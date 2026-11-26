from flask import current_app

from ..db import query
from ..queue import get_redis


def get_key(contestId):
    return f"leaderboard:contest:{contestId}"


def rank_value(totalScore, duration):
    return round(totalScore * 1_000_000) - min(duration or 0, 999_999)


def push(attempt):
    try:
        get_redis().zadd(get_key(attempt["contestId"]),
                         {str(attempt["userId"]): rank_value(attempt["totalScore"], attempt["duration"])})
    except Exception:
        pass


def topScore(contestId):
    size = current_app.config["LEADERBOARD_SIZE"]
    rows = query("""SELECT a."contestId", a."userId", u.username, a."totalScore", a.duration
                    FROM "ContestAttempt" a JOIN "User" u ON u."userId" = a."userId"
                    WHERE a."contestId" = %s AND a.finished IS NOT NULL""", (contestId,))
    by_user = {str(r["userId"]): r for r in rows}
    try:
        ids = [m.decode() for m in get_redis().zrevrange(get_key(contestId), 0, size - 1)]
        if len(ids) < min(size, len(rows)):
            raise LookupError
        return [by_user[i] for i in ids if i in by_user]
    except Exception:
        ranked = sorted(rows, key=lambda r: (-r["totalScore"], r["duration"] or 0))[:size]
        for r in ranked:
            push(r)
        return ranked


def overall(kind):
    return query("""SELECT u."userId", u.username, sum(a."totalScore") AS total, count(*) AS n
                    FROM "ContestAttempt" a JOIN "Contest" c ON c."contestId" = a."contestId"
                    JOIN "User" u ON u."userId" = a."userId"
                    WHERE c.kind = %s AND a.finished IS NOT NULL AND u.role = 'student'
                    GROUP BY u."userId", u.username
                    ORDER BY total DESC, min(a.finished)""", (kind,))


