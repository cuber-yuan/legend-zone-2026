"""Read-only match browsing with participant-based filters and public pickers."""

from datetime import datetime, timezone

from .games import get_game
from .matches import serialize_matches

RAW_PLAYERS = (
    "json_each(CASE WHEN json_valid(m.players) THEN m.players ELSE '{}' END) j"
)
PLAYER = "CASE WHEN j.type='object' THEN j.value ELSE '{}' END"
RAW_BOT = f"COALESCE(json_extract({PLAYER},'$.type'),'bot')='bot'"


def time_bound(value):
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError):
        raise ValueError("Use a valid date and time with a timezone.")


def search(
    db,
    active_ids,
    *,
    bots=(),
    bot_mode="all",
    game=None,
    author=None,
    status="all",
    rating="all",
    created_from=None,
    created_to=None,
    page=1,
):
    conditions, args = [], []
    bots = list(dict.fromkeys(bots))
    if len(bots) > 20 or any(not bot or len(bot) > 100 for bot in bots):
        raise ValueError("Select at most 20 Bots with valid IDs.")
    if (
        bot_mode not in ("all", "any")
        or status not in ("all", "playing", "finished", "interrupted")
        or rating not in ("all", "rated", "unrated")
    ):
        raise ValueError("Invalid match filter.")
    if game:
        conditions.append("m.game=?")
        args.append(get_game(game).name)
    clauses = []
    for bot in bots:
        clauses.append(
            "(EXISTS (SELECT 1 FROM match_players p WHERE p.match_id=m.id AND p.player_type='bot' "
            "AND (p.bot_id=? OR p.bot_id_snapshot=?)) OR "
            f"EXISTS (SELECT 1 FROM {RAW_PLAYERS} WHERE {RAW_BOT} "
            f"AND json_extract({PLAYER},'$.bot_id')=? "
            "AND NOT EXISTS (SELECT 1 FROM match_players p WHERE p.match_id=m.id AND j.key='player_'||p.seat)))"
        )
        args.extend((bot, bot, bot))
    if clauses:
        conditions.append(
            "(" + (" AND " if bot_mode == "all" else " OR ").join(clauses) + ")"
        )
    if author is not None:
        conditions.append(
            f"(EXISTS (SELECT 1 FROM {RAW_PLAYERS} WHERE {RAW_BOT} AND "
            f"json_extract({PLAYER},'$.owner_id')=?) OR "
            "EXISTS (SELECT 1 FROM match_players p JOIN bots b ON b.id=COALESCE(p.bot_id,p.bot_id_snapshot) "
            "WHERE p.match_id=m.id AND p.player_type='bot' AND b.user_id=? "
            f"AND NOT EXISTS (SELECT 1 FROM {RAW_PLAYERS} WHERE j.key='player_'||p.seat "
            f"AND json_extract({PLAYER},'$.owner_id') IS NOT NULL)) OR "
            f"EXISTS (SELECT 1 FROM {RAW_PLAYERS} JOIN bots b ON b.id=json_extract({PLAYER},'$.bot_id') "
            f"WHERE {RAW_BOT} AND json_extract({PLAYER},'$.owner_id') IS NULL AND b.user_id=? "
            "AND NOT EXISTS (SELECT 1 FROM match_players p WHERE p.match_id=m.id AND j.key='player_'||p.seat)))"
        )
        args.extend((author, author, author))
    placeholders = ",".join("?" for _ in active_ids)
    live = f"m.status='playing' AND m.id IN ({placeholders})" if active_ids else "0"
    abandoned = (
        f"m.status='playing' AND m.id NOT IN ({placeholders})"
        if active_ids
        else "m.status='playing'"
    )
    interrupted = f"(({abandoned}) OR (m.status='finished' AND m.termination_reason='server_error'))"
    if status == "playing":
        conditions.append(f"({live})")
        args.extend(active_ids)
    elif status == "interrupted":
        conditions.append(interrupted)
        args.extend(active_ids)
    elif status == "finished":
        conditions.append(
            "m.status='finished' AND COALESCE(m.termination_reason,'')!='server_error'"
        )
    if rating != "all":
        conditions.append(
            "m.rating_status='applied'"
            if rating == "rated"
            else "m.rating_status='skipped'"
        )
    start, end = time_bound(created_from), time_bound(created_to)
    if start and end and datetime.fromisoformat(start) > datetime.fromisoformat(end):
        raise ValueError("The start time must not be after the end time.")
    for bound, operator in ((start, ">="), (end, "<=")):
        if bound:
            conditions.append(f"julianday(m.created_at){operator}julianday(?)")
            args.append(bound)
    where = " AND ".join(f"({condition})" for condition in conditions) or "1=1"
    # Count and rows use one read snapshot so concurrent completions cannot split pagination.
    with db.connect() as conn:
        conn.execute("BEGIN")
        total = conn.execute(
            f"SELECT count(*) FROM matches m WHERE {where}", args
        ).fetchone()[0]
        pages = max(1, (total + 19) // 20)
        page = min(max(1, page), pages)
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT m.id,m.game,m.players,m.status,m.winner,m.created_at,m.started_at,m.finished_at,m.termination_reason,m.rating_status "
                f"FROM matches m WHERE {where} ORDER BY m.created_at DESC,m.rowid DESC LIMIT 20 OFFSET ?",
                [*args, (page - 1) * 20],
            )
        ]
    matches = serialize_matches(db, rows)
    for item in matches:
        if item["status"] == "playing" and item["id"] not in active_ids:
            item["status"] = "interrupted"
        item["display_status"] = (
            "interrupted"
            if item["termination_reason"] == "server_error"
            else item["status"]
        )
    return {
        "matches": matches,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": 20,
    }


def like(value):
    return (
        "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    )


def bot_options(db, q="", ids=(), game=None):
    args = []
    conditions = []
    if game:
        conditions.append("game=?")
        args.append(get_game(game).name)
    if ids:
        conditions.append("id IN (" + ",".join("?" for _ in ids) + ")")
        args.extend(ids)
    elif q:
        conditions.append(
            "(bot_name LIKE ? ESCAPE '\\' OR id LIKE ? ESCAPE '\\' OR owner LIKE ? ESCAPE '\\')"
        )
        args.extend([like(q)] * 3)
    where = " AND ".join(conditions) or "1=1"
    return db.all(
        "WITH options AS (SELECT b.id,b.bot_name,b.game,u.username owner,0 deleted FROM bots b JOIN users u ON u.id=b.user_id "
        "UNION ALL SELECT p.bot_id_snapshot,MIN(p.player_name),m.game,NULL,1 FROM match_players p JOIN matches m ON m.id=p.match_id "
        "WHERE p.player_type='bot' AND p.bot_id_snapshot IS NOT NULL AND NOT EXISTS (SELECT 1 FROM bots b WHERE b.id=p.bot_id_snapshot) "
        "GROUP BY p.bot_id_snapshot,m.game) "
        f"SELECT * FROM options WHERE {where} ORDER BY deleted,bot_name,id LIMIT 20",
        args,
    )


def author_options(db, q="", user_id=None):
    if user_id is not None:
        return db.all("SELECT id,username FROM users WHERE id=?", (user_id,))
    return db.all(
        "SELECT id,username FROM users WHERE username LIKE ? ESCAPE '\\' ORDER BY username LIMIT 20",
        (like(q),),
    )
