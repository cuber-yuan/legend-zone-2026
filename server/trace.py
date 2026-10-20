"""Public, persistent and bounded per-turn I/O recording."""

import json
import logging
from dataclasses import asdict

from .util import now

log = logging.getLogger(__name__)
LIMIT = 16 * 1024 * 1024


class Trace:
    def __init__(self, db, match_id):
        self.db, self.match_id = db, match_id
        self.sequence = 0
        self.used = 0
        self.incomplete = False
        self.truncated = False
        with db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO match_debug_sessions(match_id,created_at) VALUES (?,?)",
                (match_id, now()),
            )

    def event(self, turn, actor, result, kind="bot"):
        try:
            event = (
                asdict(result)
                if hasattr(result, "__dataclass_fields__")
                else result.copy()
            )
            event.update(actor=actor, kind=kind, truncated_fields=[])
            for key in ("input", "stdout", "stderr", "diagnostic"):
                value = event.get(key, "")
                text = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False)
                )
                raw = text.encode("utf-8")
                if len(raw) > 65536:
                    event["truncated_fields"].append(key)
                event[key] = raw[:65536].decode("utf-8", "ignore")
            payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
            size = len(payload.encode())
            if self.used + size > LIMIT:
                self.truncated = True
                return
            self.sequence += 1
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "INSERT INTO match_debug_events(match_id,sequence,turn_index,actor,status,payload) VALUES (?,?,?,?,?,?)",
                    (
                        self.match_id,
                        self.sequence,
                        turn,
                        actor,
                        event.get("status", "success"),
                        payload,
                    ),
                )
                conn.execute(
                    "UPDATE match_debug_sessions SET last_turn=?,event_count=?,stored_bytes=? WHERE match_id=?",
                    (turn, self.sequence, self.used + size, self.match_id),
                )
            self.used += size
        except Exception:
            self.incomplete = True
            log.exception("Debug persistence failed for %s", self.match_id)

    def finish(self, frames, interrupted=False):
        try:
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "UPDATE match_debug_sessions SET status=?,frame_count=?,truncated=?,incomplete=?,finished_at=? WHERE match_id=?",
                    (
                        "interrupted" if interrupted else "complete",
                        frames,
                        int(self.truncated),
                        int(self.incomplete or interrupted),
                        now(),
                        self.match_id,
                    ),
                )
        except Exception:
            log.exception("Debug finalization failed for %s", self.match_id)
