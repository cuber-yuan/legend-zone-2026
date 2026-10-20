"""Bot metadata, immutable version packages and authorized source retrieval."""

import shutil
import stat
import uuid
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from fastapi import HTTPException
from werkzeug.utils import secure_filename

from .games import get_game

ENTRIES = {"python3": ("__main__.py", "main.py"), "cpp": ("main.cpp", "main.cc")}
LATEST = """SELECT b.id,b.user_id,b.bot_name,b.game,b.language,b.is_private,b.created_at,
 u.username AS owner,v.id AS version_id,v.version_number,v.description,COALESCE(v.rating,1500) AS rating
 FROM bots b JOIN users u ON u.id=b.user_id JOIN bot_versions v ON v.bot_id=b.id
 WHERE v.version_number=(SELECT MAX(version_number) FROM bot_versions WHERE bot_id=b.id)"""


def list_bots(db, game=None, owner=None):
    sql, args = LATEST, []
    if game:
        sql += " AND b.game=?"
        args.append(get_game(game).name)
    if owner is not None:
        sql += " AND b.user_id=?"
        args.append(owner)
    return db.all(sql + " ORDER BY rating DESC,b.bot_name", args)


def selected_version(db, bot_id, version=None):
    return db.one(
        "SELECT b.*,v.id AS version_id,v.version_number,v.file_path,COALESCE(v.rating,1500) AS rating "
        "FROM bots b JOIN bot_versions v ON v.bot_id=b.id WHERE b.id=? "
        "AND (? IS NULL OR v.version_number=?) ORDER BY v.version_number DESC LIMIT 1",
        (bot_id, version, version),
    )


def owned(db, bot_id, user):
    bot = db.one("SELECT * FROM bots WHERE id=?", (bot_id,))
    if not bot:
        raise HTTPException(404, "Bot not found.")
    if bot["user_id"] != user["id"]:
        raise HTTPException(403, "Only the owner can change this bot.")
    return bot


def package_path(settings, version):
    base = settings.uploads.resolve()
    path = Path(version["file_path"] or "")
    if not path.is_absolute():
        path = settings.data_dir / path
    resolved = path.resolve()
    expected = base / str(version["user_id"]) / str(version["id"])
    if (
        not resolved.is_relative_to(expected)
        or not resolved.is_relative_to(base)
        or not resolved.exists()
    ):
        raise FileNotFoundError("Bot package is unavailable.")
    if any(
        parent.is_symlink() or (hasattr(parent, "is_junction") and parent.is_junction())
        for parent in (path, *path.parents)
        if parent.is_relative_to(base)
    ):
        raise FileNotFoundError("Bot package is unavailable.")
    return resolved


def entry_file(directory, language):
    if directory.is_file():
        if directory.suffix not in (
            (".py",) if language == "python3" else (".cpp", ".cc")
        ):
            raise ValueError("Unsupported entry file.")
        return directory
    for name in ENTRIES[language]:
        path = directory / name
        if path.is_file() and not path.is_symlink():
            return path
    raise ValueError(
        "The package must contain a root entry file: " + " or ".join(ENTRIES[language])
    )


def store_package(directory, language, source, filename, raw, limit):
    directory.mkdir(parents=True)
    if raw is not None and filename.lower().endswith(".zip"):
        work = directory / "src"
        work.mkdir()
        try:
            with ZipFile(BytesIO(raw)) as archive:
                members = archive.infolist()
                if (
                    len(members) > 2000
                    or sum(m.file_size for m in members) > 64 * 1024 * 1024
                ):
                    raise ValueError(
                        "ZIP exceeds the expanded size or file count limit."
                    )
                seen = set()
                for member in members:
                    name = member.filename.replace("\\", "/")
                    parts = PurePosixPath(name)
                    mode = member.external_attr >> 16
                    if (
                        parts.is_absolute()
                        or not parts.parts
                        or any(
                            part in ("..", ".")
                            or ":" in part
                            or part.endswith((" ", "."))
                            or PureWindowsPath(part).is_reserved()
                            for part in parts.parts
                        )
                        or stat.S_ISLNK(mode)
                        or name.lower() in seen
                        or member.flag_bits & 1
                    ):
                        raise ValueError("Unsafe or duplicate ZIP entry.")
                    seen.add(name.lower())
                    target = work.joinpath(*parts.parts)
                    if not target.resolve().is_relative_to(work.resolve()):
                        raise ValueError("Unsafe ZIP entry.")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(member) as src, target.open("xb") as dst:
                            shutil.copyfileobj(src, dst)
        except (
            BadZipFile,
            FileExistsError,
            NotADirectoryError,
            IsADirectoryError,
        ) as exc:
            raise ValueError("Invalid ZIP file.") from exc
    else:
        work = directory
        extension = ".py" if language == "python3" else ".cpp"
        if raw is not None and Path(filename).suffix.lower() not in (
            (".py",) if language == "python3" else (".cpp", ".cc")
        ):
            raise ValueError("The file extension does not match the bot language.")
        content = raw if raw is not None else source.encode("utf-8")
        if not content or len(content) > limit:
            raise ValueError("Source must be between 1 byte and 16 MiB.")
        content.decode(
            "utf-8-sig"
        )  # Reject binary uploads; never execute validation code.
        (directory / ("main" + extension)).write_bytes(content)
    entry_file(work, language)
    return work


