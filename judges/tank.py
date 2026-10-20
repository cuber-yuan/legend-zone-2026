"""Python port of Tank2 rules (original: 289371298, based on zhouhy).

Coordinates are zero-based board[y][x]. Terrain is encoded in three 27-bit
integers. Movement and shooting are simultaneous within their respective phases.
"""

from copy import deepcopy
from secrets import randbits

from .common import (
    connected,
    initial_data,
    integer,
    protocol_int,
    random_source,
    records,
    scores,
)

EMPTY, BRICK, STEEL, BASE, WATER = 0, 1, 2, 4, 128
TANKS = ((8, 16), (32, 64))
DIRECTIONS = ((0, -1), (1, 0), (0, 1), (-1, 0))
SPAWNS = (((2, 0), (6, 0)), ((6, 8), (2, 8)))
BASES = ((4, 0), (4, 8))


def encode(cells, kind):
    result = [0, 0, 0]
    for y in range(9):
        for x in range(9):
            if cells[y][x] == kind:
                result[y // 3] |= 1 << ((y % 3) * 9 + x)
    return result


def generate_map(rng):
    cells = {(x, y) for x in range(9) for y in range(9)}
    for _ in range(1000):
        board = [[EMPTY] * 9 for _ in range(9)]
        for y in range(5):
            for x in range(9):
                board[y][x] = (
                    BRICK
                    if rng.randrange(3) > 1
                    else WATER
                    if rng.randrange(27) > 22
                    else STEEL
                    if rng.randrange(23) > 18
                    else EMPTY
                )
        for x, y in ((3, 1), (5, 1), (3, 0), (5, 0), (4, 1)):
            board[y][x] = BRICK
        for x in (2, 4, 6):
            board[0][x] = EMPTY
        for y in range(5):
            for x in range(9):
                board[8 - y][8 - x] = board[y][x]
        for y in range(2, 7):
            board[y][4] = BRICK
        for x in range(9):
            board[4][x] = BRICK
        for x in (2, 4, 6):
            board[4][x] = STEEL
        accessible = {
            point for point in cells if board[point[1]][point[0]] not in (WATER, STEEL)
        }
        if connected(accessible, BASES[0], DIRECTIONS):
            return {
                "brickfield": encode(board, BRICK),
                "waterfield": encode(board, WATER),
                "steelfield": encode(board, STEEL),
            }
    raise ValueError("Unable to generate a connected Tank map.")


class Tank:
    def __init__(self, initdata=None):
        data = initial_data(initdata)
        if data.get("seed") is None:
            data["seed"] = randbits(32)
        rng = random_source(data["seed"])
        limit = data.get("maxTurn", 100)
        if not integer(limit) or not 1 <= limit <= 100:
            raise ValueError("maxTurn must be an integer between 1 and 100.")
        if "brickfield" not in data:
            data.update(generate_map(rng))
        for key in ("brickfield", "waterfield", "steelfield"):
            value = data.get(key, [0, 0, 0])
            if (
                not isinstance(value, list)
                or len(value) != 3
                or any(not integer(mask) or not 0 <= mask < 1 << 27 for mask in value)
            ):
                raise ValueError("Terrain must contain three unsigned 27-bit integers.")
            data[key] = value.copy()
        data["maxTurn"] = limit
        self.initdata = data
        self.board = [[EMPTY] * 9 for _ in range(9)]
        for y in range(9):
            for x in range(9):
                bit = 1 << ((y % 3) * 9 + x)
                for key, kind in (
                    ("brickfield", BRICK),
                    ("waterfield", WATER),
                    ("steelfield", STEEL),
                ):
                    if data[key][y // 3] & bit:
                        self.board[y][x] = kind
                        break
        self.positions = [[point for point in side] for side in SPAWNS]
        self.base_alive = [True, True]
        self.previous = [[-1, -1], [-1, -1]]
        self.turn = 0
        self.winner = None
        for side in range(2):
            for tank, (x, y) in enumerate(SPAWNS[side]):
                self.board[y][x] = TANKS[side][tank]
            x, y = BASES[side]
            self.board[y][x] = BASE

    def initial(self):
        return deepcopy(
            {
                "command": "request",
                "initdata": self.initdata,
                "content": {
                    str(side): {
                        key: self.initdata[key]
                        for key in ("brickfield", "waterfield", "steelfield")
                    }
                    | {"mySide": side}
                    for side in range(2)
                },
                "display": {
                    "brick": self.initdata["brickfield"],
                    "water": self.initdata["waterfield"],
                    "steel": self.initdata["steelfield"],
                },
            }
        )

    def valid(self, side, tank, action):
        if not integer(action) or not -1 <= action <= 7:
            return False
        if action >= 4 and self.previous[side][tank] >= 4:
            return False
        if action == -1 or action >= 4:
            return True
        point = self.positions[side][tank]
        if point is None:
            return False
        dx, dy = DIRECTIONS[action]
        x, y = point[0] + dx, point[1] + dy
        return 0 <= x < 9 and 0 <= y < 9 and self.board[y][x] == EMPTY

    def legal_actions(self, side, tank):
        if self.positions[side][tank] is None:
            return [-1]
        return [action for action in range(-1, 8) if self.valid(side, tank, action)]

    def _move_and_fire(self, actions):
        # Validate all actions against the pre-move field, then move all tanks.
        # Several tanks may enter the same previously empty cell.
        for side in range(2):
            for tank in range(2):
                point = self.positions[side][tank]
                action = actions[side][tank]
                if point is not None and 0 <= action <= 3:
                    x, y = point
                    dx, dy = DIRECTIONS[action]
                    self.board[y][x] &= ~TANKS[side][tank]
                    self.positions[side][tank] = x + dx, y + dy
                    self.board[y + dy][x + dx] |= TANKS[side][tank]
        destroyed = set()
        for side in range(2):
            for tank in range(2):
                point = self.positions[side][tank]
                action = actions[side][tank]
                if point is None or action < 4:
                    continue
                x, y = point
                own = self.board[y][x]
                stacked = bool(own & (own - 1))
                dx, dy = DIRECTIONS[action % 4]
                while True:
                    x, y = x + dx, y + dy
                    if not (0 <= x < 9 and 0 <= y < 9):
                        break
                    item = self.board[y][x]
                    if item in (EMPTY, WATER):
                        continue
                    if item >= TANKS[0][0] and not stacked and not item & (item - 1):
                        target_side = 0 if item in TANKS[0] else 1
                        target_tank = 0 if item in (TANKS[0][0], TANKS[1][0]) else 1
                        other = actions[target_side][target_tank]
                        if other >= 4 and (action + 2) % 4 == other % 4:
                            break  # Single tanks facing each other cancel their shots.
                    for mask in (BRICK, STEEL, BASE, 8, 16, 32, 64):
                        if item & mask:
                            destroyed.add((x, y, mask))
                    break
        # Every shot sees the same field. Destruction is applied afterwards.
        for x, y, item in destroyed:
            if item == STEEL:
                continue
            if item == BASE:
                self.base_alive[0 if (x, y) == BASES[0] else 1] = False
            elif item >= 8:
                side = 0 if item in TANKS[0] else 1
                tank = 0 if item in (8, 32) else 1
                self.positions[side][tank] = None
            self.board[y][x] &= ~item
        self.previous = deepcopy(actions)
        self.turn += 1
        failed = [
            not self.base_alive[side] or not any(self.positions[side])
            for side in range(2)
        ]
        if any(failed):
            self.winner = -1 if all(failed) else int(failed[0])
        elif self.turn >= self.initdata["maxTurn"]:
            self.winner = -1

    def step(self, actions):
        if self.winner is not None:
            raise ValueError("The game has finished.")
        raw = records(actions)
        invalid = [False, False]
        selected = [[-1, -1], [-1, -1]]
        display, content = {}, {}
        reasons = [None, None]
        for side in range(2):
            answer = raw[side].get("response")
            if answer is None:
                answer = raw[side].get("content")
            if (
                isinstance(answer, list)
                and len(answer) >= 2
                and all(protocol_int(value) is not None for value in answer[:2])
            ):
                answer = [protocol_int(value) for value in answer[:2]]
                selected[side] = answer[:2]
                display[str(side)] = answer[:2]
                content[str(1 - side)] = [
                    value
                    if self.positions[side][tank] is not None
                    and self.valid(side, tank, value)
                    else -1
                    for tank, value in enumerate(answer[:2])
                ]
                invalid[side] = any(
                    self.positions[side][tank] is not None
                    and not self.valid(side, tank, value)
                    for tank, value in enumerate(answer[:2])
                )
            else:
                invalid[side] = True
            if invalid[side]:
                reasons[side] = "INVALID_INPUT_VERDICT_" + str(
                    raw[side].get("verdict", "")
                )
        if any(invalid):
            self.winner = -1 if all(invalid) else int(invalid[0])
        else:
            self._move_and_fire(selected)
            if self.winner is not None:
                for side in range(2):
                    tanks = any(self.positions[side])
                    base = self.base_alive[side]
                    reasons[side] = (
                        "BASE_TANK_ALL_DESTROYED"
                        if not tanks and not base
                        else "TANK_ALL_DESTROYED"
                        if not tanks
                        else "BASE_DESTROYED"
                        if not base
                        else None
                    )
        if any(reason is not None for reason in reasons):
            last = 1 if reasons[1] is not None else 0
            display["loseReason"] = reasons[: last + 1]
        if self.winner is not None:
            content = scores(self.winner)
        return {
            "command": "finish" if self.winner is not None else "request",
            "content": content,
            "display": display,
        }
