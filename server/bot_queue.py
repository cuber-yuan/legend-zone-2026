"""A bounded, in-process FIFO for administrator-requested rated Bot matches."""

import logging
import random
from collections import OrderedDict
from copy import deepcopy
from threading import Lock, Thread

from .bots import LATEST, list_bots
from .games import get_game
from .util import now

log = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "stopped"}


class QueueConflict(ValueError):
    pass


class MatchCapacityError(ValueError):
    pass


class BotMatchQueue:
    def __init__(self, matches):
        self.matches = matches
        self.lock = Lock()
        self.batches = OrderedDict()
        self.thread = None

    def lookup(self, bot_id):
        bot = self.matches.db.one(LATEST + " AND b.id=?", (bot_id,))
        if not bot:
            raise ValueError("Bot not found or has no versions.")
        get_game(bot["game"])
        return {
            "id": bot["id"],
            "name": bot["bot_name"],
            "game": bot["game"],
            "version": bot["version_number"],
            "opponents": len(self._opponents(bot)),
        }

    def _opponents(self, bot):
        return [
            item
            for item in list_bots(self.matches.db, bot["game"])
            if item["id"] != bot["id"]
        ]

    def enqueue(self, bot_id, count, request_id):
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("Choose between 1 and 100 matches.")
        with self.lock:
            if request_id in self.batches:
                existing = self.batches[request_id]
                if existing["bot_id"] != bot_id or existing["total"] != count:
                    raise QueueConflict(
                        "This request ID was already used for another batch."
                    )
                return deepcopy(existing)
            if self.matches.stopping.is_set():
                raise QueueConflict("The server is shutting down.")
            if (
                sum(item["status"] not in TERMINAL for item in self.batches.values())
                >= 10
            ):
                raise QueueConflict(
                    "The batch queue is full. Wait for a batch to finish."
                )
            bot = self.lookup(bot_id)
            if not bot["opponents"]:
                raise ValueError("This game has no other Bots available as opponents.")
            batch = {
                "id": request_id,
                "bot_id": bot_id,
                "bot_name": bot["name"],
                "game": bot["game"],
                "total": count,
                "completed": 0,
                "rated": 0,
                "skipped": 0,
                "status": "queued",
                "current_match": None,
                "last_match": None,
                "error": None,
                "created_at": now(),
            }
            self.batches[request_id] = batch
            while len(self.batches) > 50:
                removable = next(
                    key
                    for key, item in self.batches.items()
                    if item["status"] in TERMINAL
                )
                del self.batches[removable]
            return deepcopy(batch)

    def listing(self):
        with self.lock:
            return deepcopy(list(self.batches.values()))

    def has_pending(self, game):
        with self.lock:
            return any(
                item["game"] == game and item["status"] not in TERMINAL
                for item in self.batches.values()
            )

    def step(self):
        # Only this coordinator advances batches; API readers share the small lock.
        with self.lock:
            batch = next(
                (
                    item
                    for item in self.batches.values()
                    if item["status"] not in TERMINAL
                ),
                None,
            )
            if not batch or self.matches.stopping.is_set():
                return
            match_id = batch["current_match"]
        if match_id:
            with self.matches.lock:
                if match_id in self.matches.jobs:
                    return
            row = self.matches.db.one(
                "SELECT status,rating_status FROM matches WHERE id=?", (match_id,)
            )
            with self.lock:
                if (
                    not row
                    or row["status"] != "finished"
                    or row["rating_status"] not in ("applied", "skipped")
                ):
                    batch["status"] = "failed"
                    batch["error"] = (
                        "Match storage or rating settlement requires review. Remaining matches were stopped."
                    )
                    return
                batch["completed"] += 1
                batch["rated" if row["rating_status"] == "applied" else "skipped"] += 1
                batch["last_match"] = match_id
                batch["current_match"] = None
                if batch["completed"] == batch["total"]:
                    batch["status"] = "completed"
                    return
        bot = self.lookup(batch["bot_id"])
        if bot["game"] != batch["game"]:
            raise ValueError("The selected Bot no longer belongs to this game.")
        opponents = self._opponents({"id": bot["id"], "game": bot["game"]})
        if not opponents:
            raise ValueError("No opponents remain for this game.")
        opponent = random.choice(opponents)
        players = [
            {"type": "bot", "bot_id": bot["id"]},
            {"type": "bot", "bot_id": opponent["id"]},
        ]
        random.shuffle(players)
        try:
            match_id = self.matches.create(bot["game"], players)
        except MatchCapacityError:
            return  # Respect the shared 32-match capacity, and retry next tick.
        with self.lock:
            batch["current_match"] = match_id
            batch["status"] = "running"

    def _run(self):
        while not self.matches.stopping.is_set():
            try:
                self.step()
            except Exception as error:
                log.exception("Administrator Bot batch failed")
                with self.lock:
                    batch = next(
                        (
                            item
                            for item in self.batches.values()
                            if item["status"] not in TERMINAL
                        ),
                        None,
                    )
                    if batch:
                        batch["status"] = "failed"
                        batch["error"] = (
                            str(error)
                            if isinstance(error, ValueError)
                            else "Unable to continue this batch. Check the server logs."
                        )
            if self.matches.stopping.wait(1):
                break
        with self.lock:
            for batch in self.batches.values():
                if batch["status"] not in TERMINAL:
                    batch["status"] = "stopped"
                    batch["error"] = (
                        "The server stopped. Unstarted matches were discarded."
                    )

    def start(self):
        self.thread = Thread(target=self._run, name="bot-batch", daemon=True)
        self.thread.start()

    def close(self):
        if self.thread:
            self.thread.join(timeout=2)
