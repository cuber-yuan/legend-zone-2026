"""Persistent site settings shared by chat and the automatic ladder."""

MAX_CHAT_HISTORY_HOURS = 8760
MAX_LADDER_INTERVAL_SECONDS = 604800


class SiteSettings:
    def __init__(self, db):
        self.db = db

    def read(self):
        settings = self.db.one(
            "SELECT chat_history_hours,ladder_interval_seconds FROM site_settings WHERE singleton=1"
        )
        if settings is None:
            raise ValueError("Site settings are missing. Contact the administrator.")
        return settings

    def update(self, chat_history_hours, ladder_interval_seconds):
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
        with self.db.connect(write=True) as conn:
            updated = conn.execute(
                "UPDATE site_settings SET chat_history_hours=?,ladder_interval_seconds=? WHERE singleton=1",
                (chat_history_hours, ladder_interval_seconds),
            )
            if updated.rowcount != 1:
                raise ValueError(
                    "Site settings are missing. Contact the administrator."
                )
        return {
            "chat_history_hours": chat_history_hours,
            "ladder_interval_seconds": ladder_interval_seconds,
        }
