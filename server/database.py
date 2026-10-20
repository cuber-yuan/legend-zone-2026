import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from .config import ROOT


class Database:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self, write=False):
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            if write:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self, sql, params=()):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(sql, params)]

    def one(self, sql, params=()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def validate(self):
        with closing(sqlite3.connect(":memory:")) as expected:
            expected.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
            tables = [
                row[0]
                for row in expected.execute(
                    "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            with self.connect() as actual:
                for table in tables:
                    required = {
                        row[1]
                        for row in expected.execute(f'PRAGMA table_info("{table}")')
                    }
                    present = {
                        row[1]
                        for row in actual.execute(f'PRAGMA table_info("{table}")')
                    }
                    if not required <= present:
                        raise RuntimeError(f"Database schema is incompatible: {table}")


def initialize(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        if conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone():
            raise RuntimeError("Refusing to initialize a non-empty database.")
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.execute("PRAGMA journal_mode=WAL")
        from .games import GAMES

        for game in GAMES.values():
            conn.execute(
                "INSERT INTO games(name,description,min_players,max_players) VALUES (?,?,2,2)",
                (game.name, game.description),
            )
        conn.commit()
