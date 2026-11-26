from datetime import datetime, timedelta, timezone

from ..db import execute, query
from ..labels import KEYS
from . import leaderboard, scoring


def has_attempt_with(userId, questionId):
    return query("""SELECT 1 FROM "ContestAttempt" a
                    JOIN "ContestItem" ci ON ci."contestId" = a."contestId" AND ci."questionId" = %s
                    WHERE a."userId" = %s LIMIT 1""", (questionId, userId), one=True) is not None


def get_attempt(attemptId):
    return query('SELECT * FROM "ContestAttempt" WHERE "attemptId" = %s', (attemptId,), one=True)


def of_user(contestId, userId):
    return query('SELECT * FROM "ContestAttempt" WHERE "contestId" = %s AND "userId" = %s',
                 (contestId, userId), one=True)


def for_problem(attemptId, problemId, userId):
    return query("""SELECT a.*, c.kind FROM "ContestAttempt" a
                    JOIN "Contest" c ON c."contestId" = a."contestId"
                    JOIN "ContestItem" ci ON ci."contestId" = a."contestId" AND ci."problemId" = %s
                    WHERE a."attemptId" = %s AND a."userId" = %s""",
                 (problemId, attemptId, userId), one=True)


def is_expired(attempt, grace=0):
    return attempt["finished"] is not None or datetime.now(timezone.utc) >= attempt["deadline"] + timedelta(seconds=grace)


def get_privMin(contestId):
    row = query('SELECT "privMin" FROM "Contest" WHERE "contestId" = %s', (contestId,), one=True)
    return row["privMin"] if row else 0


def final_phase(contestId):
    return "private" if get_privMin(contestId) > 0 else "public"


def currentPhase(attempt):
    privMin = get_privMin(attempt["contestId"])
    left = (attempt["deadline"] - datetime.now(timezone.utc)).total_seconds()
    return "private" if privMin > 0 and left <= privMin * 60 else "public"


def task_items(attempt, cache=None):
    phase = final_phase(attempt["contestId"])
    items = query("""SELECT ci.points, p."problemId", p.title, p.topic, p.difficulty, t."taskId"
                     FROM "ContestItem" ci JOIN "Problem" p ON p."problemId" = ci."problemId"
                     JOIN "Task" t ON t."problemId" = p."problemId"
                     WHERE ci."contestId" = %s AND ci."itemType" = 'problem' AND p.kind = 'predict'
                     ORDER BY ci.position, ci."itemId" """, (attempt["contestId"],))
    for it in items:
        it["phase"] = phase
        it["score"] = scoring.taskScore(it["taskId"], phase, attempt["userId"], attempt["contestId"], cache)
        it["earned"] = round(it["points"] * it["score"] / 100, 2)
    return items


def save(attempt, answers):
    questions = query("""SELECT q."questionId", q.key FROM "ContestItem" ci
                         JOIN "Question" q ON q."questionId" = ci."questionId"
                         WHERE ci."contestId" = %s AND ci."itemType" = 'question'""", (attempt["contestId"],))
    for q in questions:
        selected = answers.get(f"q{q['questionId']}")
        if selected not in KEYS:
            selected = None
        execute("""INSERT INTO "AttemptAnswer" ("attemptId", "questionId", selected, is_correct)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT ("attemptId", "questionId")
                   DO UPDATE SET selected = EXCLUDED.selected, is_correct = EXCLUDED.is_correct""",
                (attempt["attemptId"], q["questionId"], selected, selected == q["key"]))


def recompute(attemptId, cache=None):
    attempt = get_attempt(attemptId)
    if attempt is None:
        return 0
    quiz = query("""SELECT COALESCE(SUM(ci.points), 0) AS pts
                    FROM "AttemptAnswer" aa
                    JOIN "ContestItem" ci ON ci."contestId" = %s AND ci."questionId" = aa."questionId"
                    WHERE aa."attemptId" = %s AND aa.is_correct""",
                 (attempt["contestId"], attemptId), one=True)["pts"]
    code = query("""SELECT COALESCE(SUM(best), 0) AS pts FROM (
                        SELECT ci.points * MAX(CASE WHEN s.total > 0
                                    THEN s.passed::real / s.total ELSE 0 END) AS best
                        FROM "ContestItem" ci
                        JOIN "Submission" s ON s."problemId" = ci."problemId"
                             AND s."attemptId" = %s AND s.status = 'done' AND s.created <= %s
                        WHERE ci."contestId" = %s AND ci."itemType" = 'problem'
                        GROUP BY ci."itemId", ci.points) t""",
                 (attemptId, attempt["deadline"], attempt["contestId"]), one=True)["pts"]
    tasks = sum(it["earned"] for it in task_items(attempt, cache))
    attempt["totalScore"] = round(float(quiz) + float(code) + tasks, 2)
    execute('UPDATE "ContestAttempt" SET "totalScore" = %s WHERE "attemptId" = %s',
            (attempt["totalScore"], attemptId))
    if attempt["finished"] is not None:
        leaderboard.push(attempt)
    return attempt["totalScore"]


def finish(attemptId):
    attempt = get_attempt(attemptId)
    if attempt is None or attempt["finished"] is not None:
        return
    finished = min(datetime.now(timezone.utc), attempt["deadline"])
    duration = int((finished - attempt["start"]).total_seconds())
    execute('UPDATE "ContestAttempt" SET finished = %s, duration = %s WHERE "attemptId" = %s',
            (finished, duration, attemptId))
    recompute(attemptId)


def finish_expired(contestId=None):
    sql = 'SELECT "attemptId" FROM "ContestAttempt" WHERE finished IS NULL AND deadline < now()'
    params = ()
    if contestId is not None:
        sql += ' AND "contestId" = %s'
        params = (contestId,)
    for row in query(sql, params):
        finish(row["attemptId"])
