"""Shared page and browser messages; game and API identifiers stay canonical."""

import json
import re
from http.cookies import SimpleCookie
from pathlib import Path

from starlette.responses import RedirectResponse, Response

LOCALES = ("en", "zh")
COOKIE = "legend_language"
DIRECTORY = Path(__file__).with_name("locales")


def catalog(locale):
    return json.loads((DIRECTORY / f"{locale}.json").read_text(encoding="utf-8"))


def translate(messages, key, *values):
    text = messages.get(str(key), str(key))
    return re.sub(
        r"\{(\d+)\}",
        lambda m: str(values[int(m[1])]) if int(m[1]) < len(values) else m[0],
        text,
    )


def is_page(path):
    return bool(
        re.fullmatch(
            r"/(?:|games|matches|rating|chat|login|register|profile|upload|admin|gomoku|tictactoe|connect4|snake|msnake|tank|yahtzee|injoker|catking|profile/[^/]+|bot/[^/]+(?:/new-version)?|bots/[^/]+/new-version|match/[^/]+)",
            path,
        )
    )


def page_url(path, locale):
    if not path.startswith("/") or path.startswith("//"):
        return path
    bare, separator, query = path.partition("?")
    if is_page(bare):
        return f"/{locale}{bare}{separator}{query}"
    return path


class LocaleMiddleware:
    def __init__(self, app, secure_cookie=False):
        self.app = app
        self.secure_cookie = secure_cookie

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        first, _, rest = path.lstrip("/").partition("/")
        locale = first if first in LOCALES else None
        if locale:
            bare = "/" + rest
            if bare.startswith(("/api/", "/static/")) or bare in ("/api", "/static"):
                return await Response(status_code=404)(scope, receive, send)
            scope = dict(scope)
            scope["path"] = bare
            raw = scope.get("raw_path", path.encode())
            scope["raw_path"] = raw[len(locale) + 1 :] or b"/"
            scope["state"] = dict(scope.get("state", {}), locale=locale)
        elif scope["method"] in ("GET", "HEAD") and is_page(path):
            headers = dict(scope["headers"])
            cookie = SimpleCookie()
            try:
                cookie.load(headers.get(b"cookie", b"").decode("latin-1"))
            except Exception:
                pass
            preferred = cookie[COOKIE].value if COOKIE in cookie else "en"
            locale = preferred if preferred in LOCALES else "en"
            url = page_url(scope.get("raw_path", path.encode()).decode("ascii"), locale)
            query = scope.get("query_string", b"").decode("ascii")
            return await RedirectResponse(
                url + ("?" + query if query else ""),
                status_code=307,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)

        async def localized_send(message):
            if message["type"] == "http.response.start" and locale:
                headers = []
                html = False
                for name, value in message.get("headers", []):
                    if name == b"location":
                        value = page_url(value.decode("latin-1"), locale).encode(
                            "latin-1"
                        )
                    if name == b"content-type" and b"text/html" in value:
                        html = True
                    headers.append((name, value))
                if html:
                    headers.append((b"content-language", locale.encode()))
                    cookie = SimpleCookie()
                    cookie[COOKIE] = locale
                    cookie[COOKIE]["path"] = "/"
                    cookie[COOKIE]["max-age"] = 31536000
                    cookie[COOKIE]["samesite"] = "Lax"
                    cookie[COOKIE]["httponly"] = True
                    if self.secure_cookie:
                        cookie[COOKIE]["secure"] = True
                    headers.append(
                        (b"set-cookie", cookie.output(header="").strip().encode())
                    )
                message = dict(message, headers=headers)
            await send(message)

        await self.app(scope, receive, localized_send)
