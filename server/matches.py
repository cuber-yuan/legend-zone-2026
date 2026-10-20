"""Match selection, public listings and the single result persistence boundary."""

import json
import uuid

from .bots import LATEST
from .games import get_game
from .ratings import settle
from .util import now, parse_json


def create_match(db, game_value, choices, user):
    game = get_game(game_value)
    if not isinstance(choices, list) or len(choices) != 2:
        raise ValueError("Choose exactly two players.")
    if (
        sum(isinstance(p, dict) and p.get("type") == "human" for p in choices)
        > game.max_humans
    ):
        raise ValueError("This game supports at most one human player.")
    match_id = uuid.uuid4().hex
    players = {}
    snapshots = []
    with db.connect(write=True) as conn:
        for seat, choice in enumerate(choices, 1):
            if not isinstance(choice, dict):
                raise ValueError("Invalid player.")
            if choice.get("type") == "human":
                if user is None:
                    raise ValueError("Sign in to play as a human.")
                player = {
                    "type": "human",
                    "name": user["username"],
                    "user_id": user["id"],
                }
                snapshot = (
                    match_id,
                    seat,
                    "human",
                    None,
                    None,
                    None,
                    player["name"],
                    None,
                    "execution",
                )
            elif choice.get("type") == "bot":
                version = choice.get("version")
                if version is not None and (type(version) is not int or version < 1):
                    raise ValueError("Invalid version number.")
                row = conn.execute(
                    "SELECT b.*,v.id AS version_id,v.version_number FROM bots b JOIN bot_versions v ON v.bot_id=b.id "
                    "WHERE b.id=? AND (? IS NULL OR v.version_number=?) ORDER BY v.version_number DESC LIMIT 1",
                    (choice.get("bot_id"), version, version),
                ).fetchone()
                if not row or row["game"] != game.name:
                    raise ValueError("Bot or version does not belong to this game.")
                latest = conn.execute(
                    "SELECT MAX(version_number) FROM bot_versions WHERE bot_id=?",
                    (row["id"],),
                ).fetchone()[0]
                player = {
                    "type": "bot",
                    "name": row["bot_name"],
                    "bot_id": row["id"],
                    "version": row["version_number"],
                    "rating_eligible": row["version_number"] == latest,
                }
                snapshot = (
                    match_id,
                    seat,
                    "bot",
                    row["id"],
                    row["version_id"],
                    row["id"],
                    row["bot_name"],
                    row["version_number"],
                    "execution",
                )
            else:
                raise ValueError("Choose a bot or human player.")
            players[f"player_{seat}"] = player
            snapshots.append(snapshot)
        conn.execute(
            "INSERT INTO matches(id,game,players,rating_status) VALUES (?,?,?,'pending')",
            (match_id, game.name, json.dumps(players)),
        )
        conn.executemany(
            "INSERT INTO match_players(match_id,seat,player_type,bot_id,bot_version_id,bot_id_snapshot,player_name,version_number_snapshot,snapshot_source) VALUES (?,?,?,?,?,?,?,?,?)",
            snapshots,
        )
    return match_id


def participants(db, row, snapshots=None, ratings=None):
    raw = parse_json(row.get("players"), {})
    if not isinstance(raw, dict):
        raw = {}
    if snapshots is None:
        snapshots = db.all(
            "SELECT * FROM match_players WHERE match_id=? ORDER BY seat", (row["id"],)
        )
    snapshot = {p["seat"]: p for p in snapshots}
    ids = [
        p.get("bot_id") for p in raw.values() if isinstance(p, dict) and p.get("bot_id")
    ]
    ids += [p["bot_id"] for p in snapshots if p["bot_id"]]
    if ratings is None and ids:
        ratings = {
            p["id"]: p["rating"]
            for p in db.all(
                LATEST + " AND b.id IN (" + ",".join("?" for _ in ids) + ")", ids
            )
        }
    ratings = ratings or {}
    output = []
    for seat in (1, 2):
        value = raw.get(f"player_{seat}", {})
        player = value.copy() if isinstance(value, dict) else {"name": str(value)}
        if seat in snapshot:
            saved = snapshot[seat]
            player.update(
                name=saved["player_name"],
                type=saved["player_type"],
                bot_id=saved["bot_id_snapshot"],
                version=saved["version_number_snapshot"],
            )
        player.setdefault("name", f"Player {seat}")
        player["rating"] = ratings.get(player.get("bot_id"))
        output.append(player)
    return output


