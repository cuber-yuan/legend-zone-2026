import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictInt

from .game_state import replay_frames, snapshot
from .games import GAMES, create_judge, get_game
from .matches import list_matches, public_match
from .security import require_user
from .util import parse_json

router = APIRouter(prefix="/api")


@router.get("/games")
def games():
    return [game.public() for game in GAMES.values()]


@router.get("/games/{slug}/initial")
def initial(slug: str):
    game = get_game(slug)
    return snapshot(create_judge(slug), game)


@router.get("/matches")
def listing(
    request: Request,
    bot: str | None = None,
    game: str | None = None,
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0, le=1000000),
):
    return list_matches(
        request.app.state.db, bot_id=bot, game=game, limit=limit, offset=offset
    )


class MatchChoice(BaseModel):
    game: str
    players: list[dict] = Field(min_length=2, max_length=2)


@router.post("/matches")
def create(body: MatchChoice, request: Request, user=Depends(require_user)):
    return {"id": request.app.state.matches.create(body.game, body.players, user)}


@router.get("/matches/{match_id}")
def detail(match_id: str, request: Request):
    db = request.app.state.db
    row = db.one("SELECT * FROM matches WHERE id=?", (match_id,))
    if not row:
        raise HTTPException(404, "Match not found.")
    result = public_match(db, row, replay=True)
    runtime = request.app.state.matches
    with runtime.lock:
        job = runtime.jobs.get(match_id)
    result["waiting"] = []
    if job:
        result.update(job.view())
    elif row["status"] == "playing":
        result["status"] = "interrupted"
    session = db.one(
        "SELECT frame_count,last_turn FROM match_debug_sessions WHERE match_id=?",
        (match_id,),
    )
    result["turn_count"] = max(
        result.get("turn", 0),
        len(result["move_history"]),
        max(0, len(result["displays"]) - 1),
        session["frame_count"] if session else 0,
    )
    if row["status"] == "finished" and result["slug"]:
        try:
            result["frames"] = replay_frames(
                result["slug"],
                json.dumps(result["move_history"]),
                json.dumps(result["displays"]),
            )
        except (ValueError, TypeError, KeyError, IndexError):
            result["frames"] = []
            result["replay_error"] = "Replay data is incomplete."
    return result


class Move(BaseModel):
    seat: StrictInt = Field(ge=1, le=2)
    turn: StrictInt = Field(ge=1)
    action: dict


@router.post("/matches/{match_id}/moves")
def move(match_id: str, body: Move, request: Request, user=Depends(require_user)):
    try:
        request.app.state.matches.submit(
            match_id, user, body.seat, body.turn, body.action
        )
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    return {"ok": True}


@router.get("/matches/{match_id}/debug")
def debug(match_id: str, request: Request):
    db = request.app.state.db
    if not db.one("SELECT 1 FROM matches WHERE id=?", (match_id,)):
        raise HTTPException(404, "Match not found.")
    session = db.one("SELECT * FROM match_debug_sessions WHERE match_id=?", (match_id,))
    events = db.all(
        "SELECT turn_index,sequence,actor,status,payload FROM match_debug_events WHERE match_id=? ORDER BY sequence",
        (match_id,),
    )
    for event in events:
        event["payload"] = parse_json(event["payload"], {})
        event.update(event["payload"], turn=event["turn_index"])
    result = {"session": session, "events": events, "available": bool(session)}
    if session:
        result.update(
            {
                key: session[key]
                for key in (
                    "status",
                    "frame_count",
                    "last_turn",
                    "truncated",
                    "incomplete",
                    "error",
                    "schema_version",
                )
            }
        )
        result["failure_turn"] = (
            session["last_turn"]
            if session["last_turn"] > session["frame_count"]
            else None
        )
    return result
