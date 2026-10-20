"""Routine maintenance commands. Startup only validates the database."""

import argparse
import os
import secrets
import sqlite3
from getpass import getpass
from pathlib import Path

from werkzeug.security import generate_password_hash

from .config import ROOT
from .database import Database, initialize
from .util import now


def data_path(value):
    return Path(value or os.environ.get("LEGEND_DATA_DIR", ROOT / "data")).resolve()


def make_secret(directory):
    path = directory / "secret.key"
    if not path.exists():
        with path.open("x", encoding="utf-8") as file:
            file.write(secrets.token_urlsafe(48))
        if os.name != "nt":
            path.chmod(0o600)


def init(args):
    directory = data_path(args.data)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "legend_zone.db"
    if path.exists():
        raise ValueError(
            "Database already exists. Initialization will not overwrite it."
        )
    if args.admin:
        password = getpass("Administrator password (8+ characters): ")
        if len(password) < 8 or getpass("Repeat password: ") != password:
            raise ValueError("Passwords must match and contain at least 8 characters.")
    initialize(path)
    if args.admin:
        with Database(path).connect(write=True) as conn:
            conn.execute(
                "INSERT INTO users(username,password_hash,role) VALUES (?,?,'admin')",
                (args.admin, generate_password_hash(password)),
            )
    make_secret(directory)
    print("Initialized a new database. Existing project data was not touched.")


def access(args):
    db = Database(data_path(args.data) / "legend_zone.db")
    db.validate()
    fields = []
    values = []
    if args.role:
        fields.append("role=?")
        values.append(args.role)
    if args.membership:
        fields.append("membership=?")
        values.append(args.membership)
    if not fields:
        raise ValueError("Specify --role or --membership.")
    with db.connect(write=True) as conn:
        result = conn.execute(
            "UPDATE users SET " + ",".join(fields) + " WHERE username=?",
            [*values, args.username],
        )
        if result.rowcount != 1:
            raise ValueError("User not found.")
    print("User access updated. Changes apply on the next request.")


def recover(args):
    db = Database(data_path(args.data) / "legend_zone.db")
    db.validate()
    from .main import ProcessLock

    lock = ProcessLock(data_path(args.data) / "server.lock")
    lock.acquire()
    try:
        with db.connect(write=True) as conn:
            ids = [
                row[0]
                for row in conn.execute("SELECT id FROM matches WHERE status='playing'")
            ]
            for match_id in ids:
                conn.execute(
                    "UPDATE matches SET status='finished',winner=-1,finished_at=?,termination_reason='server_error',rating_status='skipped',error_message='Interrupted by a previous server shutdown.' WHERE id=?",
                    (now(), match_id),
                )
                conn.execute(
                    "UPDATE match_debug_sessions SET status='interrupted',incomplete=1,finished_at=? WHERE match_id=?",
                    (now(), match_id),
                )
        print(
            f"Marked {len(ids)} interrupted matches as finished without rating changes."
        )
    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description="Legend Zone maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("init")
    command.add_argument("--admin")
    command.add_argument("--data")
    command.set_defaults(run=init)
    command = commands.add_parser("access")
    command.add_argument("username")
    command.add_argument("--role", choices=("user", "admin"))
    command.add_argument("--membership", choices=("standard", "vip"))
    command.add_argument("--data")
    command.set_defaults(run=access)
    command = commands.add_parser("recover")
    command.add_argument("--data")
    command.set_defaults(run=recover)
    command = commands.add_parser("serve")
    command.add_argument("--host", default="127.0.0.1")
    command.add_argument("--port", type=int, default=8000)
    command.add_argument("--data")

    def serve(args):
        if args.data:
            os.environ["LEGEND_DATA_DIR"] = str(data_path(args.data))
        import uvicorn

        uvicorn.run(
            "server.main:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            workers=1,
            timeout_graceful_shutdown=90,
        )

    command.set_defaults(run=serve)
    args = parser.parse_args()
    try:
        args.run(args)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
