from datetime import datetime, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import execute, query
from .labels import DIFFICULTIES, TOPICS
from .services import attempt as attempts
from .services import leaderboard
from .user import requires_auth

bp = Blueprint("contest", __name__, url_prefix="/contests")

KINDS = {"exam": "Kỳ thi", "practice": "Đề luyện tập"}
PRACTICE_DAYS = 3650
GRACE_SECONDS = 15
PRACTICE_URLS = {"question": "quiz.practice", "code": "problem.list", "predict": "task.list", "mix": "practice"}
SECTIONS = {"all": "Luyện tập", "mix": "Tổng hợp", "code": "Luyện lập trình", "question": "Trắc nghiệm AI", "predict": "Học máy nâng cao"}


def get_contest(contestId):
    contest = query('SELECT *, now() AS server_now FROM "Contest" WHERE "contestId" = %s',
                    (contestId,), one=True)
    if contest is None:
        abort(404)
    return contest


def is_active(contest):
    return contest["open"] <= contest["server_now"] < contest["close"]


def list_url(contest):
    return url_for("contest.list") if contest["kind"] == "exam" else url_for("practice")


def safe_next(target, default):
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def missing_ids(items):
    qs = [x for t, x in items if t == "question"]
    ps = [x for t, x in items if t == "problem"]
    found_q = {r["questionId"] for r in query('SELECT "questionId" FROM "Question" WHERE "questionId" = ANY(%s)', (qs,))}
    found_p = {r["problemId"] for r in query('SELECT "problemId" FROM "Problem" WHERE "problemId" = ANY(%s)', (ps,))}
    return [x for x in qs if x not in found_q] + [x for x in ps if x not in found_p]


def read_points(name, default):
    try:
        return max(0.0, float(request.form.get(name) or default))
    except ValueError:
        return default


def random_questions(topic, count, skip):
    if count <= 0:
        return []
    sql = 'SELECT "questionId" FROM "Question" WHERE NOT ("questionId" = ANY(%s))'
    params = [list(skip)]
    if topic:
        sql += " AND topic = %s"
        params.append(topic)
    return [r["questionId"] for r in query(sql + " ORDER BY random() LIMIT %s", (*params, min(count, 200)))]


def has_tasks(contestId):
    return query("""SELECT 1 FROM "ContestItem" ci JOIN "Problem" p ON p."problemId" = ci."problemId"
                    WHERE ci."contestId" = %s AND p.kind = 'predict' LIMIT 1""", (contestId,), one=True)


def practice_list(section):
    topic = request.args.get("topic", "")
    difficulty = request.args.get("difficulty", "")
    match = "q.\"questionId\" IS NOT NULL" if section == "question" else f"p.kind = '{section}'"
    if section in ("all", "mix"):
        match = "TRUE"
    params = [g.user["userId"]]
    having = f"count(*) FILTER (WHERE {match}) > 0"
    if section == "mix":
        having = """(count(q."questionId") > 0)::int + (count(*) FILTER (WHERE p.kind = 'code') > 0)::int
                    + (count(*) FILTER (WHERE p.kind = 'predict') > 0)::int > 1"""
    if topic in TOPICS:
        having += f" AND bool_or({match} AND COALESCE(q.topic, p.topic) = %s)"
        params.append(topic)
    if difficulty in DIFFICULTIES:
        having += f" AND bool_or({match} AND COALESCE(q.difficulty, p.difficulty) = %s)"
        params.append(difficulty)
    tests = query(f"""SELECT c."contestId", c.title, c.descp, c.created, a."attemptId", a.finished, a."totalScore",
                             count(q."questionId") AS n_q,
                             count(*) FILTER (WHERE p.kind = 'code') AS n_p,
                             count(*) FILTER (WHERE p.kind = 'predict') AS n_t,
                             string_agg(DISTINCT COALESCE(q.topic, p.topic), ',') AS topics
                      FROM "Contest" c JOIN "ContestItem" ci ON ci."contestId" = c."contestId"
                      LEFT JOIN "Question" q ON q."questionId" = ci."questionId"
                      LEFT JOIN "Problem" p ON p."problemId" = ci."problemId"
                      LEFT JOIN "ContestAttempt" a ON a."contestId" = c."contestId" AND a."userId" = %s
                      WHERE c.kind = 'practice' AND c.open <= now() AND c.close > now()
                      GROUP BY c."contestId", a."attemptId" HAVING {having}
                      ORDER BY c."contestId" DESC""", params)
    stats = None
    if section == "question":
        from .quiz import statByTopic
        stats = statByTopic(g.user["userId"])
    return render_template("practice.html", tests=tests, section=section, title=SECTIONS[section],
                           topic=topic, difficulty=difficulty, stats=stats)


