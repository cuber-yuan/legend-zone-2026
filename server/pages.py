"""Server-rendered views preserving the platform's existing UI."""

import json
from collections import defaultdict
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import api_auth, api_bots, api_community, bots
from .config import ROOT
from .avatars import Avatars
from .game_state import replay_frames
from .games import GAMES, get_game
from .matches import list_matches
from .security import can_read_source, current_user, require_admin, require_user
from .util import parse_json

router = APIRouter()
environment = Environment(
    loader=FileSystemLoader(ROOT / "server/templates"), autoescape=select_autoescape()
)
PATHS = {
    "main.home": "/",
    "main.games": "/games",
    "main.rating": "/rating",
    "main.chat": "/chat",
    "main.chat_messages": "/chat/messages",
    "main.profile": "/profile/{username}",
    "main.profile_root": "/profile",
    "main.bot_detail": "/bot/{bot_id}",
    "main.match_view": "/match/{match_id}",
    "main.matches": "/matches",
    "main.match_debug": "/api/matches/{match_id}/debug",
    "auth.login": "/login",
    "auth.register": "/register",
    "auth.logout": "#logout",
    "upload.new_version_page": "/bots/{bot_id}/new-version",
    "upload.add_version": "/bots/{bot_id}/versions",
    "upload.upload_bot": "/upload-bot",
    "upload.download_bot": "/api/bots/{bot_id}/download",
    "upload.set_visibility": "/api/bots/{bot_id}/visibility",
    "admin.test_page": "/admin",
    "admin.database_tables": "/admin/database/tables",
    "admin.database_table": "/admin/database/table",
}


def url_for(name, **values):
    if name == "static":
        return "/static/" + quote(values["filename"], safe="/")
    if name.startswith("main.") and name[5:] in (
        "gomoku",
        "tictactoe",
        "connect4",
        "snake",
        "msnake",
        "tank",
        "yahtzee",
        "catking",
        "injoker",
    ):
        return "/" + name[5:]
    return PATHS[name].format(
        **{key: quote(str(value), safe="") for key, value in values.items()}
    )


class Viewer(SimpleNamespace):
    def get_id(self):
        return str(self.id) if self.is_authenticated else None


def render(request, template, endpoint="main.home", **context):
    user = current_user(request)
    viewer = Viewer(
        **(user or {"id": None, "username": ""}),
        is_authenticated=bool(user),
        is_admin=bool(user and user["role"] == "admin"),
        public=user,
        avatar_url=Avatars(request.app.state.settings.data_dir).url(user["id"])
        if user
        else None,
    )
    context.update(
        current_user=viewer,
        url_for=url_for,
        request=SimpleNamespace(
            endpoint=endpoint, blueprint=endpoint.split(".")[0], path=request.url.path
        ),
    )
    return HTMLResponse(
        environment.get_template(template).render(**context),
        headers={"Cache-Control": "no-store"},
    )


def flat_match(match):
    result = match.copy()
    for seat, player in enumerate(match["players"], 1):
        key = f"player_{seat}"
        result.update(
            {
                key: player["name"],
                key + "_id": player.get("bot_id"),
                key + "_version": player.get("version"),
                key + "_is_human": player.get("type") == "human",
                key + "_rating": player.get("rating"),
            }
        )
    return result


@router.get("/")
def home(request: Request):
    return render(request, "index.html")


@router.get("/games")
def games(request: Request):
    return render(request, "games.html", "main.games")


@router.get("/matches")
def matches_page(request: Request):
    return render(request, "matches.html", "main.matches", games=GAMES.values())


@router.get("/rating")
def ratings(request: Request):
    values = defaultdict(list)
    for bot in bots.list_bots(request.app.state.db):
        values[bot["game"]].append(
            bot | {"name": bot["bot_name"], "version": bot["version_number"]}
        )
    return render(
        request, "rating.html", "main.rating", ratings=dict(sorted(values.items()))
    )


@router.get("/profile")
@router.get("/upload")
def own_profile(request: Request):
    user = current_user(request)
    return RedirectResponse(
        "/profile/" + quote(user["username"], safe="") if user else "/login",
        status_code=303,
    )


