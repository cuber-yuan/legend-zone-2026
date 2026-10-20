import logging
import shutil

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, StrictBool

from . import bots
from .security import can_read_source, current_user, require_user

router = APIRouter(prefix="/api/bots")
log = logging.getLogger(__name__)


@router.get("")
def listing(request: Request, game: str | None = None):
    db = request.app.state.db
    values = bots.list_bots(db, game)
    versions = {value["id"]: [] for value in values}
    if versions:
        for row in db.all(
            "SELECT bot_id,version_number FROM bot_versions WHERE bot_id IN ("
            + ",".join("?" for _ in versions)
            + ") ORDER BY version_number DESC",
            list(versions),
        ):
            versions[row["bot_id"]].append(row["version_number"])
    for value in values:
        value["versions"] = versions[value["id"]]
    return values


@router.get("/{bot_id}")
def detail(bot_id: str, request: Request):
    db = request.app.state.db
    bot = db.one(bots.LATEST + " AND b.id=?", (bot_id,))
    if not bot:
        raise HTTPException(404, "Bot not found.")
    bot["can_read_source"] = can_read_source(current_user(request), bot)
    bot["versions"] = db.all(
        "SELECT id,version_number,description,rating,created_at FROM bot_versions WHERE bot_id=? ORDER BY version_number DESC",
        (bot_id,),
    )
    bot["history"] = db.all(
        "SELECT id,version_id,match_id,rating,created_at FROM rating_history WHERE bot_id=? ORDER BY id",
        (bot_id,),
    )
    return bot


@router.get("/{bot_id}/source")
def source(bot_id: str, request: Request, version: int | None = None):
    db = request.app.state.db
    value = bots.selected_version(db, bot_id, version)
    if not value:
        raise HTTPException(404, "Bot version not found.")
    if not can_read_source(current_user(request), value):
        raise HTTPException(403, "This source is private.")
    try:
        text = bots.read_source(request.app.state.settings, value)
    except FileNotFoundError:
        row = db.one(
            "SELECT source_code FROM bot_versions WHERE id=?", (value["version_id"],)
        )
        if row["source_code"] is None:
            raise HTTPException(404, "Source file is unavailable.")
        text = row["source_code"]
    return {"source": text, "version": value["version_number"]}


@router.get("/{bot_id}/download")
def download(bot_id: str, request: Request, version: int | None = None):
    value = bots.selected_version(request.app.state.db, bot_id, version)
    if not value:
        raise HTTPException(404, "Bot version not found.")
    if not can_read_source(current_user(request), value):
        raise HTTPException(403, "This source is private.")
    try:
        raw, name, mime = bots.download(request.app.state.settings, value)
    except FileNotFoundError:
        raise HTTPException(404, "Bot package is unavailable.")
    return Response(
        raw,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
        },
    )


async def upload(request, user, bot_id=None):
    async with request.form(
        max_files=1, max_fields=12, max_part_size=request.app.state.settings.max_upload
    ) as form:
        file = form.get("file")
        filename = getattr(file, "filename", "") or ""
        raw = (
            await file.read(request.app.state.settings.max_upload + 1)
            if filename
            else None
        )
        return bots.save_version(
            request.app.state.db,
            request.app.state.settings,
            user,
            bot_id=bot_id,
            name=str(form.get("name", "")),
            game=str(form.get("game", "")),
            language=str(form.get("language", "")),
            description=str(form.get("description", "")),
            source=str(form.get("source", "")),
            filename=filename,
            raw=raw,
        )


@router.post("")
async def create(request: Request, user=Depends(require_user)):
    return {"id": await upload(request, user)}


@router.post("/{bot_id}/versions")
async def version(bot_id: str, request: Request, user=Depends(require_user)):
    bots.owned(request.app.state.db, bot_id, user)
    return {"id": await upload(request, user, bot_id)}


class Visibility(BaseModel):
    is_private: StrictBool


@router.post("/{bot_id}/visibility")
def visibility(
    bot_id: str, body: Visibility, request: Request, user=Depends(require_user)
):
    bots.owned(request.app.state.db, bot_id, user)
    with request.app.state.db.connect(write=True) as conn:
        conn.execute(
            "UPDATE bots SET is_private=? WHERE id=?", (int(body.is_private), bot_id)
        )
    return {"ok": True, "is_private": body.is_private}


class Deletion(BaseModel):
    confirm: str


@router.delete("/{bot_id}")
def delete(bot_id: str, body: Deletion, request: Request, user=Depends(require_user)):
    db = request.app.state.db
    bot = bots.owned(db, bot_id, user)
    if body.confirm != "DELETE":
        raise HTTPException(400, "Type DELETE to confirm.")
    with db.connect(write=True) as conn:
        if conn.execute(
            "SELECT 1 FROM match_players p JOIN matches m ON m.id=p.match_id WHERE p.bot_id=? AND m.status='playing' LIMIT 1",
            (bot_id,),
        ).fetchone():
            raise HTTPException(409, "A match using this bot is still active.")
        conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))
    base = request.app.state.settings.uploads.resolve()
    directory = base / str(bot["user_id"]) / bot_id
    if (
        directory.exists()
        and directory.resolve().is_relative_to(base)
        and directory.resolve() == directory.absolute()
        and not directory.is_symlink()
    ):
        try:
            shutil.rmtree(directory)
        except OSError:
            log.exception("Deleted bot package could not be removed: %s", bot_id)
    return {"ok": True}
