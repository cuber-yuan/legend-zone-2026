"""One worker loop for board games, one for simultaneous games; shared lifecycle."""

import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Condition, Event, Lock, Thread

from .bots import list_bots, selected_version
from .bot_queue import BotMatchQueue, MatchCapacityError
from .execution import Execution, Executor
from .game_state import snapshot
from .games import GAMES, create_judge, get_game
from .matches import create_match, persist_result
from .trace import Trace
from .site_settings import SiteSettings
from .util import now, parse_json

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    owner: int | None
    condition: Condition = field(default_factory=Condition)
    history: list = field(default_factory=list)
    displays: list = field(default_factory=list)
    waiting: list = field(default_factory=list)
    moves: dict = field(default_factory=dict)
    turn: int = 0
    state: dict = field(default_factory=dict)
    pending_result: tuple | None = None
    trace: object = None
    error: str | None = None

    def view(self):
        with self.condition:
            return deepcopy(
                {
                    "move_history": self.history,
                    "displays": self.displays,
                    "waiting": self.waiting,
                    "turn": self.turn,
                    "state": self.state,
                    "save_error": self.error,
                }
            )


class Matches:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.executor = Executor(settings)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="match")
        self.jobs = {}
        self.lock = Lock()
        self.stopping = Event()
        self.scheduler = None
        self.bot_queue = BotMatchQueue(self)

    def create(self, game, players, user=None):
        with self.lock:
            if self.stopping.is_set():
                raise ValueError("The server is shutting down.")
            if (
                len(self.jobs) >= 32
                or user
                and sum(job.owner == user["id"] for job in self.jobs.values()) >= 4
            ):
                raise MatchCapacityError("Too many pending matches. Please wait.")
            match_id = create_match(self.db, game, players, user)
            job = Job(match_id, user["id"] if user else None)
            self.jobs[match_id] = job
            self.pool.submit(self._run, job)
        return match_id

    def submit(self, match_id, user, seat, turn, action):
        with self.lock:
            job = self.jobs.get(match_id)
        if not job:
            raise ValueError("This match is not accepting moves.")
        row = self.db.one("SELECT players FROM matches WHERE id=?", (match_id,))
        player = parse_json(row["players"], {}).get(f"player_{seat}", {})
        if player.get("type") != "human" or player.get("user_id") != user["id"]:
            raise PermissionError("This seat belongs to another player.")
        with job.condition:
            if (
                type(turn) is not int
                or turn != job.turn
                or seat not in job.waiting
                or seat in job.moves
            ):
                raise ValueError("This move is stale or has already been submitted.")
            job.moves[seat] = action
            job.condition.notify_all()

    def _human(self, job, seat, payload):
        result = Execution(json.dumps(payload), exit_code=0)
        start = time.monotonic()
        with job.condition:
            job.waiting.append(seat)
            deadline = start + self.settings.human_timeout
            while seat not in job.moves and not self.stopping.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                job.condition.wait(timeout=remaining)
            job.waiting.remove(seat)
            if self.stopping.is_set():
                raise InterruptedError("Server shutdown.")
            if seat not in job.moves:
                result.status = "timeout"
                result.diagnostic = "Human move timed out."
            else:
                result.stdout = json.dumps(job.moves.pop(seat))
        result.duration_ms = round((time.monotonic() - start) * 1000, 3)
        return result

    def _action(self, job, players, versions, seat, payload):
        result = (
            self._human(job, seat, payload)
            if players[seat - 1]["type"] == "human"
            else self.executor.execute(versions[seat - 1], payload)
        )
        action = result.action() if result.status == "success" else None
        return action, result

    def _run(self, job):
        winner, reason, error = -1, "server_error", None
        trace = None
        try:
            row = self.db.one("SELECT * FROM matches WHERE id=?", (job.id,))
            game = get_game(row["game"])
            raw = parse_json(row["players"], {})
            players = [raw[f"player_{seat}"] for seat in (1, 2)]
            versions = [None, None]
            for index, player in enumerate(players):
                if player["type"] == "bot":
                    versions[index] = selected_version(
                        self.db, player["bot_id"], player["version"]
                    )
                    if versions[index] is None:
                        raise ValueError("A selected bot version no longer exists.")
                    latest = selected_version(self.db, player["bot_id"])
                    player["rating_eligible"] &= bool(
                        latest and latest["version_id"] == versions[index]["version_id"]
                    )
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "UPDATE matches SET started_at=?,players=? WHERE id=?",
                    (now(), json.dumps(raw), job.id),
                )
            trace = job.trace = Trace(self.db, job.id)
            judge = create_judge(game.slug)
            initial = (
                judge.initial()
                if game.kind != "board"
                else {"board": judge.board, "side": judge.side}
            )
            trace.event(
                0,
                "judge",
                {"input": {}, "stdout": initial, "status": "success"},
                "judge",
            )
            with job.condition:
                if game.kind != "board":
                    job.displays.append(initial["display"])
                job.state = snapshot(judge, game, job.state)
            requests = (
                [[initial["content"][str(side)]] for side in range(2)]
                if game.kind != "board"
                else None
            )
            responses = [[], []]
            reason = "turn_limit"
            for turn in range(1, game.max_turns + 1):
                if self.stopping.is_set():
                    raise InterruptedError("Server shutdown.")
                with job.condition:
                    job.turn = turn
                if game.kind == "board":
                    seat = judge.side
                    payload = {
                        "move_history": deepcopy(judge.history),
                        "your_side": seat,
                    }
                    action, result = self._action(job, players, versions, seat, payload)
                    if result.status == "success":
                        try:
                            outcome = judge.apply(action)
                        except ValueError:
                            result.status = "invalid_move"
                            result.diagnostic = "The move is not legal."
                            outcome = 1 if seat == 1 else 0
                    else:
                        outcome = 1 if seat == 1 else 0
                    trace.event(
                        turn, f"player_{seat}", result, players[seat - 1]["type"]
                    )
                    trace.event(
                        turn,
                        "judge",
                        {
                            "input": {
                                "action": action,
                                "move_history": payload["move_history"],
                            },
                            "stdout": {
                                "winner": outcome,
                                "move_history": judge.history,
                            },
                            "status": "success",
                        },
                        "judge",
                    )
                    with job.condition:
                        job.history = deepcopy(judge.history)
                        job.state = snapshot(judge, game, job.state)
                    if outcome is not None:
                        winner = outcome
                        reason = (
                            "normal" if result.status == "success" else result.status
                        )
                        error = result.diagnostic or None
                        break
                else:
                    actions = {}
                    results = []
                    for seat in (1, 2):
                        payload = {
                            "requests": deepcopy(requests[seat - 1]),
                            "responses": deepcopy(responses[seat - 1]),
                        }
                        action, result = self._action(
                            job, players, versions, seat, payload
                        )
                        actions[str(seat - 1)] = {
                            "response": action.get("response")
                            if isinstance(action, dict)
                            else None,
                            "verdict": result.status,
                        }
                        results.append(result)
                    output = judge.step(actions)
                    for index, result in enumerate(results):
                        if result.status == "success" and output["command"] == "finish":
                            # Rule violations are reflected on the acting bot's status.
                            losing = output["content"].get(str(index)) == 0
                            reasons = output["display"].get("loseReason", [])
                            invalid = (
                                game.kind == "snake"
                                and output["display"].get("err") == "INVALIDMOVE"
                                or index < len(reasons)
                                and str(reasons[index]).startswith("INVALID_INPUT")
                            )
                            if losing and invalid:
                                result.status = "invalid_move"
                        trace.event(
                            turn, f"player_{index + 1}", result, players[index]["type"]
                        )
                    trace.event(
                        turn,
                        "judge",
                        {"input": actions, "stdout": output, "status": "success"},
                        "judge",
                    )
                    with job.condition:
                        job.displays.append(output["display"])
                        job.state = snapshot(judge, game, job.state)
                    if output["command"] == "finish":
                        winner = judge.winner
                        failures = [r for r in results if r.status != "success"]
                        reason = (
                            "double_forfeit"
                            if len(failures) == 2
                            else failures[0].status
                            if failures
                            else "normal"
                        )
                        error = next(
                            (r.diagnostic for r in failures if r.diagnostic), None
                        )
                        break
                    for side in range(2):
                        responses[side].append(actions[str(side)]["response"])
                        requests[side].append(output["content"][str(side)])
            else:
                winner = -1
        except Exception:
            log.exception("Match %s interrupted", job.id)
            winner, reason, error = (
                -1,
                "server_error",
                "The match was interrupted by a server error or shutdown.",
            )
        finally:
            job.pending_result = (
                winner,
                deepcopy(job.history),
                deepcopy(job.displays),
                reason,
                error,
            )
            self._save(job)

    def _save(self, job):
        try:
            persist_result(self.db, job.id, *job.pending_result)
        except Exception:
            # If ratings failed after result commit, the saved match is still final.
            job.error = "Result storage failed. The server will retry."
            try:
                row = self.db.one("SELECT status FROM matches WHERE id=?", (job.id,))
            except Exception:
                log.exception("Result persistence pending for %s", job.id)
                return
            if not row or row["status"] != "finished":
                job.error = "Result storage failed. The server will retry."
                log.exception("Result persistence pending for %s", job.id)
                return
            log.exception("Result saved, rating failed for %s", job.id)
        if job.trace:
            job.trace.finish(
                len(job.history) if job.history else max(0, len(job.displays) - 1),
                job.pending_result[3] == "server_error",
            )
        with self.lock:
            self.jobs.pop(job.id, None)

    def start(self):
        self.bot_queue.start()
        self.scheduler = Thread(target=self._schedule, name="maintenance", daemon=True)
        self.scheduler.start()

    def _schedule(self):
        interval = None
        next_auto = float("inf")
        site_settings = SiteSettings(self.db)
        while not self.stopping.is_set():
            try:
                configured_interval = site_settings.read()["ladder_interval_seconds"]
                now = time.monotonic()
                if configured_interval != interval:
                    interval = configured_interval
                    next_auto = now + interval if interval else float("inf")
                with self.lock:
                    pending = [
                        job
                        for job in self.jobs.values()
                        if job.error and job.pending_result
                    ]
                for job in pending:
                    self._save(job)
                if interval and now >= next_auto:
                    next_auto = now + interval
                    for game in GAMES:
                        bots = list_bots(self.db, game)
                        if len(bots) >= 2:
                            selected = random.sample(bots, 2)
                            self.create(
                                game,
                                [
                                    {"type": "bot", "bot_id": bot["id"]}
                                    for bot in selected
                                ],
                            )
            except Exception:
                log.exception("Maintenance task failed")
            if self.stopping.wait(30):
                break

    def close(self):
        self.stopping.set()
        self.bot_queue.close()
        with self.lock:
            jobs = list(self.jobs.values())
        for job in jobs:
            with job.condition:
                job.condition.notify_all()
        if self.scheduler:
            self.scheduler.join(timeout=2)
        self.pool.shutdown(wait=True, cancel_futures=False)
