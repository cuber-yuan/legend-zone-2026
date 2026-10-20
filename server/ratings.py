"""Atomic, idempotent Elo settlement using actual execution snapshots."""

import json

from .util import now


def settle(db, match_id):
    with db.connect(write=True) as conn:
        match = conn.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not match or match["status"] != "finished":
            raise ValueError("A saved result is required.")
        if match["rating_status"] in ("applied", "skipped"):
            return match["rating_status"]
        players = json.loads(match["players"])
        versions = conn.execute(
            "SELECT p.*,v.rating FROM match_players p LEFT JOIN bot_versions v ON v.id=p.bot_version_id WHERE match_id=? ORDER BY seat",
            (match_id,),
        ).fetchall()
        allowed = (
            len(versions) == 2
            and match["termination_reason"] not in ("server_error", "unsupported")
            and all(
                p["player_type"] == "bot"
                and p["snapshot_source"] == "execution"
                and p["bot_version_id"] is not None
                for p in versions
            )
            and versions[0]["bot_id"] != versions[1]["bot_id"]
            and all(
                players[f"player_{seat}"].get("rating_eligible") is True
                for seat in (1, 2)
            )
        )
        if not allowed:
            conn.execute(
                "UPDATE matches SET rating_status='skipped',rating_error=NULL WHERE id=?",
                (match_id,),
            )
            return "skipped"
        history = conn.execute(
            "SELECT version_id FROM rating_history WHERE match_id=?", (match_id,)
        ).fetchall()
        if history:
            if {p["version_id"] for p in history} != {
                p["bot_version_id"] for p in versions
            }:
                raise ValueError("Partial rating history requires review.")
        else:
            a, b = [p["rating"] if p["rating"] is not None else 1500 for p in versions]
            expected = 1 / (1 + 10 ** (max(-4000, min(4000, b - a)) / 400))
            actual = 0.5 if match["winner"] == -1 else 1 if match["winner"] == 0 else 0
            change = 32 * (actual - expected)
            for player, rating in zip(versions, (a + change, b - change)):
                conn.execute(
                    "UPDATE bot_versions SET rating=? WHERE id=?",
                    (rating, player["bot_version_id"]),
                )
                conn.execute(
                    "INSERT INTO rating_history(bot_id,version_id,match_id,rating) VALUES (?,?,?,?)",
                    (player["bot_id"], player["bot_version_id"], match_id, rating),
                )
        conn.execute(
            "UPDATE matches SET rating_status='applied',rating_error=NULL,rated_at=? WHERE id=?",
            (now(), match_id),
        )
    return "applied"
