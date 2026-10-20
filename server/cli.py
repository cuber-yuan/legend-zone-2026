"""Explicit maintenance commands. Startup never initializes, migrates or imports."""

import argparse
import os
import secrets
import shutil
import sqlite3
import tempfile
from contextlib import closing
from getpass import getpass
from pathlib import Path

from werkzeug.security import generate_password_hash

from .config import ROOT
from .database import Database, initialize, install_chat_schema
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


def upgrade_chat(args):
    if not args.service_stopped:
        raise ValueError("Stop the service, then pass --service-stopped.")
    directory = data_path(args.data)
    db = Database(directory / "legend_zone.db")
    if not db.path.is_file():
        raise ValueError(
            "Database not found. This command never initializes a database."
        )
    backup = args.backup.resolve()
    if backup.is_relative_to(directory):
        raise ValueError("Choose a database backup file outside the data directory.")
    from .main import ProcessLock

    lock = ProcessLock(directory / "server.lock")
    lock.acquire()
    try:
        obsolete = [directory / "chat.json", *directory.glob(".chat-*.tmp")]
        for path in obsolete:
            if (
                path.is_symlink()
                or path.resolve().parent != directory
                or path.exists()
                and not path.is_file()
            ):
                raise ValueError(
                    "Refusing to remove a linked or invalid legacy chat path."
                )
        backup.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents replacing an existing backup. Do not back up old chat files.
        with backup.open("xb"):
            pass
        with db.connect() as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        with db.connect(write=True) as conn:
            install_chat_schema(conn)
            db.validate(conn)
        removed = 0
        for path in obsolete:
            if path.exists():
                path.unlink()
                removed += 1
        print(f"Chat schema ready. Database backup: {backup}")
        print(f"Deleted {removed} legacy chat files without importing their records.")
    finally:
        lock.release()


def copy_tree(source, destination):
    if not source.exists():
        return
    for path in source.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Import refuses links in upload directories.")
    shutil.copytree(source, destination, dirs_exist_ok=True)


def import_legacy(args):
    if not args.source_stopped:
        raise ValueError("Stop writes to the old project, then pass --source-stopped.")
    source = args.source.resolve()
    destination = data_path(args.data)
    if destination.exists():
        raise ValueError(
            "Import destination must not exist. Choose a new --data directory."
        )
    if destination.is_relative_to(source):
        raise ValueError("Import destination must be outside the old project.")
    source_db = source / "legend_zone.db"
    if not source_db.is_file():
        raise ValueError("Source database not found.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".legend-import-", dir=destination.parent))
    try:
        # Copy only after the source service has stopped; never open its database.
        source_copy = stage / "source-copy"
        source_copy.mkdir()
        for suffix in ("", "-wal", "-shm"):
            source_file = Path(str(source_db) + suffix)
            if source_file.exists():
                shutil.copy2(source_file, source_copy / ("legend_zone.db" + suffix))
        with (
            closing(sqlite3.connect(source_copy / "legend_zone.db")) as original,
            closing(sqlite3.connect(stage / "legend_zone.db")) as copied,
        ):
            original.backup(copied)
        if source_copy.resolve().parent != stage.resolve():
            raise ValueError("Invalid temporary database path.")
        shutil.rmtree(source_copy)
        db = Database(stage / "legend_zone.db")
        with db.connect(write=True) as conn:
            install_chat_schema(conn)
            db.validate(conn)
        copy_tree(source / "uploads/bots", stage / "bots")
        with db.connect(write=True) as conn:
            rows = conn.execute(
                "SELECT v.id,v.version_number,v.file_path,v.source_code,b.id AS bot_id,b.user_id,b.language FROM bot_versions v JOIN bots b ON b.id=v.bot_id"
            ).fetchall()
            for row in rows:
                raw = (row["file_path"] or "").replace("\\", "/")
                marker = "uploads/bots/"
                suffix = raw.split(marker, 1)[1] if marker in raw else None
                target = stage / "bots" / suffix if suffix else None
                expected = stage / "bots" / str(row["user_id"]) / row["bot_id"]
                if target is not None and (
                    not target.resolve().is_relative_to(expected.resolve())
                    or not target.resolve().is_relative_to(stage / "bots")
                ):
                    raise ValueError(
                        "A stored upload path is outside its bot directory."
                    )
                if target is None or not target.exists():
                    if row["source_code"] is None:
                        raise ValueError(
                            f"Missing package for version ID {row['id']}; import stopped."
                        )
                    target = expected / f"import-v{row['version_number']}"
                    target.mkdir(parents=True, exist_ok=True)
                    (
                        target
                        / ("main.py" if row["language"] == "python3" else "main.cpp")
                    ).write_text(row["source_code"], encoding="utf-8")
                conn.execute(
                    "UPDATE bot_versions SET file_path=? WHERE id=?",
                    (target.relative_to(stage).as_posix(), row["id"]),
                )
            # Mark interrupted work explicitly in the imported copy. Do not replay or rate it.
            conn.execute(
                "UPDATE matches SET status='finished',winner=-1,finished_at=?,termination_reason='server_error',rating_status='skipped' WHERE status='playing'",
                (now(),),
            )
            conn.execute(
                "UPDATE match_debug_sessions SET status='interrupted',incomplete=1,finished_at=? WHERE status='recording'",
                (now(),),
            )
            from .games import GAMES

            for game in GAMES.values():
                conn.execute(
                    "INSERT OR IGNORE INTO games(name,description,min_players,max_players) VALUES (?,?,2,2)",
                    (game.name, game.description),
                )
            if conn.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError(
                    "Imported database has invalid foreign key references."
                )
        # These are optional runtime headers for existing user C++ bots, not judges.
        if args.bot_headers:
            copy_tree(source / "judges/jsoncpp", stage / "bot-include/jsoncpp")
            if (source / "judges/jsoncpp.cpp").exists():
                (stage / "bot-include").mkdir(exist_ok=True)
                shutil.copy2(
                    source / "judges/jsoncpp.cpp", stage / "bot-include/jsoncpp.cpp"
                )
        make_secret(stage)
        stage.rename(destination)
        print(
            f"Imported {len(rows)} bot versions into the new data directory. Source data was not modified."
        )
    finally:
        if stage.exists():
            shutil.rmtree(stage)


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
    command = commands.add_parser("upgrade-chat")
    command.add_argument("--data")
    command.add_argument("--backup", type=Path, required=True)
    command.add_argument("--service-stopped", action="store_true")
    command.set_defaults(run=upgrade_chat)
    command = commands.add_parser("import-legacy")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--data")
    command.add_argument("--source-stopped", action="store_true")
    command.add_argument("--bot-headers", action="store_true")
    command.set_defaults(run=import_legacy)
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