def public_match(db, row, *, replay=False, snapshots=None, ratings=None):
    result = {
        key: row.get(key)
        for key in (
            "id",
            "game",
            "status",
            "winner",
            "created_at",
            "started_at",
            "finished_at",
            "termination_reason",
            "rating_status",
        )
    }
    result["players"] = participants(db, row, snapshots, ratings)
    try:
        result["slug"] = get_game(row["game"]).slug
    except ValueError:
        result["slug"] = None
    if replay:
        result["move_history"] = parse_json(row.get("move_history"), [])
        result["displays"] = parse_json(row.get("displays"), [])
    return result


def list_matches(db, *, bot_id=None, game=None, limit=20, offset=0):
    sql = "SELECT m.* FROM matches m WHERE 1=1"
    params = []
    if bot_id:
        sql += " AND (EXISTS (SELECT 1 FROM match_players p WHERE p.match_id=m.id AND (p.bot_id=? OR p.bot_id_snapshot=?)) "
        sql += "OR (json_valid(m.players) AND (json_extract(m.players,'$.player_1.bot_id')=? OR json_extract(m.players,'$.player_2.bot_id')=?)))"
        params += [bot_id] * 4
    if game:
        sql += " AND m.game=?"
        params.append(get_game(game).name)
    rows = db.all(
        sql + " ORDER BY m.created_at DESC,m.rowid DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    )
    ids = [row["id"] for row in rows]
    snapshots = {key: [] for key in ids}
    if ids:
        for player in db.all(
            "SELECT * FROM match_players WHERE match_id IN ("
            + ",".join("?" for _ in ids)
            + ") ORDER BY seat",
            ids,
        ):
            snapshots[player["match_id"]].append(player)
    bot_ids = {
        p["bot_id"] for values in snapshots.values() for p in values if p["bot_id"]
    }
    for row in rows:
        raw = parse_json(row.get("players"), {})
        if isinstance(raw, dict):
            bot_ids.update(
                p["bot_id"]
                for p in raw.values()
                if isinstance(p, dict) and p.get("bot_id")
            )
    ratings = (
        {
            bot["id"]: bot["rating"]
            for bot in db.all(
                LATEST + " AND b.id IN (" + ",".join("?" for _ in bot_ids) + ")",
                list(bot_ids),
            )
        }
        if bot_ids
        else {}
    )
    result = [
        public_match(db, row, snapshots=snapshots[row["id"]], ratings=ratings)
        for row in rows
    ]
    if bot_id:
        for item in result:
            if any(p.get("type") == "human" for p in item["players"]):
                item["rating_delta"] = None
                continue
            history = db.one(
                "SELECT h.rating-(SELECT p.rating FROM rating_history p WHERE p.version_id=h.version_id AND p.id<h.id ORDER BY p.id DESC LIMIT 1) AS delta "
                "FROM rating_history h WHERE h.bot_id=? AND h.match_id=?",
                (bot_id, item["id"]),
            )
            item["rating_delta"] = (
                history["delta"]
                if history
                else 0
                if item["rating_status"] == "skipped"
                else None
            )
    return result


def persist_result(db, match_id, winner, history, displays, reason, error):
    # Result is committed before either ratings or debug finalization.
    with db.connect(write=True) as conn:
        conn.execute(
            "UPDATE matches SET winner=?,move_history=?,displays=?,status='finished',finished_at=?,termination_reason=?,error_message=? WHERE id=? AND status='playing'",
            (
                winner,
                json.dumps(history),
                json.dumps(displays),
                now(),
                reason,
                error,
                match_id,
            ),
        )
    try:
        settle(db, match_id)
    except Exception:
        with db.connect(write=True) as conn:
            conn.execute(
                "UPDATE matches SET rating_status='failed',rating_error='Rating settlement failed; explicit review required.' WHERE id=? AND rating_status NOT IN ('applied','skipped')",
                (match_id,),
            )
        raise
