"""Python rule engines. No compiler, files, subprocesses or application state."""

from .common import replay
from .snake import Snake
from .tank import Tank


def evaluate(game, payload):
    """Evaluate a legacy judge initdata/log request without launching a process."""
    if not isinstance(payload, dict):
        raise ValueError("Judge input must be an object.")
    if game in ("snake", "msnake"):
        judge = Snake(payload.get("initdata"), mini=game == "msnake")
    elif game == "tank":
        judge = Tank(payload.get("initdata"))
    else:
        raise ValueError("Unknown simultaneous game.")
    return replay(judge, payload.get("log"))
