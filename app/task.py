import json
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template,
                   request, send_file, url_for)
from psycopg.types.json import Jsonb

from .db import commit, execute, query
from .labels import DATA_ROLES, DIFFICULTIES, METRICS, PHASES, TOPICS
from .queue import enqueue
from .services import attempt as attempts
from .services import scoring, storage
from .services.scoring import score
from .submission import checkCooldown
from .user import requires_auth

bp = Blueprint("task", __name__)

FIELDS = ("title", "statement", "topic", "difficulty")
TASK_FIELDS = ("dataDesc", "submitFormat", "baseline")
ALLOWED = (".csv", ".json", ".jsonl", ".zip")
OPEN_ROLES = ("train", "public_test", "private_test", "other")


def get_task(problemId):
    task = query("""SELECT p.*, t."taskId", t."dataDesc", t."submitFormat", t.baseline,
                           t."pubLimit", t."priLimit"
                    FROM "Problem" p JOIN "Task" t ON t."problemId" = p."problemId"
                    WHERE p."problemId" = %s AND p.kind = 'predict'""", (problemId,), one=True)
    if task is None:
        abort(404)
    return task


def get_attempt(task, attemptId):
    if attemptId:
        attempt = attempts.for_problem(attemptId, task["problemId"], g.user["userId"])
        if attempt is None:
            abort(404)
        return attempt
    if g.user["role"] == "student":
        abort(404)
    return None


def get_datasets(taskId):
    return query('SELECT * FROM "Dataset" WHERE "taskId" = %s ORDER BY role, "dataId"', (taskId,))


def open_phases(task, attempt):
    roles = {d["role"] for d in get_datasets(task["taskId"])}
    phases = [p for p in PHASES if f"{p}_key" in roles]
    if attempt is not None:
        phases = [p for p in phases if p == attempts.currentPhase(attempt)]
    return phases


def checkLimit(task, phase, attempt):
    limit = task["pubLimit"] if phase == "public" else task["priLimit"]
    sql = """SELECT count(*) AS n FROM "Prediction" WHERE "userId" = %s AND "taskId" = %s
             AND phase = %s AND status <> 'system_error'"""
    params = [g.user["userId"], task["taskId"], phase]
    if attempt is not None:
        sql += ' AND "attemptId" = %s'
        params.append(attempt["attemptId"])
    else:
        sql += ' AND "attemptId" IS NULL'
    if attempt is None or attempt["kind"] == "practice":
        sql += " AND created >= date_trunc('day', now())"
    return max(limit - query(sql, params, one=True)["n"], 0)


def get_prediction(predId):
    pred = query("""SELECT r.*, p.title, p."problemId", u.username FROM "Prediction" r
                    JOIN "Task" t ON t."taskId" = r."taskId"
                    JOIN "Problem" p ON p."problemId" = t."problemId"
                    JOIN "User" u ON u."userId" = r."userId" WHERE r."predId" = %s""", (predId,), one=True)
    if pred is None:
        abort(404)
    if pred["userId"] != g.user["userId"] and g.user["role"] == "student":
        abort(403)
    return pred


def read_form():
    data = {k: request.form.get(k, "").strip() for k in FIELDS + TASK_FIELDS}
    data["is_publish"] = request.form.get("is_publish") == "on"
    if not data["title"] or not data["statement"]:
        return None
    if data["topic"] not in TOPICS or data["difficulty"] not in DIFFICULTIES:
        return None
    try:
        data["pubLimit"] = max(0, int(request.form.get("pubLimit") or current_app.config["PUB_LIMIT"]))
        data["priLimit"] = max(0, int(request.form.get("priLimit") or current_app.config["PRI_LIMIT"]))
    except ValueError:
        return None
    return data


@bp.route("/tasks", endpoint="list")
@requires_auth()
def list_():
    from .contest import practice_list
    return practice_list("predict")


