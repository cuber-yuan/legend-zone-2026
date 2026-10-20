"""Small, dependency-free helpers shared by the Python judges."""

import json
import random
from collections import deque


def integer(value):
    return type(value) is int


def protocol_int(value):
    """Match JsonCpp isInt for legacy action values, including integral floats."""
    if type(value) not in (int, float) or not -(1 << 31) <= value < (1 << 31):
        return None
    result = int(value)
    return result if result == value else None


def initial_data(value):
    if isinstance(value, str):
        value = json.loads(value)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("initdata must be an object.")
    return value.copy()


def random_source(seed):
    if seed is not None and not integer(seed):
        raise ValueError("seed must be an integer.")
    return random.Random(seed)


def connected(cells, start, directions):
    if start not in cells:
        return False
    visited = {start}
    pending = deque([start])
    while pending:
        x, y = pending.popleft()
        for dx, dy in directions:
            point = x + dx, y + dy
            if point in cells and point not in visited:
                visited.add(point)
                pending.append(point)
    return len(visited) == len(cells)


def scores(winner):
    return (
        {"0": 1, "1": 1}
        if winner == -1
        else {
            str(winner): 2,
            str(1 - winner): 0,
        }
    )


def records(actions):
    if not isinstance(actions, dict):
        raise ValueError("Round actions must be an object keyed by 0 and 1.")
    return [
        value if isinstance(value := actions.get(str(side)), dict) else {}
        for side in range(2)
    ]


def replay(judge, log):
    if log is None:
        log = []
    if not isinstance(log, list) or len(log) % 2:
        raise ValueError("log must contain judge/action pairs.")
    result = judge.initial()
    for index in range(1, len(log), 2):
        if result["command"] == "finish":
            break
        result = judge.step(log[index])
    return result
