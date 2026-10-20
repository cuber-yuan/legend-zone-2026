from fastapi import HTTPException, Request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE = "legend_session"
MAX_AGE = 7 * 24 * 3600


def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        uid = URLSafeTimedSerializer(
            request.app.state.settings.secret_key, salt="session"
        ).loads(token, max_age=MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return request.app.state.db.one(
        "SELECT id,username,role,membership FROM users WHERE id=?", (uid,)
    )


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required.")
    return user


def set_session(response, settings, uid):
    token = URLSafeTimedSerializer(settings.secret_key, salt="session").dumps(uid)
    response.set_cookie(
        COOKIE,
        token,
        max_age=MAX_AGE,
        httponly=True,
        secure=settings.secure_cookie,
        samesite="lax",
        path="/",
    )


def can_read_source(user, bot):
    return not bot["is_private"] or bool(user and user["id"] == bot["user_id"])