@bp.route("/tasks/<int:problemId>")
@requires_auth()
def detail(problemId):
    task = get_task(problemId)
    attemptId = request.args.get("attempt", type=int)
    attempt = get_attempt(task, attemptId)
    phase = attempts.currentPhase(attempt) if attempt else None
    files = [d for d in get_datasets(task["taskId"]) if d["role"] in OPEN_ROLES
             and not (d["role"] == "private_test" and phase == "public")]
    phases = open_phases(task, attempt)
    if attempt is not None and attempts.is_expired(attempt):
        phases = []
    left = {p: checkLimit(task, p, attempt) for p in phases}
    history = query("""SELECT * FROM "Prediction" WHERE "taskId" = %s AND "userId" = %s
                       AND "attemptId" IS NOT DISTINCT FROM %s ORDER BY "predId" DESC LIMIT 30""",
                    (task["taskId"], g.user["userId"], attemptId))
    return render_template("task.html", task=task, metrics=scoring.get_metrics(task["taskId"]),
                           files=files, phases=phases, left=left, history=history,
                           attempt=attempt, phase=phase)


@bp.route("/tasks/<int:problemId>/data/<int:dataId>")
@requires_auth()
def download(problemId, dataId):
    task = get_task(problemId)
    attempt = get_attempt(task, request.args.get("attempt", type=int))
    data = query('SELECT * FROM "Dataset" WHERE "dataId" = %s AND "taskId" = %s',
                 (dataId, task["taskId"]), one=True)
    if data is None:
        abort(404)
    if g.user["role"] == "student":
        if data["role"] not in OPEN_ROLES:
            abort(403)
        if data["role"] == "private_test" and attempt and attempts.currentPhase(attempt) == "public":
            abort(403)
    file = storage.full(data["path"])
    if not file.is_file():
        abort(404)
    return send_file(file, as_attachment=True, download_name=data["fileName"])


@bp.route("/tasks/<int:problemId>/submit", methods=["POST"])
@requires_auth()
def submitFile(problemId):
    task = get_task(problemId)
    attemptId = request.form.get("attemptId", type=int)
    attempt = get_attempt(task, attemptId)
    back = url_for("task.detail", problemId=problemId, attempt=attemptId)
    phase = request.form.get("phase", "public")
    file = request.files.get("file")

    if attempt is not None and attempts.is_expired(attempt):
        flash("Lượt thi đã hết giờ, không nhận thêm bài nộp.", "error")
        return redirect(url_for("contest.result", contestId=attempt["contestId"]))
    if phase not in open_phases(task, attempt):
        flash("Giai đoạn này chưa mở hoặc bài chưa có nhãn chấm.", "error")
        return redirect(back)
    if file is None or not file.filename or Path(file.filename).suffix.lower() not in ALLOWED:
        flash("Chọn file kết quả có đuôi .csv, .json, .jsonl hoặc .zip.", "error")
        return redirect(back)
    if checkLimit(task, phase, attempt) <= 0:
        flash("Đã hết lượt nộp cho giai đoạn này.", "error")
        return redirect(back)
    if not checkCooldown(g.user, "predict"):
        flash(f"Chờ {current_app.config['SUBMIT_COOLDOWN_SECONDS']} giây giữa hai lần nộp.", "error")
        return redirect(back)
    path, size = storage.save(file, f"pred/{g.user['userId']}")
    if size == 0 or size > current_app.config["MAX_FILE_BYTES"]:
        storage.remove(path)
        flash("File trống hoặc vượt quá 20 MB.", "error")
        return redirect(back)

    row = execute("""INSERT INTO "Prediction" ("userId", "taskId", "attemptId", phase, "fileName", path)
                     VALUES (%s, %s, %s, %s, %s, %s) RETURNING "predId" """,
                  (g.user["userId"], task["taskId"], attemptId, phase,
                   storage.clean_name(file.filename), path), returning=True)
    commit()
    try:
        enqueue(score, row["predId"])
    except Exception as e:
        execute("""UPDATE "Prediction" SET status = 'system_error', "errMess" = %s WHERE "predId" = %s""",
                (f"Không đưa được vào hàng đợi: {e}"[:500], row["predId"]))
    return redirect(url_for("task.prediction", predId=row["predId"]))


@bp.route("/predictions/<int:predId>")
@requires_auth()
def prediction(predId):
    pred = get_prediction(predId)
    return render_template("prediction.html", pred=pred, metrics=scoring.get_metrics(pred["taskId"]))


@bp.route("/predictions/<int:predId>/status")
@requires_auth()
def status(predId):
    pred = get_prediction(predId)
    return jsonify({"status": pred["status"], "score": pred["score"]})