def save_version(
    db,
    settings,
    user,
    *,
    bot_id=None,
    name="",
    game="",
    language="",
    description="",
    source="",
    filename="",
    raw=None,
):
    if len(description.strip()) < 4 or len(description) > 4000:
        raise ValueError("Description must contain 4–4000 characters.")
    if raw is None and not source.strip():
        raise ValueError("Upload a file or enter source code.")
    if raw is not None and len(raw) > settings.max_upload:
        raise ValueError("File exceeds 16 MiB.")
    is_new = bot_id is None
    if bot_id:
        bot = owned(db, bot_id, user)
        language = bot["language"]
    else:
        if not 4 <= len(name.strip()) <= 80:
            raise ValueError("Bot name must contain 4–80 characters.")
        if language not in ENTRIES:
            raise ValueError("Unsupported language.")
        game = get_game(game).name
        bot_id = uuid.uuid4().hex
    folder = (
        settings.uploads / str(user["id"]) / bot_id / ("version-" + uuid.uuid4().hex)
    )
    try:
        work = store_package(
            folder, language, source, filename, raw, settings.max_upload
        )
        with db.connect(write=True) as conn:
            if is_new:
                conn.execute(
                    "INSERT INTO bots(id,user_id,bot_name,game,language,is_private) VALUES (?,?,?,?,?,1)",
                    (bot_id, user["id"], name.strip(), game, language),
                )
            previous = conn.execute(
                "SELECT version_number,rating FROM bot_versions WHERE bot_id=? ORDER BY version_number DESC LIMIT 1",
                (bot_id,),
            ).fetchone()
            number, rating = (
                (previous["version_number"] + 1, previous["rating"])
                if previous
                else (1, 1500)
            )
            cursor = conn.execute(
                "INSERT INTO bot_versions(bot_id,version_number,description,file_path,rating) VALUES (?,?,?,?,?)",
                (
                    bot_id,
                    number,
                    description.strip(),
                    work.relative_to(settings.data_dir).as_posix(),
                    rating,
                ),
            )
            conn.execute(
                "INSERT INTO rating_history(bot_id,version_id,rating) VALUES (?,?,?)",
                (bot_id, cursor.lastrowid, rating),
            )
        return bot_id
    except Exception:
        if folder.exists():
            shutil.rmtree(folder)
        raise


def read_source(settings, version):
    path = entry_file(package_path(settings, version), version["language"])
    if path.stat().st_size > settings.max_upload:
        raise ValueError("Source exceeds the display limit.")
    return path.read_text(encoding="utf-8-sig")


def download(settings, version):
    path = package_path(settings, version)
    label = (
        f"{secure_filename(version['bot_name']) or 'bot'}-v{version['version_number']}"
    )
    if path.is_file() or path.name != "src":
        entry = entry_file(path, version["language"])
        return entry.read_bytes(), label + entry.suffix, "text/plain"
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for file in sorted(path.rglob("*")):
            if (
                not file.is_file()
                or file.is_symlink()
                or "__pycache__" in file.parts
                or file.suffix in (".pyc", ".pyo")
            ):
                continue
            if not file.resolve().is_relative_to(path):
                raise ValueError("Package contains an unsafe link.")
            archive.write(file, file.relative_to(path).as_posix())
    return output.getvalue(), label + ".zip", "application/zip"
