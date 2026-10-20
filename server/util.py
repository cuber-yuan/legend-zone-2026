import json
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_json(value, default):
    if value is None or value == "":
        return default
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return default