@bp.route("/tasks/<int:problemId>/board")
@requires_auth()
def board(problemId):
    task = get_task(problemId)
    get_attempt(task, None)
    phase = request.args.get("phase", "public")
    if phase not in PHASES:
        phase = "public"
    rows, metrics = scoring.taskBoard(task["taskId"], phase)
    return render_template("task_board.html", task=task, rows=rows[:current_app.config["BOARD_SIZE"]],
                           metrics=metrics, phase=phase)


@bp.route("/manage/tasks")
@requires_auth("supervisor")
def bank():
    rows = query("""SELECT p.*, t."taskId",
                           (SELECT count(*) FROM "Metric" m WHERE m."taskId" = t."taskId") AS n_metrics,
                           (SELECT count(*) FROM "Dataset" d WHERE d."taskId" = t."taskId") AS n_files,
                           (SELECT count(*) FROM "Prediction" r WHERE r."taskId" = t."taskId") AS n_preds
                    FROM "Problem" p JOIN "Task" t ON t."problemId" = p."problemId"
                    WHERE p.kind = 'predict' ORDER BY p."problemId" DESC""")
    return render_template("task_bank.html", tasks=rows)


@bp.route("/manage/tasks/new", methods=["GET", "POST"])
@requires_auth("supervisor")
def create():
    if request.method == "POST":
        data = read_form()
        if data is None:
            flash("Thiếu tiêu đề, đề bài, chủ đề hoặc độ khó.", "error")
        else:
            row = execute("""INSERT INTO "Problem" (title, statement, topic, difficulty, kind, is_publish, author)
                             VALUES (%s, %s, %s, %s, 'predict', %s, %s) RETURNING "problemId" """,
                          (*[data[k] for k in FIELDS], data["is_publish"], g.user["userId"]), returning=True)
            execute("""INSERT INTO "Task" ("problemId", "dataDesc", "submitFormat", baseline, "pubLimit", "priLimit")
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (row["problemId"], *[data[k] for k in TASK_FIELDS], data["pubLimit"], data["priLimit"]))
            flash("Đã tạo bài, giờ thêm phần điểm và dữ liệu.", "ok")
            return redirect(url_for("task.update", problemId=row["problemId"]))
    return render_template("task_edit.html", task=None, metrics=[], files=[])


@bp.route("/manage/tasks/<int:problemId>/edit", methods=["GET", "POST"])
@requires_auth("supervisor")
def update(problemId):
    task = get_task(problemId)
    if request.method == "POST":
        data = read_form()
        if data is None:
            flash("Thiếu tiêu đề, đề bài, chủ đề hoặc độ khó.", "error")
        else:
            execute("""UPDATE "Problem" SET title=%s, statement=%s, topic=%s, difficulty=%s, is_publish=%s
                       WHERE "problemId"=%s""", (*[data[k] for k in FIELDS], data["is_publish"], problemId))
            execute("""UPDATE "Task" SET "dataDesc"=%s, "submitFormat"=%s, baseline=%s, "pubLimit"=%s,
                       "priLimit"=%s WHERE "problemId"=%s""",
                    (*[data[k] for k in TASK_FIELDS], data["pubLimit"], data["priLimit"], problemId))
            flash("Đã lưu.", "ok")
            return redirect(url_for("task.update", problemId=problemId))
    n_preds = query('SELECT count(*) AS n FROM "Prediction" WHERE "taskId" = %s', (task["taskId"],), one=True)["n"]
    return render_template("task_edit.html", task=task, metrics=scoring.get_metrics(task["taskId"]),
                           files=get_datasets(task["taskId"]), n_preds=n_preds)


@bp.route("/manage/tasks/<int:problemId>/delete", methods=["POST"])
@requires_auth("supervisor")
def delete(problemId):
    task = get_task(problemId)
    used = query("""SELECT EXISTS (SELECT 1 FROM "Prediction" WHERE "taskId" = %s)
                        OR EXISTS (SELECT 1 FROM "ContestItem" WHERE "problemId" = %s) AS used""",
                 (task["taskId"], problemId), one=True)["used"]
    if used:
        flash("Bài đã có bài nộp hoặc nằm trong kỳ thi, không xoá được. Hãy bỏ công khai.", "error")
        return redirect(url_for("task.update", problemId=problemId))
    for d in get_datasets(task["taskId"]):
        storage.remove(d["path"])
    execute('DELETE FROM "Problem" WHERE "problemId" = %s', (problemId,))
    flash("Đã xoá bài.", "ok")
    return redirect(url_for("task.bank"))


@bp.route("/manage/tasks/<int:problemId>/rescore", methods=["POST"])
@requires_auth("supervisor")
def rescore(problemId):
    task = get_task(problemId)
    rows = query("""UPDATE "Prediction" SET status = 'queued', score = NULL, detail = NULL, "errMess" = NULL,
                    judged = NULL WHERE "taskId" = %s RETURNING "predId" """, (task["taskId"],))
    commit()
    failed = 0
    for r in rows:
        try:
            enqueue(score, r["predId"])
        except Exception as e:
            failed += 1
            execute("""UPDATE "Prediction" SET status = 'system_error', "errMess" = %s WHERE "predId" = %s""",
                    (f"Không đưa được vào hàng đợi: {e}"[:500], r["predId"]))
    flash(f"Đã đưa {len(rows) - failed}/{len(rows)} bài nộp vào hàng đợi chấm lại.", "ok" if not failed else "error")
    return redirect(url_for("task.update", problemId=problemId))


@bp.route("/manage/tasks/<int:problemId>/metrics", methods=["POST"])
@requires_auth("supervisor")
def addMetric(problemId):
    task = get_task(problemId)
    info = request.form
    back = redirect(url_for("task.update", problemId=problemId))
    try:
        config = json.loads(info.get("config") or "{}")
        weight = float(info.get("weight") or 1)
        minScore = float(info.get("minScore") or 0)
        maxScore = float(info["maxScore"]) if info.get("maxScore") else None
    except ValueError:
        flash("Trọng số, điểm và cấu hình JSON phải đúng định dạng.", "error")
        return back
    fileName = storage.clean_name(info.get("fileName", ""))
    if info.get("metric") not in METRICS or not info.get("name") or not isinstance(config, dict) \
            or weight < 0 or Path(fileName).suffix.lower() not in scoring.TYPES:
        flash("Cần tên phần điểm, độ đo, tệp kết quả (.csv, .json, .jsonl) và trọng số không âm.", "error")
        return back
    execute("""INSERT INTO "Metric" ("taskId", name, metric, "fileName", config, weight, "minScore", "maxScore", position)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                       (SELECT COALESCE(max(m.position), -1) + 1 FROM "Metric" m WHERE m."taskId" = %s))""",
            (task["taskId"], info["name"].strip()[:100], info["metric"], fileName, Jsonb(config),
             weight, minScore, maxScore, task["taskId"]))
    return back


@bp.route("/manage/tasks/<int:problemId>/metrics/<int:id>/delete", methods=["POST"])
@requires_auth("supervisor")
def deleteMetric(problemId, id):
    task = get_task(problemId)
    execute('DELETE FROM "Metric" WHERE "metricId" = %s AND "taskId" = %s', (id, task["taskId"]))
    return redirect(url_for("task.update", problemId=problemId))


@bp.route("/manage/tasks/<int:problemId>/datasets", methods=["POST"])
@requires_auth("supervisor")
def addDataset(problemId):
    task = get_task(problemId)
    role = request.form.get("role")
    file = request.files.get("file")
    if role not in DATA_ROLES or file is None or not file.filename:
        flash("Chọn loại tệp và tệp dữ liệu.", "error")
    else:
        path, size = storage.save(file, f"data/{task['taskId']}")
        execute('INSERT INTO "Dataset" ("taskId", role, "fileName", path, size) VALUES (%s, %s, %s, %s, %s)',
                (task["taskId"], role, storage.clean_name(file.filename), path, size))
        flash("Đã tải tệp lên.", "ok")
    return redirect(url_for("task.update", problemId=problemId))


@bp.route("/manage/tasks/<int:problemId>/datasets/<int:id>/delete", methods=["POST"])
@requires_auth("supervisor")
def deleteDataset(problemId, id):
    task = get_task(problemId)
    row = execute('DELETE FROM "Dataset" WHERE "dataId" = %s AND "taskId" = %s RETURNING path',
                  (id, task["taskId"]), returning=True)
    if row:
        storage.remove(row["path"])
    return redirect(url_for("task.update", problemId=problemId))
