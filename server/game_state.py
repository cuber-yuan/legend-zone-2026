"""Serializable rendering snapshots derived from authoritative Python judges."""

import json
from copy import deepcopy
from functools import lru_cache

from .games import create_judge, get_game


def snapshot(judge, game, previous=None):
    if game.kind == "board":
        return {"board": deepcopy(judge.board), "side": judge.side}
    if game.kind == "snake":
        return {
            "bodies": [list(body) for body in judge.bodies],
            "width": judge.width,
            "height": judge.height,
            "obstacle": deepcopy(judge.initdata["obstacle"]),
        }
    directions = deepcopy((previous or {}).get("directions", [[2, 2], [0, 0]]))
    for side in range(2):
        for tank in range(2):
            if judge.previous[side][tank] >= 0:
                directions[side][tank] = judge.previous[side][tank] % 4
    return {
        "board": deepcopy(judge.board),
        "positions": deepcopy(judge.positions),
        "base_alive": judge.base_alive.copy(),
        "previous": deepcopy(judge.previous),
        "directions": directions,
        "legal_actions": [
            [judge.legal_actions(side, tank) for tank in range(2)] for side in range(2)
        ],
    }


@lru_cache(maxsize=16)
def replay_frames(slug, history_json, displays_json):
    game = get_game(slug)
    history = json.loads(history_json)
    displays = json.loads(displays_json)
    initdata = None
    if game.kind == "snake":
        if not displays:
            return []
        initdata = displays[0]
    elif game.kind == "tank":
        if not displays:
            return []
        display = displays[0]
        initdata = (
            {
                "brickfield": display.get("brick", [0, 0, 0]),
                "waterfield": display.get("water", [0, 0, 0]),
                "steelfield": display.get("steel", [0, 0, 0]),
            }
            if isinstance(display, dict)
            else {
                "brickfield": display,
                "waterfield": [0, 0, 0],
                "steelfield": [0, 0, 0],
            }
        )
    judge = create_judge(slug, initdata)
    frames = [snapshot(judge, game)]
    if game.kind == "board":
        for move in history:
            if judge.winner is None:
                judge.apply(move)
            frames.append(snapshot(judge, game))
    else:
        for display in displays[1:]:
            if judge.winner is None:
                actions = {
                    str(side): {
                        "response": (
                            {"direction": display.get(str(side))}
                            if game.kind == "snake"
                            else display.get(str(side))
                        )
                    }
                    for side in range(2)
                }
                judge.step(actions)
            frames.append(snapshot(judge, game, frames[-1]))
    return frames