@bp.route("", endpoint="list")
@requires_auth()
def list_():
    attempts.finish_expired()
    contests = query("""SELECT c.*, now() AS server_now, a."attemptId", a.finished, a."totalScore"
                        FROM "Contest" c
                        LEFT JOIN "ContestAttempt" a ON a."contestId" = c."contestId" AND a."userId" = %s
                        WHERE c.kind = 'exam' ORDER BY c.open DESC""", (g.user["userId"],))
    for c in contests:
        c["active"] = is_active(c)
    return render_template("contests.html", contests=contests)


def insert_contest(info, kind, items, open_at, close_at, duration, privMin):
    contest = execute("""INSERT INTO "Contest" (title, descp, duration, open, close, "privMin", kind, author)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING "contestId" """,
                      (info["title"], info.get("descp", ""), duration, open_at, close_at, privMin, kind,
                       g.user["userId"]), returning=True)
    for position, (itemType, id) in enumerate(items):
        points = read_points(f"points_{itemType}_{id}", 1.0 if itemType == "question" else 10.0)
        execute("""INSERT INTO "ContestItem" ("contestId", "itemType", "questionId", "problemId", points, position)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (contest["contestId"], itemType, id if itemType == "question" else None,
                 id if itemType == "problem" else None, points, position))


@bp.route("/new", methods=["GET", "POST"])
@requires_auth("supervisor")
def create():
    questions = query('SELECT "questionId", content, topic FROM "Question" ORDER BY topic, "questionId"')
    problems = query("""SELECT "problemId", title, topic, difficulty, kind, is_publish FROM "Problem"
                        ORDER BY kind, topic, "problemId" """)
    if request.method == "POST":
        info = request.form
        error = None
        try:
            open_at = datetime.fromisoformat(info["open"]).astimezone()
            close_at = datetime.fromisoformat(info["close"]).astimezone()
            duration = int(info["duration"])
            privMin = max(0, int(info.get("privMin") or 0))
            picked = [int(x) for x in info.getlist("questionId")]
            picked += random_questions(info.get("rand_topic", ""), int(info.get("rand_count") or 0), picked)
            items = [("question", x) for x in dict.fromkeys(picked)]
            items += [("problem", int(x)) for x in dict.fromkeys(info.getlist("problemId"))]
            if not info.get("title") or close_at <= open_at or duration <= 0 or not items:
                error = "Cần tiêu đề, thời gian hợp lệ và ít nhất một câu hỏi, bài toán hoặc bài học máy nâng cao."
            elif privMin >= duration:
                error = "Giai đoạn private phải ngắn hơn thời gian làm bài."
            elif missing_ids(items):
                error = "Có câu hỏi hoặc bài toán không tồn tại."
        except (KeyError, ValueError):
            error = "Thời gian không hợp lệ."
        if error:
            flash(error, "error")
        else:
            insert_contest(info, "exam", items, open_at, close_at, duration, privMin)
            flash("Đã tạo kỳ thi.", "ok")
            return redirect(url_for("contest.list"))
    return render_template("contest_new.html", questions=questions, problems=problems)


@bp.route("/practice/new", methods=["GET", "POST"])
@requires_auth("supervisor")
def create_practice():
    section = request.values.get("section", "question")
    if section not in PRACTICE_URLS:
        section = "question"
    questions, problems = [], []
    if section in ("question", "mix"):
        questions = query('SELECT "questionId", content, topic FROM "Question" ORDER BY topic, "questionId"')
    if section != "question":
        kinds = ["code", "predict"] if section == "mix" else [section]
        problems = query("""SELECT "problemId", title, topic, difficulty, kind, is_publish FROM "Problem"
                            WHERE kind = ANY(%s) ORDER BY kind, topic, "problemId" """, (kinds,))
    if request.method == "POST":
        info = request.form
        error = None
        try:
            items = []
            if section in ("question", "mix"):
                picked = [int(x) for x in info.getlist("questionId")]
                picked += random_questions(info.get("rand_topic", ""), int(info.get("rand_count") or 0), picked)
                items = [("question", x) for x in dict.fromkeys(picked)]
            if section != "question":
                allowed = {p["problemId"] for p in problems}
                items += [("problem", x) for x in dict.fromkeys(int(x) for x in info.getlist("problemId")) if x in allowed]
            if not info.get("title") or not items:
                error = "Cần tiêu đề và ít nhất một mục."
            elif missing_ids(items):
                error = "Có câu hỏi hoặc bài toán không tồn tại."
        except ValueError:
            error = "Dữ liệu không hợp lệ."
        if error:
            flash(error, "error")
        else:
            open_at = datetime.now().astimezone()
            insert_contest(info, "practice", items, open_at, open_at + timedelta(days=PRACTICE_DAYS),
                           PRACTICE_DAYS * 24 * 60, 0)
            flash("Đã tạo đề luyện tập.", "ok")
            return redirect(url_for("practice", section="mix") if section == "mix" else url_for(PRACTICE_URLS[section]))
    return render_template("practice_new.html", section=section, questions=questions, problems=problems)


@bp.route("/<int:contestId>/join", methods=["POST"])
@requires_auth()
def join(contestId):
    contest = get_contest(contestId)
    attempt = attempts.of_user(contestId, g.user["userId"])
    if attempt is None:
        if not is_active(contest):
            flash(f"{KINDS[contest['kind']]} chưa mở hoặc đã đóng, không thể tham gia.", "error")
            return redirect(list_url(contest))
        execute("""INSERT INTO "ContestAttempt" ("contestId", "userId", deadline)
                   VALUES (%s, %s, LEAST(now() + make_interval(mins => %s), %s))
                   ON CONFLICT ("contestId", "userId") DO NOTHING""",
                (contestId, g.user["userId"], contest["duration"], contest["close"]))
    return redirect(url_for("contest.take", contestId=contestId))


@bp.route("/<int:contestId>/retry", methods=["POST"])
@requires_auth()
def retry(contestId):
    contest = get_contest(contestId)
    attempt = attempts.of_user(contestId, g.user["userId"])
    if contest["kind"] != "practice" or attempt is None or not is_active(contest):
        abort(404)
    execute('DELETE FROM "AttemptAnswer" WHERE "attemptId" = %s', (attempt["attemptId"],))
    execute("""UPDATE "ContestAttempt" SET start = now(), finished = NULL, duration = NULL, "totalScore" = 0
               WHERE "attemptId" = %s""", (attempt["attemptId"],))
    return redirect(url_for("contest.take", contestId=contestId))


@bp.route("/<int:contestId>/take")
@requires_auth()
def take(contestId):
    contest = get_contest(contestId)
    attempt = attempts.of_user(contestId, g.user["userId"])
    if attempt is None:
        return redirect(list_url(contest))
    if attempts.is_expired(attempt):
        attempts.finish(attempt["attemptId"])
        return redirect(url_for("contest.result", contestId=contestId))
    questions = query("""SELECT ci.points, q."questionId", q.content, q.code, q.image,
                                 q.op1, q.op2, q.op3, q.op4, aa.selected
                          FROM "ContestItem" ci JOIN "Question" q ON q."questionId" = ci."questionId"
                          LEFT JOIN "AttemptAnswer" aa ON aa."attemptId" = %s AND aa."questionId" = q."questionId"
                          WHERE ci."contestId" = %s AND ci."itemType" = 'question'
                          ORDER BY ci.position, ci."itemId" """, (attempt["attemptId"], contestId))
    problems = query("""SELECT ci.points, p."problemId", p.title, p.topic, p.difficulty,
                                (SELECT max(CASE WHEN s.total > 0 THEN s.passed::real / s.total END)
                                 FROM "Submission" s WHERE s."attemptId" = %s AND s."problemId" = p."problemId"
                                   AND s.status = 'done') AS best_ratio
                         FROM "ContestItem" ci JOIN "Problem" p ON p."problemId" = ci."problemId"
                         WHERE ci."contestId" = %s AND ci."itemType" = 'problem' AND p.kind = 'code'
                         ORDER BY ci.position, ci."itemId" """, (attempt["attemptId"], contestId))
    seconds_left = int((attempt["deadline"] - contest["server_now"]).total_seconds())
    return render_template("contest_take.html", contest=contest, attempt=attempt, questions=questions,
                           problems=problems, tasks=attempts.task_items(attempt),
                           phase=attempts.currentPhase(attempt), seconds_left=max(seconds_left, 0))


@bp.route("/<int:contestId>/answer", methods=["POST"])
@requires_auth()
def answer(contestId):
    attempt = attempts.of_user(contestId, g.user["userId"])
    if attempt is None:
        abort(404)
    if not attempts.is_expired(attempt):
        attempts.save(attempt, request.form)
    target = request.form.get("next", "")
    return redirect(safe_next(target, url_for("contest.take", contestId=contestId)))


@bp.route("/<int:contestId>/submit", methods=["POST"])
@requires_auth()
def submit(contestId):
    contest = get_contest(contestId)
    attempt = attempts.of_user(contestId, g.user["userId"])
    if attempt is None:
        abort(404)
    finished = attempt["finished"] is not None
    if not attempts.is_expired(attempt, GRACE_SECONDS):
        attempts.save(attempt, request.form)
    attempts.finish(attempt["attemptId"])
    if contest["kind"] == "practice" and not finished:
        from .quiz import checkPractice
        checkPractice(g.user, attempt["attemptId"])
    return redirect(url_for("contest.result", contestId=contestId))


@bp.route("/<int:contestId>/result")
@requires_auth()
def result(contestId):
    contest = get_contest(contestId)
    attempt = attempts.of_user(contestId, g.user["userId"])
    if attempt is None or attempt["finished"] is None:
        return redirect(url_for("contest.take", contestId=contestId))
    attempts.recompute(attempt["attemptId"])
    attempt = attempts.of_user(contestId, g.user["userId"])
    answers = query("""SELECT ci.points, q.content, q.key, q.explain, aa.selected, aa.is_correct
                        FROM "ContestItem" ci JOIN "Question" q ON q."questionId" = ci."questionId"
                        LEFT JOIN "AttemptAnswer" aa ON aa."attemptId" = %s AND aa."questionId" = q."questionId"
                        WHERE ci."contestId" = %s AND ci."itemType" = 'question'
                        ORDER BY ci.position, ci."itemId" """, (attempt["attemptId"], contestId))
    problems = query("""SELECT ci.points, p.title,
                                COALESCE(max(CASE WHEN s.total > 0 AND s.status = 'done' AND s.created <= %s
                                    THEN s.passed::real / s.total END), 0) AS best_ratio,
                                count(s."submissionId") FILTER (WHERE s.status IN ('queued', 'judging')) AS pending
                         FROM "ContestItem" ci JOIN "Problem" p ON p."problemId" = ci."problemId"
                         LEFT JOIN "Submission" s ON s."attemptId" = %s AND s."problemId" = p."problemId"
                         WHERE ci."contestId" = %s AND ci."itemType" = 'problem' AND p.kind = 'code'
                         GROUP BY ci."itemId", ci.points, p.title ORDER BY min(ci.position), ci."itemId" """,
                     (attempt["deadline"], attempt["attemptId"], contestId))
    practice = contest["kind"] == "practice"
    return render_template("contest_result.html", contest=contest, attempt=attempt, answers=answers,
                           problems=problems, tasks=attempts.task_items(attempt), practice=practice,
                           closed=practice or contest["server_now"] >= contest["close"])


@bp.route("/<int:contestId>/leaderboard")
def top(contestId):
    contest = get_contest(contestId)
    if contest["kind"] != "exam":
        abort(404)
    attempts.finish_expired(contestId)
    if has_tasks(contestId):
        cache = {}
        for row in query('SELECT "attemptId" FROM "ContestAttempt" WHERE "contestId" = %s AND finished IS NOT NULL',
                         (contestId,)):
            attempts.recompute(row["attemptId"], cache)
    return render_template("leaderboard.html", contest=contest, rows=leaderboard.topScore(contestId))
