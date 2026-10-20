"""Shared Gomoku, Tic Tac Toe and Connect Four rules. Zero-based board[y][x]."""


class Board:
    def __init__(self, game):
        self.game = game
        self.board = [[0] * game.width for _ in range(game.height)]
        self.history = []
        self.side = 1
        self.winner = None

    def apply(self, action):
        if self.winner is not None:
            raise ValueError("The game has finished.")
        if not isinstance(action, dict):
            raise ValueError("Action must be an object.")
        x, y = action.get("x"), action.get("y")
        if type(x) is not int or not 0 <= x < self.game.width:
            raise ValueError("Invalid column.")
        if self.game.slug == "connect4":
            y = next(
                (
                    row
                    for row in range(self.game.height - 1, -1, -1)
                    if not self.board[row][x]
                ),
                None,
            )
        if type(y) is not int or not 0 <= y < self.game.height or self.board[y][x]:
            raise ValueError("Invalid move.")
        side = self.side
        self.board[y][x] = side
        self.history.append({"x": x, "y": y, "player": side})
        self.side = 3 - side
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            count = 1
            for sign in (-1, 1):
                nx, ny = x + dx * sign, y + dy * sign
                while (
                    0 <= nx < self.game.width
                    and 0 <= ny < self.game.height
                    and self.board[ny][nx] == side
                ):
                    count += 1
                    nx, ny = nx + dx * sign, ny + dy * sign
            if count >= self.game.line:
                self.winner = side - 1
                break
        if (
            self.winner is None
            and len(self.history) == self.game.width * self.game.height
        ):
            self.winner = -1
        return self.winner
