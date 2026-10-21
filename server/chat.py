"""Persistent chat records; expiry only controls the public history window."""

import time
from datetime import datetime, timezone

from .site_settings import SiteSettings


class Chat:
    def __init__(self, db):
        self.db = db
        self.site_settings = SiteSettings(db)

    @staticmethod
    def _public(message):
        return {
            "user": message["username"],
            "text": message["text"],
            "time": datetime.fromtimestamp(message["created_at"], timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        }

    def history(self):
        hours = self.site_settings.read()["chat_history_hours"]
        cutoff = time.time() - hours * 3600
        messages = self.db.all(
            "SELECT username,text,created_at FROM chat_messages WHERE created_at>? ORDER BY created_at,id",
            (cutoff,),
        )
        return {
            "history_hours": hours,
            "messages": [self._public(message) for message in messages],
        }

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
