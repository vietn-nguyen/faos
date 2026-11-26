from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, url_for)

from .db import commit, execute, query
from .queue import enqueue, get_redis
from .services import attempt as attempts
from .services import judge0
from .services.grading import grade
from .user import requires_auth

bp = Blueprint("submission", __name__)


def checkCooldown(user, kind="submit"):
    cooldown = current_app.config["SUBMIT_COOLDOWN_SECONDS"]
    try:
        return bool(get_redis().set(f"cooldown:{kind}:{user['userId']}", 1, nx=True, ex=cooldown))
    except Exception:
        return True


def check_code(code):
    if not code.strip():
        return "Code đang trống."
    if len(code.encode("utf-8")) > current_app.config["MAX_CODE_BYTES"]:
        return "Code vượt quá 64 KB."
    return None


def can_practice(problemId):
    if g.user["role"] == "student":
        return False
    return query('SELECT 1 FROM "Problem" WHERE "problemId" = %s AND is_publish', (problemId,), one=True) is not None


def get_submission(submissionId):
    sub = query("""SELECT s.*, p.title FROM "Submission" s
                   JOIN "Problem" p ON p."problemId" = s."problemId" WHERE s."submissionId" = %s""",
                (submissionId,), one=True)
    if sub is None:
        abort(404)
    if sub["userId"] != g.user["userId"] and g.user["role"] == "student":
        abort(403)
    return sub


@bp.route("/problems/<int:problemId>/submit", methods=["POST"])
@requires_auth()
def submit(problemId):
    code = request.form.get("sourceCode", "")
    attemptId = request.form.get("attemptId", type=int)
    back = url_for("problem.detail", problemId=problemId, attempt=attemptId)
    if not query("""SELECT 1 FROM "Problem" WHERE "problemId" = %s AND kind = 'code'""", (problemId,), one=True):
        abort(404)

    error = check_code(code)
    if error:
        flash(error, "error")
        return redirect(back)
    if attemptId:
        attempt = attempts.for_problem(attemptId, problemId, g.user["userId"])
        if attempt is None:
            abort(404)
        if attempts.is_expired(attempt):
            flash("Lượt thi đã hết giờ, không nhận thêm bài nộp.", "error")
            return redirect(url_for("contest.result", contestId=attempt["contestId"]))
    elif not can_practice(problemId):
        abort(404)
    if not checkCooldown(g.user):
        flash(f"Chờ {current_app.config['SUBMIT_COOLDOWN_SECONDS']} giây giữa hai lần nộp.", "error")
        return redirect(back)

    row = execute("""INSERT INTO "Submission" ("userId", "problemId", "attemptId", "sourceCode")
                     VALUES (%s, %s, %s, %s) RETURNING "submissionId" """,
                  (g.user["userId"], problemId, attemptId, code), returning=True)
    commit()
    try:
        enqueue(grade, row["submissionId"])
    except Exception as e:
        execute("""UPDATE "Submission" SET status = 'system_error', "errMess" = %s WHERE "submissionId" = %s""",
                (f"Không đưa được vào hàng đợi: {e}"[:500], row["submissionId"]))
    return redirect(url_for("submission.detail", submissionId=row["submissionId"]))


@bp.route("/problems/<int:problemId>/run", methods=["POST"])
@requires_auth()
def run(problemId):
    code = request.form.get("sourceCode", "")
    attemptId = request.form.get("attemptId", type=int)
    problem = query("""SELECT * FROM "Problem" WHERE "problemId" = %s AND kind = 'code'""", (problemId,), one=True)
    if problem is None:
        return jsonify({"error": "not found"}), 404
    if attemptId:
        attempt = attempts.for_problem(attemptId, problemId, g.user["userId"])
        if attempt is None or attempts.is_expired(attempt):
            return jsonify({"error": "Lượt thi không hợp lệ hoặc đã hết giờ."}), 403
    elif not can_practice(problemId):
        return jsonify({"error": "not found"}), 404
    error = check_code(code)
    if error:
        return jsonify({"error": error}), 400
    if not checkCooldown(g.user, "run"):
        return jsonify({"error": f"Chờ {current_app.config['SUBMIT_COOLDOWN_SECONDS']} giây giữa hai lần chạy."}), 429
    samples = query("""SELECT * FROM "TestCase" t WHERE t."problemId" = %s AND t.sample
                       ORDER BY t.position, t."TestCaseId" """, (problemId,))
    try:
        results = judge0.runBatch(code, [s["input"] for s in samples],
                                  problem["timeLimit"], problem["memoryLimit"])
    except Exception as e:
        return jsonify({"error": f"Judge0 lỗi: {e}"}), 502
    out = []
    for s, r in zip(samples, results):
        verdict = judge0.get_verdict(r, s["output"])
        if verdict is None:
            return jsonify({"error": "Judge0 không phản hồi."}), 502
        out.append({"input": s["input"], "output": s["output"],
                    "stdout": r["stdout"], "stderr": r["stderr"], "verdict": verdict})
    return jsonify({"results": out})


@bp.route("/submissions/<int:submissionId>")
@requires_auth()
def detail(submissionId):
    sub = get_submission(submissionId)
    results = query("""SELECT r.verdict, r.time, r.memory, r.stdout, r.stderr,
                              t.sample, t.input, t.output
                       FROM "SubmissionResult" r JOIN "TestCase" t ON t."TestCaseId" = r."TestCaseId"
                       WHERE r."submissionId" = %s ORDER BY t.sample DESC, t.position, t."TestCaseId" """,
                    (submissionId,))
    return render_template("submission.html", sub=sub, results=results)


@bp.route("/submissions/<int:submissionId>/status")
@requires_auth()
def status(submissionId):
    sub = get_submission(submissionId)
    return jsonify({"status": sub["status"], "verdict": sub["verdict"],
                    "passed": sub["passed"], "total": sub["total"]})


@bp.route("/submissions")
@requires_auth()
def history():
    kind = "exam" if request.args.get("kind") == "exam" else "practice"
    rows = query("""SELECT a."attemptId", a."contestId", a.start, a.finished, a."totalScore", c.title, c.close,
                           (SELECT count(*) FROM "Submission" s WHERE s."attemptId" = a."attemptId")
                           + (SELECT count(*) FROM "Prediction" r WHERE r."attemptId" = a."attemptId")
                           + (SELECT count(*) FROM "AttemptAnswer" aa WHERE aa."attemptId" = a."attemptId"
                              AND aa.selected IS NOT NULL) AS n_done
                    FROM "ContestAttempt" a JOIN "Contest" c ON c."contestId" = a."contestId"
                    WHERE a."userId" = %s AND c.kind = %s ORDER BY a.start DESC""", (g.user["userId"], kind))
    return render_template("submissions.html", rows=rows, kind=kind)
