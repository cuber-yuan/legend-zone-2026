import re
import sqlite3
from contextlib import closing

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .bots import list_bots
from .security import require_admin, require_user

router = APIRouter(prefix="/api")


@router.get("/rankings")
def rankings(request: Request, game: str | None = None):
    return list_bots(request.app.state.db, game)


@router.get("/users/{username}")
def profile(username: str, request: Request):
    db = request.app.state.db
    user = db.one(
        "SELECT id,username,created_at FROM users WHERE username=?", (username,)
    )
    if not user:
        raise HTTPException(404, "User not found.")
    return user | {"bots": list_bots(db, owner=user["id"])}


@router.get("/chat")
def chat(request: Request):
    try:
        return request.app.state.chat.messages()
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "Chat history is temporarily unavailable.")


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/chat")
def send(body: Message, request: Request, user=Depends(require_user)):
    text = body.text.strip()
    if not text:
        raise HTTPException(400, "Write a message first.")
    try:
        return request.app.state.chat.send(user["username"], text)
    except (OSError, ValueError, KeyError):
        raise HTTPException(503, "Unable to save the message. Please retry.")


def admin_connection(request):
    path = request.app.state.settings.database.as_uri() + "?mode=ro"
    conn = sqlite3.connect(path, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


@router.get("/admin/tables")
def tables(request: Request, user=Depends(require_admin)):
    with closing(admin_connection(request)) as conn:
        try:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT name,type FROM sqlite_schema WHERE type='table' ORDER BY name"
                )
            ]
        finally:
            conn.close()


@router.get("/admin/table")
def table(
    request: Request,
    name: str,
    page: int = Query(1, ge=1),
    size: int = Query(25, ge=1, le=100),
    user=Depends(require_admin),
):
    with closing(admin_connection(request)) as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?", (name,)
        ).fetchone():
            raise HTTPException(404, "Table not found.")
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [dict(row) for row in conn.execute(f"PRAGMA table_info({quoted})")]
        expressions = []
        for column in columns:
            key = column["name"]
            field = '"' + key.replace('"', '""') + '"'
            private = bool(
                re.search(r"password|secret|token|source_code|api_key", key, re.I)
            )
            column["hidden"] = private
            if private:
                expressions.append(f"NULL AS {field}")
            else:
                expressions.append(
                    f"CASE WHEN typeof({field})='blob' THEN '[binary]' ELSE substr({field},1,1001) END AS {field}"
                )
        order = (
            ",".join(
                '"' + c["name"].replace('"', '""') + '"'
                for c in sorted(columns, key=lambda c: c["pk"])
                if c["pk"]
            )
            or "rowid"
        )
        count = conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT {','.join(expressions)} FROM {quoted} ORDER BY {order} LIMIT ? OFFSET ?",
                (size, (page - 1) * size),
            )
        ]
        return {
            "columns": columns,
            "rows": rows,
            "total": count,
            "page": page,
            "size": size,
        }
