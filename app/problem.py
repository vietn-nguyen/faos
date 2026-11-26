from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import commit, execute, query
from .queue import enqueue
from .services.grading import grade
from .labels import DIFFICULTIES, TOPICS
from .services import attempt as attempts
from .user import requires_auth

bp = Blueprint("problem", __name__)

FIELDS = ("title", "statement", "input", "output", "constraints",
          "topic", "difficulty", "timeLimit", "memoryLimit")


def read_form():
    data = {k: request.form.get(k, "").strip() for k in FIELDS}
    data["is_publish"] = request.form.get("is_publish") == "on"
    if not data["title"] or not data["statement"]:
        return None
    if data["topic"] not in TOPICS or data["difficulty"] not in DIFFICULTIES:
        return None
    try:
        data["timeLimit"] = float(data["timeLimit"] or 2)
        data["memoryLimit"] = int(data["memoryLimit"] or 128)
    except ValueError:
        return None
    if data["timeLimit"] <= 0 or data["memoryLimit"] <= 0:
        return None
    return data


def get_problem(problemId):
    problem = query('SELECT * FROM "Problem" WHERE "problemId" = %s', (problemId,), one=True)
    if problem is None:
        abort(404)
    return problem


def check_publish(problemId, data):
    if data["is_publish"] and not query('SELECT 1 FROM "TestCase" WHERE "problemId" = %s', (problemId,), one=True):
        data["is_publish"] = False
        flash("Bài chưa có test case nên chưa công khai. Thêm test rồi bật công khai.", "error")


def get_tests(problemId, sample_only=False):
    sql = 'SELECT * FROM "TestCase" t WHERE t."problemId" = %s'
    if sample_only:
        sql += " AND t.sample"
    return query(sql + ' ORDER BY t.sample DESC, t.position, t."TestCaseId"', (problemId,))


@bp.route("/problems", endpoint="list")
@requires_auth()
def list_():
    from .contest import practice_list
    return practice_list("code")


@bp.route("/problems/<int:problemId>")
@requires_auth()
def detail(problemId):
    problem = get_problem(problemId)
    attempt = None
    attemptId = request.args.get("attempt", type=int)
    if problem["kind"] == "predict":
        return redirect(url_for("task.detail", problemId=problemId, attempt=attemptId))
    if attemptId:
        attempt = attempts.for_problem(attemptId, problemId, g.user["userId"])
        if attempt is None:
            abort(404)
    elif g.user["role"] == "student" or not problem["is_publish"]:
        abort(404)
    history = query("""SELECT * FROM "Submission" WHERE "problemId" = %s AND "userId" = %s
                       AND "attemptId" IS NOT DISTINCT FROM %s
                       ORDER BY "submissionId" DESC LIMIT 10""",
                    (problemId, g.user["userId"], attemptId))
    last_code = history[0]["sourceCode"] if history else ""
    return render_template("problem.html", problem=problem, samples=get_tests(problemId, True),
                           history=history, attempt=attempt, last_code=last_code)


@bp.route("/manage/problems")
@requires_auth("supervisor")
def bank():
    rows = query("""SELECT p.*, (SELECT count(*) FROM "TestCase" t WHERE t."problemId" = p."problemId") AS n_tests
                    FROM "Problem" p WHERE p.kind = 'code' ORDER BY p."problemId" DESC""")
    return render_template("problem_bank.html", problems=rows)


@bp.route("/manage/problems/new", methods=["GET", "POST"])
@requires_auth("supervisor")
def create():
    if request.method == "POST":
        data = read_form()
        if data is None:
            flash("Thiếu tiêu đề, đề bài, chủ đề hoặc độ khó.", "error")
        else:
            check_publish(None, data)
            row = execute("""INSERT INTO "Problem" (title, statement, input, output, constraints, topic,
                             difficulty, "timeLimit", "memoryLimit", is_publish, author)
                             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING "problemId" """,
                          (*[data[k] for k in FIELDS], data["is_publish"], g.user["userId"]),
                          returning=True)
            flash("Đã tạo bài toán, giờ thêm test case.", "ok")
            return redirect(url_for("problem.update", problemId=row["problemId"]))
    return render_template("problem_edit.html", problem=None, tests=[])


