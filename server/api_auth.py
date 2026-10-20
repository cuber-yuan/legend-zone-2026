import re
import time
from threading import Lock

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from werkzeug.security import check_password_hash, generate_password_hash

from .security import COOKIE, current_user, set_session

router = APIRouter(prefix="/api")


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=256)
    email: str | None = Field(default=None, max_length=254)


class Attempts:
    def __init__(self):
        self.lock = Lock()
        self.windows = {}

    def check(self, request):
        key = request.client.host if request.client else "local"
        now = time.monotonic()
        with self.lock:
            self.windows = {
                ip: [t for t in times if t > now - 60]
                for ip, times in self.windows.items()
                if times and times[-1] > now - 60
            }
            values = self.windows.setdefault(key, [])
            if len(values) >= 12:
                raise HTTPException(429, "Too many attempts. Please wait a minute.")
            values.append(now)


@router.get("/session")
def session(request: Request):
    return {"user": current_user(request)}


@router.post("/auth/{operation}")
def authenticate(
    operation: str, body: Credentials, request: Request, response: Response
):
    if operation not in ("login", "register"):
        raise HTTPException(404, "Not found.")
    request.app.state.attempts.check(request)
    db = request.app.state.db
    if operation == "register":
        if not re.fullmatch(r"[\w-]{3,32}", body.username) or len(body.password) < 8:
            raise HTTPException(
                400,
                "Use a 3–32 character username and a password of at least 8 characters.",
            )
        if body.email and "@" not in body.email:
            raise HTTPException(400, "Invalid email address.")
        hashed = generate_password_hash(body.password)
        with db.connect(write=True) as conn:
            cursor = conn.execute(
                "INSERT INTO users(username,password_hash,email) VALUES (?,?,?)",
                (body.username, hashed, body.email),
            )
            uid = cursor.lastrowid
    else:
        user = db.one(
            "SELECT id,password_hash FROM users WHERE username=?", (body.username,)
        )
        try:
            valid = bool(
                user and check_password_hash(user["password_hash"], body.password)
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise HTTPException(401, "Incorrect username or password.")
        uid = user["id"]
    set_session(response, request.app.state.settings, uid)
    return {
        "user": db.one(
            "SELECT id,username,role,membership FROM users WHERE id=?", (uid,)
        )
    }


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}