@router.get("/profile/{username}")
def profile(username: str, request: Request):
    db = request.app.state.db
    person = db.one(
        "SELECT id,username,created_at FROM users WHERE username=?", (username,)
    )
    if not person:
        raise HTTPException(404, "User not found.")
    user = current_user(request)
    values = []
    for bot in bots.list_bots(db, owner=person["id"]):
        count = db.one(
            "SELECT COUNT(*) AS n FROM bot_versions WHERE bot_id=?", (bot["id"],)
        )["n"]
        values.append(
            bot
            | {
                "name": bot["bot_name"],
                "latest_version": bot["version_number"],
                "latest_rating": bot["rating"],
                "latest_description": bot["description"],
                "versions": count,
            }
        )
    return render(
        request,
        "profile.html",
        "main.profile",
        bots=values,
        user_not_found=False,
        username=username,
        registered_at=person["created_at"],
        avatar_url=Avatars(request.app.state.settings.data_dir).url(person["id"]),
        is_owner=bool(user and user["id"] == person["id"]),
    )


@router.get("/bot/{bot_id}")
def bot_page(bot_id: str, request: Request):
    db = request.app.state.db
    bot = db.one(bots.LATEST + " AND b.id=?", (bot_id,))
    if not bot:
        raise HTTPException(404, "Bot not found.")
    user = current_user(request)
    selected = bots.selected_version(db, bot_id)
    bot.update(
        name=bot["bot_name"],
        latest_version=bot["version_number"],
        is_owner=bool(user and user["id"] == bot["user_id"]),
        has_files=bool(selected["file_path"]),
        can_download=can_read_source(user, bot),
    )
    if can_read_source(user, bot):
        try:
            bot["source_code"] = bots.read_source(request.app.state.settings, selected)
        except FileNotFoundError:
            bot["source_code"] = db.one(
                "SELECT source_code FROM bot_versions WHERE id=?",
                (selected["version_id"],),
            )["source_code"]
    versions = db.all(
        "SELECT id,version_number,description,rating,created_at FROM bot_versions WHERE bot_id=? ORDER BY version_number DESC",
        (bot_id,),
    )
    history = db.all(
        "SELECT v.version_number,h.match_id,h.rating,h.created_at FROM rating_history h JOIN bot_versions v ON v.id=h.version_id WHERE h.bot_id=? ORDER BY h.id DESC LIMIT 20",
        (bot_id,),
    )[::-1]
    total = db.one(
        "SELECT COUNT(*) AS n FROM rating_history WHERE bot_id=?", (bot_id,)
    )["n"]
    recent = [flat_match(match) for match in list_matches(db, bot_id=bot_id)]
    return render(
        request,
        "bot_detail.html",
        "main.bot_detail",
        bot=bot,
        versions=versions,
        history=history,
        history_total=total,
        history_limit=20,
        recent_matches=recent,
    )


@router.get("/bots/{bot_id}/new-version")
@router.get("/bot/{bot_id}/new-version")
def new_version(bot_id: str, request: Request, user=Depends(require_user)):
    bot = bots.owned(request.app.state.db, bot_id, user)
    return render(
        request,
        "new_version.html",
        "upload.new_version_page",
        bot=bot | {"name": bot["bot_name"]},
    )


async def form_upload(request, user, bot_id=None):
    async with request.form(
        max_files=1, max_fields=12, max_part_size=request.app.state.settings.max_upload
    ) as form:
        file = form.get("botFile")
        filename = getattr(file, "filename", "") or ""
        raw = (
            await file.read(request.app.state.settings.max_upload + 1)
            if filename
            else None
        )
        language = str(form.get("language", "python3"))
        if (
            not bot_id
            and filename
            and filename.lower().endswith((".py", ".cpp", ".cc"))
        ):
            language = "python3" if filename.lower().endswith(".py") else "cpp"
        value = bots.save_version(
            request.app.state.db,
            request.app.state.settings,
            user,
            bot_id=bot_id,
            name=str(form.get("botName", "")),
            game=str(form.get("game", "")),
            language=language,
            description=str(form.get("botDescription", "")),
            source=str(form.get("sourceCode", "")),
            filename=filename,
            raw=raw,
        )
    return {"bot_id": value, "message": "Version added." if bot_id else "Bot uploaded."}


@router.post("/upload-bot")
async def upload(request: Request, user=Depends(require_user)):
    return await form_upload(request, user)


@router.post("/bots/{bot_id}/versions")
async def upload_version(bot_id: str, request: Request, user=Depends(require_user)):
    return await form_upload(request, user, bot_id)


@router.post("/bots/{bot_id}/delete")
def delete_bot(
    bot_id: str, body: api_bots.Deletion, request: Request, user=Depends(require_user)
):
    api_bots.delete(bot_id, body, request, user)
    return {"message": "Bot deleted."}


@router.get("/login")
@router.get("/register")
def auth_page(request: Request):
    name = request.url.path.strip("/")
    return render(request, name + ".html", "auth." + name)