@bp.route("/manage/problems/<int:problemId>/edit", methods=["GET", "POST"])
@requires_auth("supervisor")
def update(problemId):
    problem = get_problem(problemId)
    if request.method == "POST":
        data = read_form()
        if data is None:
            flash("Thiếu tiêu đề, đề bài, chủ đề hoặc độ khó.", "error")
        else:
            check_publish(problemId, data)
            execute("""UPDATE "Problem" SET title=%s, statement=%s, input=%s, output=%s, constraints=%s,
                       topic=%s, difficulty=%s, "timeLimit"=%s, "memoryLimit"=%s, is_publish=%s
                       WHERE "problemId"=%s""",
                    (*[data[k] for k in FIELDS], data["is_publish"], problemId))
            flash("Đã lưu.", "ok")
            return redirect(url_for("problem.update", problemId=problemId))
    n_subs = query('SELECT count(*) AS n FROM "Submission" WHERE "problemId" = %s', (problemId,), one=True)["n"]
    return render_template("problem_edit.html", problem=problem, tests=get_tests(problemId), n_subs=n_subs)


@bp.route("/manage/problems/<int:problemId>/rejudge", methods=["POST"])
@requires_auth("supervisor")
def rejudge(problemId):
    get_problem(problemId)
    rows = query("""UPDATE "Submission" SET status = 'queued', verdict = NULL, passed = 0, judged = NULL,
                    "errMess" = NULL WHERE "problemId" = %s RETURNING "submissionId" """, (problemId,))
    commit()
    failed = 0
    for r in rows:
        try:
            enqueue(grade, r["submissionId"])
        except Exception as e:
            failed += 1
            execute("""UPDATE "Submission" SET status = 'system_error', "errMess" = %s WHERE "submissionId" = %s""",
                    (f"Không đưa được vào hàng đợi: {e}"[:500], r["submissionId"]))
    flash(f"Đã đưa {len(rows) - failed}/{len(rows)} bài nộp vào hàng đợi chấm lại.", "ok" if not failed else "error")
    return redirect(url_for("problem.update", problemId=problemId))


@bp.route("/manage/problems/<int:problemId>/delete", methods=["POST"])
@requires_auth("supervisor")
def delete(problemId):
    used = query("""SELECT EXISTS (SELECT 1 FROM "Submission" WHERE "problemId" = %s)
                        OR EXISTS (SELECT 1 FROM "ContestItem" WHERE "problemId" = %s) AS used""",
                 (problemId, problemId), one=True)["used"]
    if used:
        flash("Bài toán đã có bài nộp hoặc nằm trong kỳ thi, không xoá được. Hãy bỏ công khai.", "error")
        return redirect(url_for("problem.update", problemId=problemId))
    execute('DELETE FROM "Problem" WHERE "problemId" = %s', (problemId,))
    flash("Đã xoá bài toán.", "ok")
    return redirect(url_for("problem.bank"))


@bp.route("/manage/problems/<int:problemId>/model", methods=["POST"])
@requires_auth("supervisor")
def setModel(problemId):
    row = execute("""UPDATE "Problem" SET is_model = NOT is_model WHERE "problemId" = %s RETURNING kind, is_model""",
                  (problemId,), returning=True)
    if row is None:
        abort(404)
    flash("Đã đánh dấu là đề mẫu cho việc tạo đề." if row["is_model"] else "Đã bỏ đánh dấu đề mẫu.", "ok")
    return redirect(url_for("task.bank" if row["kind"] == "predict" else "problem.bank"))


@bp.route("/manage/problems/<int:problemId>/tests", methods=["POST"])
@requires_auth("supervisor")
def addTestCase(problemId):
    get_problem(problemId)
    execute("""INSERT INTO "TestCase" ("problemId", input, output, sample, position)
               VALUES (%s, %s, %s, %s,
                       (SELECT COALESCE(max(t.position), -1) + 1 FROM "TestCase" t WHERE t."problemId" = %s))""",
            (problemId, request.form.get("input", ""), request.form.get("output", ""),
             request.form.get("sample") == "on", problemId))
    return redirect(url_for("problem.update", problemId=problemId))


@bp.route("/manage/problems/<int:problemId>/tests/<int:id>/delete", methods=["POST"])
@requires_auth("supervisor")
def deleteTestCase(problemId, id):
    execute('DELETE FROM "TestCase" WHERE "TestCaseId" = %s AND "problemId" = %s', (id, problemId))
    if not query('SELECT 1 FROM "TestCase" WHERE "problemId" = %s', (problemId,), one=True):
        execute('UPDATE "Problem" SET is_publish = FALSE WHERE "problemId" = %s', (problemId,))
        flash("Bài không còn test case nên đã bỏ công khai.", "error")
    return redirect(url_for("problem.update", problemId=problemId))
