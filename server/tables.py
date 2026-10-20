"""Ephemeral homepage drafts; disconnect removes a table immediately."""

from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect

from .bots import selected_version
from .games import get_game
from .security import current_user

router = APIRouter(prefix="/api")


class Tables:
    def __init__(self):
        self.lock = Lock()
        self.values = {}

    def list(self):
        with self.lock:
            return list(self.values.values())

    def remove(self, key):
        with self.lock:
            self.values.pop(key, None)


@router.get("/tables")
def listing(request: Request):
    return request.app.state.tables.list()


@router.websocket("/tables/ws")
async def draft(socket: WebSocket):
    origin = socket.headers.get("origin")
    expected = (
        "https://" if socket.url.scheme == "wss" else "http://"
    ) + socket.url.netloc
    user = current_user(socket)
    if not user or origin != expected:
        await socket.close(code=1008)
        return
    await socket.accept()
    key = uuid4().hex
    tables = socket.app.state.tables
    try:
        while True:
            value = await socket.receive_json()
            if not isinstance(value, dict):
                continue
            try:
                game = get_game(value.get("game"))
                players = []
                for choice in value.get("players", [])[:2]:
                    if choice.get("type") == "human":
                        players.append({"type": "human", "name": user["username"]})
                    else:
                        bot = selected_version(
                            socket.app.state.db,
                            choice.get("bot_id"),
                            choice.get("version"),
                        )
                        if bot and bot["game"] == game.name:
                            latest = selected_version(socket.app.state.db, bot["id"])
                            players.append(
                                {
                                    "type": "bot",
                                    "name": bot["bot_name"],
                                    "bot_id": bot["id"],
                                    "version": bot["version_number"],
                                    "rating": latest["rating"],
                                }
                            )
                if len(players) != 2:
                    continue
                with tables.lock:
                    tables.values[key] = {
                        "id": key,
                        "owner": user["username"],
                        "user_id": user["id"],
                        "game": game.name,
                        "players": players,
                    }
            except (ValueError, TypeError, AttributeError):
                continue
    except (WebSocketDisconnect, ValueError):
        pass
    finally:
        tables.remove(key)
