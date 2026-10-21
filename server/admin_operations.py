"""Explicit, game-scoped maintenance under the match creation lock."""

from .games import get_game


class OperationConflict(ValueError):
    pass


def perform(matches, game_value, action, confirmation):
    game = get_game(game_value)
    phrases = {"clear-matches": "CLEAR MATCHES", "reset-ratings": "RESET RATINGS"}
    if action not in phrases:
        raise ValueError("Unknown operation.")
    if confirmation != f"{phrases[action]} {game.name}":
        raise ValueError("Confirmation text does not match.")
    # Creation uses this same lock. Existing workers remain visible in jobs until
    # result, rating and trace finalization have all completed.
    with matches.lock, matches.db.connect(write=True) as conn:
        rows = conn.execute(
            "SELECT id,status,rating_status FROM matches WHERE game=?", (game.name,)
        ).fetchall()
        if any(row["status"] == "playing" or row["id"] in matches.jobs for row in rows):
            raise OperationConflict(
                "This game has active or unsaved matches. Wait for them to finish."
            )
        if action == "clear-matches":
            scope = "SELECT id FROM matches WHERE game=?"
            # Preserve the rating curve while removing links to deleted replays.
            conn.execute(
                f"UPDATE rating_history SET match_id=NULL WHERE match_id IN ({scope})",
                (game.name,),
            )
            for table in (
                "match_debug_events",
                "match_debug_sessions",
                "match_players",
            ):
                conn.execute(
                    f"DELETE FROM {table} WHERE match_id IN ({scope})", (game.name,)
                )
            count = conn.execute(
                "DELETE FROM matches WHERE game=?", (game.name,)
            ).rowcount
            return {"deleted_matches": count}
        if any(
            row["rating_status"] in ("pending", "failed", "unknown") for row in rows
        ):
            raise OperationConflict(
                "This game has unsettled ratings. Resolve them before resetting ratings."
            )
        scope = "SELECT id FROM bots WHERE game=?"
        conn.execute(
            f"DELETE FROM rating_history WHERE bot_id IN ({scope})", (game.name,)
        )
        count = conn.execute(
            f"UPDATE bot_versions SET rating=1500 WHERE bot_id IN ({scope})",
            (game.name,),
        ).rowcount
        conn.execute(
            f"INSERT INTO rating_history(bot_id,version_id,rating) SELECT bot_id,id,1500 FROM bot_versions WHERE bot_id IN ({scope})",
            (game.name,),
        )
        return {"reset_versions": count, "rating": 1500}
