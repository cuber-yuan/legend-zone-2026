from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile

from .avatars import MAX_AVATAR_BYTES, Avatars
from .config import ROOT
from .security import require_user

router = APIRouter(prefix="/api")


@router.get("/avatars/{user_id}")
def avatar(user_id: int, request: Request):
    if not request.app.state.db.one("SELECT id FROM users WHERE id=?", (user_id,)):
        raise HTTPException(404, "User not found.")
    try:
        raw = Avatars(request.app.state.settings.data_dir).path(user_id).read_bytes()
    except FileNotFoundError:
        raw = (ROOT / "server/static/default-avatar.png").read_bytes()
    return Response(raw, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/account/avatar")
def upload_avatar(request: Request, file: UploadFile, user=Depends(require_user)):
    request.app.state.attempts.check(request)
    raw = file.file.read(MAX_AVATAR_BYTES + 1)
    if len(raw) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "Choose an image up to 4 MiB.")
    Avatars(request.app.state.settings.data_dir).save(user["id"], raw)
    return {
        "avatar_url": f"/api/avatars/{user['id']}",
        "message": "Avatar updated successfully.",
    }


@router.delete("/account/avatar")
def remove_avatar(request: Request, user=Depends(require_user)):
    Avatars(request.app.state.settings.data_dir).remove(user["id"])
    return {"avatar_url": None, "message": "Default avatar restored."}
