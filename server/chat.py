import json
import math
import os
import time
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock


class Chat:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = RLock()

    def _read(self):
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Invalid chat file.")
        messages = data["messages"]
        if not isinstance(messages, list):
            raise ValueError("Invalid chat file.")
        for m in messages:
            if (
                not isinstance(m, dict)
                or not all(isinstance(m.get(k), str) for k in ("user", "text", "time"))
                or (
                    type(m.get("created_at")) not in (int, float)
                    or not math.isfinite(m["created_at"])
                )
            ):
                raise ValueError("Invalid chat record.")
        return messages

    def _write(self, messages):
        if not messages:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".chat-",
                suffix=".tmp",
                delete=False,
            ) as f:
                name = f.name
                json.dump({"version": 1, "messages": messages}, f, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def messages(self):
        with self.lock:
            original = self._read()
            messages = [m for m in original if m["created_at"] > time.time() - 86400]
            if len(messages) != len(original):
                self._write(messages)
            return [{k: m[k] for k in ("user", "text", "time")} for m in messages]

    def send(self, user, text):
        with self.lock:
            now = time.time()
            messages = [m for m in self._read() if m["created_at"] > now - 86400]
            msg = {
                "user": user,
                "text": text,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "created_at": now,
            }
            self._write(messages + [msg])
            return {k: msg[k] for k in ("user", "text", "time")}

    def prune(self):
        self.messages()
        with self.lock:
            for path in self.path.parent.glob(".chat-*.tmp"):
                if path.is_file() and path.stat().st_mtime < time.time() - 86400:
                    path.unlink(missing_ok=True)