@router.post("/login")
@router.post("/register")
async def auth_form(request: Request):
    form = await request.form()
    operation = request.url.path.strip("/")
    body = api_auth.Credentials(
        username=str(form.get("username", "")),
        password=str(form.get("password", "")),
        email=str(form.get("email", "")) or None,
    )
    response = (
        JSONResponse({"message": "Login successful"})
        if operation == "login"
        else RedirectResponse("/", status_code=303)
    )
    api_auth.authenticate(operation, body, request, response)
    return response


@router.get("/chat")
def chat_page(request: Request):
    return render(
        request, "chat.html", "main.chat", **api_community.chat_history(request)
    )


@router.get("/chat/messages")
def chat_messages(request: Request):
    return api_community.chat(request)


@router.post("/chat")
async def chat_send(request: Request, user=Depends(require_user)):
    form = await request.form()
    try:
        message = api_community.send(
            api_community.Message(text=str(form.get("message", ""))), request, user
        )
    except HTTPException as exc:
        return JSONResponse(
            {"success": False, "error": exc.detail}, status_code=exc.status_code
        )
    return {"success": True, "message": message}


@router.get("/admin")
def admin(request: Request, user=Depends(require_admin)):
    return render(request, "admin.html", "admin.console", games=GAMES.values())


@router.get("/admin/database/tables")
def table_names(request: Request, user=Depends(require_admin)):
    return {"tables": [value["name"] for value in api_community.tables(request, user)]}


@router.get("/admin/database/table")
def table_data(
    request: Request,
    name: str,
    page: int = 1,
    page_size: int = 25,
    user=Depends(require_admin),
):
    if page < 1 or page_size not in (25, 50, 100):
        raise HTTPException(400, "Invalid page.")
    value = api_community.table(request, name, page, page_size, user)
    columns = [
        column | {"primary_key": bool(column["pk"])} for column in value["columns"]
    ]
    return value | {
        "columns": columns,
        "rows": [[row[column["name"]] for column in columns] for row in value["rows"]],
        "page_size": page_size,
        "pages": max(1, (value["total"] + page_size - 1) // page_size),
        "cell_limit": 1000,
    }


@router.get("/match/{match_id}")
def match_page(match_id: str, request: Request):
    row = request.app.state.db.one("SELECT * FROM matches WHERE id=?", (match_id,))
    if not row:
        raise HTTPException(404, "Match not found.")
    game = get_game(row["game"])
    value = dict(row)
    for key, default in (("players", {}), ("move_history", []), ("displays", [])):
        value[key] = parse_json(value[key], default)
    template = "snake.html" if game.kind == "snake" else game.slug + ".html"
    return render(
        request, template, "main.match_view", match_id=match_id, match=value, bots=[]
    )


@router.get("/{slug}")
def game_page(slug: str, request: Request):
    if slug in ("yahtzee", "injoker", "catking"):
        return render(request, slug + ".html", "main." + slug)
    try:
        game = get_game(slug)
    except ValueError:
        raise HTTPException(404, "Page not found.")
    demo = None
    for row in request.app.state.db.all(
        "SELECT move_history,displays,winner FROM matches WHERE game=? AND status='finished' ORDER BY created_at DESC,rowid DESC LIMIT 50",
        (game.name,),
    ):
        history = parse_json(row["move_history"], [])
        displays = parse_json(row["displays"], [])
        frames = history if game.kind == "board" else displays
        if not frames or game.kind != "board" and len(frames) < 2:
            continue
        if game.kind == "snake" and any(
            not isinstance(frame, dict)
            or any(
                type(frame.get(str(side))) is not int or not 0 <= frame[str(side)] <= 3
                for side in range(2)
            )
            for frame in displays[1:]
        ):
            continue
        if game.kind == "tank" and any(
            not isinstance(frame, dict)
            or any(
                not isinstance(frame.get(str(side)), list)
                or len(frame[str(side)]) != 2
                or any(
                    type(action) is not int or not -1 <= action <= 7
                    for action in frame[str(side)]
                )
                for side in range(2)
            )
            for frame in displays[1:]
        ):
            continue
        try:
            replay_frames(slug, json.dumps(history), json.dumps(displays))
        except (ValueError, KeyError, TypeError, IndexError):
            continue
        winner = row["winner"]
        demo = {
            "game": game.name,
            "frames": frames,
            "winner": winner + 1
            if game.kind == "board" and winner in (0, 1)
            else 0
            if game.kind == "board"
            else winner,
        }
        break
    template = "snake.html" if game.kind == "snake" else slug + ".html"
    return render(
        request,
        template,
        "main." + slug,
        match_id=None,
        bots=[],
        demo=demo,
        match=demo,
        matches_game=game.slug,
        create_match_game={"slug": game.slug, "name": game.name},
    )
