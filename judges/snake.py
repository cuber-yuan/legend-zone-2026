"""Snake rules. Coordinates are one-based: x is row, y is column."""

from collections import deque
from copy import deepcopy

from .common import (
    connected,
    initial_data,
    integer,
    protocol_int,
    random_source,
    records,
    scores,
)

DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


class Snake:
    def __init__(self, initdata=None, *, mini=False):
        data = initial_data(initdata)
        rng = random_source(data.get("seed"))
        if mini:
            height, width = 10, 11
        elif "height" in data and "width" in data:
            height, width = data["height"], data["width"]
        else:
            height, width = rng.randint(10, 13), rng.randint(11, 17)
            while (height + width) % 2 == 0:
                height, width = rng.randint(10, 13), rng.randint(11, 17)
            height, width = data.get("height", height), data.get("width", width)
        if any(not integer(size) or not 2 <= size <= 24 for size in (height, width)):
            raise ValueError("Snake dimensions must be integers between 2 and 24.")
        self.height, self.width = height, width
        self.bodies = [deque([(1, 1)]), deque([(height, width)])]
        self.turn = 0
        self.winner = None
        if data.get("obstacle") is None:
            obstacles = self._generate_obstacles(rng)
        else:
            obstacles = data["obstacle"]
        if not isinstance(obstacles, list):
            raise ValueError("obstacle must be an array.")
        self.obstacles = set()
        for item in obstacles:
            if not isinstance(item, dict):
                raise ValueError("Invalid obstacle.")
            x, y = item.get("x"), item.get("y")
            if (
                not integer(x)
                or not integer(y)
                or not 1 <= x <= height
                or not 1 <= y <= width
            ):
                raise ValueError("Obstacle outside the board.")
            self.obstacles.add((x, y))
        if (1, 1) in self.obstacles or (height, width) in self.obstacles:
            raise ValueError("An obstacle cannot cover a spawn point.")
        self.initdata = {
            "width": width,
            "height": height,
            "obstacle": deepcopy(obstacles),
            "0": {"x": 1, "y": 1},
            "1": {"x": height, "y": width},
        }

    def _generate_obstacles(self, rng):
        height, width = self.height, self.width
        cells = {(x, y) for x in range(1, height + 1) for y in range(1, width + 1)}
        candidates = sorted(cells - {(1, 1), (height, width)})
        target_pairs = height * width // 10 // 2
        for _ in range(1000):
            blocked = set()
            output = []
            for _ in range(target_pairs):
                options = [point for point in candidates if point not in blocked]
                x, y = rng.choice(options)
                for point in ((x, y), (height + 1 - x, width + 1 - y)):
                    if point not in blocked:
                        blocked.add(point)
                        output.append({"x": point[0], "y": point[1]})
            if connected(cells - blocked, (1, 1), DIRECTIONS):
                return output
        raise ValueError("Unable to generate a connected Snake map.")

    def initial(self):
        content = {}
        for side, point in enumerate(((1, 1), (self.height, self.width))):
            content[str(side)] = {
                "x": point[0],
                "y": point[1],
                "height": self.height,
                "width": self.width,
                "obstacle": self.initdata["obstacle"],
            }
        return deepcopy(
            {
                "command": "request",
                "initdata": self.initdata,
                "content": content,
                "display": self.initdata,
            }
        )

    def step(self, actions):
        if self.winner is not None:
            raise ValueError("The game has finished.")
        raw = records(actions)
        grow = self.turn <= 24 or (self.turn - 24) % 3 == 0
        display = {"grow": "true" if grow else "false"}
        content = {}
        lost, invalid = [False, False], [False, False]
        # Tails leave before either collision check. The original judge resolves
        # side 0 then side 1 and explicitly handles their heads meeting.
        if not grow:
            for body in self.bodies:
                body.pop()
        for side in range(2):
            answer = raw[side].get("response")
            direction = (
                protocol_int(answer.get("direction"))
                if isinstance(answer, dict)
                else None
            )
            if direction is None:
                lost[side] = invalid[side] = True
                continue
            display[str(side)] = direction
            if not 0 <= direction < 4:
                lost[side] = True
                continue
            dx, dy = DIRECTIONS[direction]
            x, y = self.bodies[side][0]
            target = x + dx, y + dy
            if side == 1 and target == self.bodies[0][0]:
                lost = [True, True]
                continue
            occupied = any(target in body for body in self.bodies)
            if (
                not (1 <= target[0] <= self.height and 1 <= target[1] <= self.width)
                or target in self.obstacles
                or occupied
            ):
                lost[side] = True
                continue
            self.bodies[side].appendleft(target)
            if not any(lost):
                content[str(1 - side)] = {"direction": direction}
        self.turn += 1
        if any(lost):
            self.winner = -1 if all(lost) else int(lost[0])
            content = scores(self.winner)
            if self.winner == -1:
                display["err"] = "BothSnakeDie"
            else:
                loser = 1 - self.winner
                display["err"] = (
                    "INVALID_INPUT_VERDICT_" + str(raw[loser].get("verdict", ""))
                    if invalid[loser]
                    else "INVALIDMOVE"
                )
                display["winner"] = str(self.winner)
        return {
            "command": "finish" if self.winner is not None else "request",
            "initdata": {
                key: deepcopy(self.initdata[key])
                for key in ("width", "height", "obstacle")
            },
            "content": content,
            "display": display,
        }
