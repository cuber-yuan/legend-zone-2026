from dataclasses import asdict, dataclass

from judges.board import Board
from judges.snake import Snake
from judges.tank import Tank


@dataclass(frozen=True)
class Game:
    slug: str
    name: str
    kind: str
    width: int
    height: int
    line: int = 0
    max_turns: int = 200
    max_humans: int = 2
    description: str = ""

    def public(self):
        return asdict(self)


GAMES = {
    g.slug: g
    for g in [
        Game(
            "gomoku",
            "Gomoku",
            "board",
            15,
            15,
            5,
            max_turns=225,
            description="Connect five stones in a row.",
        ),
        Game(
            "tictactoe",
            "Tic Tac Toe",
            "board",
            3,
            3,
            3,
            max_turns=9,
            description="Line up three marks before your opponent.",
        ),
        Game(
            "connect4",
            "Connect Four",
            "board",
            7,
            6,
            4,
            max_turns=42,
            description="Drop discs and connect four with gravity.",
        ),
        Game(
            "snake",
            "Snake",
            "snake",
            20,
            20,
            max_humans=1,
            description="Outlast your opponent in a growing snake duel.",
        ),
        Game(
            "msnake",
            "Mini Snake",
            "snake",
            11,
            10,
            max_humans=1,
            description="A compact snake duel on a fixed 10 × 11 map.",
        ),
        Game(
            "tank",
            "Tank Battle",
            "tank",
            9,
            9,
            max_turns=100,
            max_humans=2,
            description="Command two tanks and protect your base.",
        ),
    ]
}
BY_NAME = {g.name: g for g in GAMES.values()}


def get_game(value):
    game = GAMES.get(value) or BY_NAME.get(value)
    if not game:
        raise ValueError("Unknown game.")
    return game


def create_judge(value, initdata=None):
    game = get_game(value)
    if game.kind == "board":
        return Board(game)
    if game.kind == "snake":
        return Snake(initdata, mini=game.slug == "msnake")
    return Tank(initdata)
