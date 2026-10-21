"""Application composition; one process serves the API and built frontend."""

import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api_auth import Attempts
from .api_account import router as account_router
from .api_auth import router as auth_router
from .api_bots import router as bots_router
from .api_community import router as community_router
from .api_matches import router as matches_router
from .chat import Chat
from .config import ROOT, Settings
from .database import Database
from .runner import Matches
from .tables import Tables
from .tables import router as tables_router

log = logging.getLogger(__name__)


class ProcessLock:
    def __init__(self, path):
        self.path = path
        self.file = None

    def acquire(self):
        self.file = self.path.open("a+b")
        try:
            if self.path.stat().st_size == 0:
                self.file.write(b"0")
                self.file.flush()
            self.file.seek(0)
            if __import__("os").name == "nt":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError(
                "This data directory already has a running server. Use one worker."
            )

    def release(self):
        if self.file:
            self.file.close()


class BodyLimit:
    def __init__(self, app, limit):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") not in (
            "POST",
            "PUT",
            "PATCH",
            "DELETE",
        ):
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.limit:
                return await JSONResponse(
                    {"detail": "Request exceeds 16 MiB."}, status_code=413
                )(scope, receive, send)
            if not message.get("more_body"):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings=None):
    settings = settings or Settings.load()
    db = Database(settings.database)
    db.validate()  # Read-only; explicit CLI initialization/import owns schema work.
    chat = Chat(db)
    matches = Matches(db, settings)
    process_lock = ProcessLock(settings.data_dir / "server.lock")

    @asynccontextmanager
    async def lifespan(app):
        process_lock.acquire()
        matches.start()
        try:
            yield
        finally:
            # Shutdown finishes active matches without changing ratings.
            import asyncio

            await asyncio.to_thread(matches.close)
            process_lock.release()

    app = FastAPI(title="Legend Zone", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.db = db
    app.state.chat = chat
    app.state.matches = matches
    app.state.attempts = Attempts()
    app.state.tables = Tables()
    app.add_middleware(BodyLimit, limit=settings.max_upload)

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in (
            "GET",
            "HEAD",
            "OPTIONS",
        ):
            if (
                request.url.path.startswith("/api/")
                and request.headers.get("X-Legend-Request") != "1"
            ):
                return JSONResponse(
                    {"detail": "Missing request header."}, status_code=403
                )
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return JSONResponse(
                    {"detail": "Cross-origin request rejected."}, status_code=403
                )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request, exc):
        return JSONResponse(
            {
                "detail": "The name already exists or the change conflicts with retained data."
            },
            status_code=409,
        )

    @app.exception_handler(sqlite3.OperationalError)
    async def unavailable(request, exc):
        log.error("Database operation failed", exc_info=exc)
        return JSONResponse(
            {"detail": "Database temporarily unavailable."}, status_code=503
        )

    for router in (
        auth_router,
        account_router,
        bots_router,
        matches_router,
        community_router,
        tables_router,
    ):
        app.include_router(router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    from .pages import router as pages_router

    app.mount("/static", StaticFiles(directory=ROOT / "server/static"), name="static")
    app.include_router(pages_router)
    return app
