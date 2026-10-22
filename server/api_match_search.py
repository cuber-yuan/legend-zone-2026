from typing import Literal

from fastapi import APIRouter, Query, Request

from .match_search import author_options, bot_options, search

router = APIRouter(prefix="/api/match-search")


@router.get("")
def browse(
    request: Request,
    bot: list[str] = Query(default=[], max_length=20),
    bot_mode: Literal["all", "any"] = "all",
    game: str | None = Query(default=None, max_length=80),
    author: int | None = Query(default=None, ge=1),
    status: Literal["all", "playing", "finished", "interrupted"] = "all",
    rating: Literal["all", "rated", "unrated"] = "all",
    created_from: str | None = Query(default=None, max_length=40),
    created_to: str | None = Query(default=None, max_length=40),
    page: int = Query(default=1, ge=1, le=50000),
):
    runtime = request.app.state.matches
    with runtime.lock:
        active_ids = tuple(runtime.jobs)
    return search(
        request.app.state.db,
        active_ids,
        bots=bot,
        bot_mode=bot_mode,
        game=game,
        author=author,
        status=status,
        rating=rating,
        created_from=created_from,
        created_to=created_to,
        page=page,
    )


@router.get("/bots")
def bots(
    request: Request,
    q: str = Query(default="", max_length=100),
    id: list[str] = Query(default=[], max_length=20),
    game: str | None = Query(default=None, max_length=80),
):
    if any(not item or len(item) > 100 for item in id):
        raise ValueError("Invalid Bot ID.")
    return bot_options(request.app.state.db, q, id, game)


@router.get("/authors")
def authors(
    request: Request,
    q: str = Query(default="", max_length=40),
    id: int | None = Query(default=None, ge=1),
):
    return author_options(request.app.state.db, q, id)
