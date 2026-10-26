"""Persistent site settings and per-game Bot execution limits."""

from .games import GAMES, get_game

MAX_CHAT_HISTORY_HOURS = 8760
MAX_LADDER_INTERVAL_SECONDS = 604800
MAX_BOT_STEP_TIMEOUT_MS = 60000


class SiteSettings:
    def __init__(self, db):
        self.db = db

    def read(self):
        settings = self.db.one(
            "SELECT chat_history_hours,ladder_interval_seconds FROM site_settings WHERE singleton=1"
        )
        if settings is None:
            raise ValueError("Site settings are missing. Contact the administrator.")
        settings["bot_time_limits_ms"] = self.bot_time_limits()
        return settings

    def bot_time_limits(self):
        rows = self.db.all("SELECT name,bot_step_timeout_ms FROM games")
        values = {row["name"]: row["bot_step_timeout_ms"] for row in rows}
        if any(game.name not in values for game in GAMES.values()):
            raise ValueError("Game time limit settings are missing.")
        return {slug: values[game.name] for slug, game in GAMES.items()}

    def bot_step_timeout(self, game):
        return self.bot_time_limits()[get_game(game).slug] / 1000

    def update(
        self, chat_history_hours, ladder_interval_seconds, bot_time_limits_ms=None
    ):
        if (
            type(chat_history_hours) is not int
            or not 1 <= chat_history_hours <= MAX_CHAT_HISTORY_HOURS
        ):
            raise ValueError(
                f"Chat history hours must be an integer between 1 and {MAX_CHAT_HISTORY_HOURS}."
            )
        if (
            type(ladder_interval_seconds) is not int
            or not 0 <= ladder_interval_seconds <= MAX_LADDER_INTERVAL_SECONDS
            or ladder_interval_seconds % 60
        ):
            raise ValueError(
                "Automatic ladder interval must be a whole number of minutes between 0 and 10080."
            )
        if bot_time_limits_ms is not None:
            if set(bot_time_limits_ms) != set(GAMES) or any(
                type(value) is not int
                or not 100 <= value <= MAX_BOT_STEP_TIMEOUT_MS
                or value % 100
                for value in bot_time_limits_ms.values()
            ):
                raise ValueError(
                    "Set a time limit for every game: 0.1–60 seconds in 0.1-second increments."
                )
        with self.db.connect(write=True) as conn:
            updated = conn.execute(
                "UPDATE site_settings SET chat_history_hours=?,ladder_interval_seconds=? WHERE singleton=1",
                (chat_history_hours, ladder_interval_seconds),
            )
            if updated.rowcount != 1:
                raise ValueError(
                    "Site settings are missing. Contact the administrator."
                )
            if bot_time_limits_ms is not None:
                for slug, value in bot_time_limits_ms.items():
                    updated = conn.execute(
                        "UPDATE games SET bot_step_timeout_ms=? WHERE name=?",
                        (value, GAMES[slug].name),
                    )
                    if updated.rowcount != 1:
                        raise ValueError("Game time limit settings are missing.")
        return self.read()
