"""Persistent chat records; expiry only controls the public history window."""

import time
from datetime import datetime

MAX_HISTORY_HOURS = 8760


class Chat:
    def __init__(self, db):
        self.db = db

    def settings(self):
        value = self.db.one("SELECT history_hours FROM chat_settings WHERE singleton=1")
        if value is None:
            raise ValueError(
                "Chat settings are missing. Run the explicit chat upgrade."
            )
        return value

    def configure(self, history_hours):
        if (
            type(history_hours) is not int
            or not 1 <= history_hours <= MAX_HISTORY_HOURS
        ):
            raise ValueError(
                f"History hours must be an integer between 1 and {MAX_HISTORY_HOURS}."
            )
        with self.db.connect(write=True) as conn:
            updated = conn.execute(
                "UPDATE chat_settings SET history_hours=? WHERE singleton=1",
                (history_hours,),
            )
            if updated.rowcount != 1:
                raise ValueError(
                    "Chat settings are missing. Run the explicit chat upgrade."
                )
        return {"history_hours": history_hours}

    @staticmethod
    def _public(message):
        return {
            "user": message["username"],
            "text": message["text"],
            "time": datetime.fromtimestamp(message["created_at"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }

    def history(self):
        settings = self.settings()
        cutoff = time.time() - settings["history_hours"] * 3600
        messages = self.db.all(
            "SELECT username,text,created_at FROM chat_messages WHERE created_at>? ORDER BY created_at,id",
            (cutoff,),
        )
        return settings | {"messages": [self._public(message) for message in messages]}

    def send(self, user, text):
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError("Messages must contain 1 to 2000 characters.")
        message = {"username": user, "text": text.strip(), "created_at": time.time()}
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO chat_messages(username,text,created_at) VALUES (?,?,?)",
                (message["username"], message["text"], message["created_at"]),
            )
        return self._public(message)
