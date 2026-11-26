from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .db import commit, execute, query
from psycopg.types.json import Jsonb

from .labels import DIFFICULTIES, DRAFT_STATUSES, KEYS, KINDS, REJECT_REASONS, STANDARD_FIELDS, TOPICS
from .queue import enqueue
from .services import standard, storage
from .services.generation import all_inputs, generate, split, to_csv
from .user import requires_auth

bp = Blueprint("draft", __name__, url_prefix="/manage/drafts")

EDITED = ("title", "statement", "input", "output", "constraints")


def get_pending(draftId):
    draft = query('SELECT * FROM "Draft" WHERE "draftId" = %s', (draftId,), one=True)
    if draft is None:
        abort(404)
    if draft["status"] != "pending_review":
        flash("Bản nháp này không ở trạng thái chờ duyệt.", "error")
        return None
    return draft


def claim(draftId, status):
    row = execute("""UPDATE "Draft" SET status = %s WHERE "draftId" = %s AND status = 'pending_review'
                     RETURNING "draftId" """, (status, draftId), returning=True)
    if row is None:
        flash("Bản nháp này đã được xử lý.", "error")
    return row is not None


@bp.route("", endpoint="list")
@requires_auth("supervisor")
def list_():
    status = request.args.get("status", "")
    sql = 'SELECT * FROM "Draft"'
    params = ()
    if status in DRAFT_STATUSES:
        sql += " WHERE status = %s"
        params = (status,)
    rows = query(sql + ' ORDER BY "draftId" DESC LIMIT 100', params)
    busy = any(r["status"] in ("generating", "validating") for r in rows)
    return render_template("drafts.html", drafts=rows, status=status, busy=busy)


@bp.route("/request", methods=["POST"], endpoint="request")
@requires_auth("supervisor")
def request_():
    kind = request.form.get("kind", "code")
    topic = request.form.get("topic")
    difficulty = request.form.get("difficulty")
    count = max(1, min(request.form.get("count", 1, type=int) or 1, 5))
    if kind not in KINDS or topic not in TOPICS or difficulty not in DIFFICULTIES:
        flash("Chọn chủ đề và độ khó.", "error")
        return redirect(url_for("draft.list"))
    for _ in range(count):
        row = execute("""INSERT INTO "Draft" (kind, topic, difficulty, requested_by)
                         VALUES (%s, %s, %s, %s) RETURNING "draftId" """,
                      (kind, topic, difficulty, g.user["userId"]), returning=True)
        commit()
        try:
            enqueue(generate, row["draftId"])
        except Exception as e:
            execute("""UPDATE "Draft" SET status = 'failed', "errMess" = %s WHERE "draftId" = %s""",
                    (f"Không đưa được vào hàng đợi: {e}"[:1000], row["draftId"]))
    flash(f"Đã gửi {count} yêu cầu tạo đề. Trang sẽ tự cập nhật.", "ok")
    return redirect(url_for("draft.list"))


@bp.route("/standards")
@requires_auth("supervisor")
def standards():
    rows = [standard.get(kind) for kind in KINDS]
    models = query("""SELECT kind, count(*) AS n FROM "Problem" WHERE is_model GROUP BY kind""")
    counts = {r["kind"]: r["n"] for r in models}
    counts["question"] = query('SELECT count(*) AS n FROM "Question" WHERE is_model', one=True)["n"]
    return render_template("standards.html", standards=rows, counts=counts, fields=STANDARD_FIELDS,
                           max_examples=standard.MAX_EXAMPLES)


@bp.route("/standards/<kind>", methods=["POST"])
@requires_auth("supervisor")
def saveStandard(kind):
    if kind not in KINDS:
        abort(404)
    if request.form.get("reset") == "1":
        standard.reset(kind, g.user["userId"])
        flash(f"Đã khôi phục tiêu chuẩn mặc định cho {KINDS[kind].lower()}.", "ok")
        return redirect(url_for("draft.standards"))
    rules = request.form.get("rules", "").strip()
    try:
        examples = int(request.form.get("examples", ""))
        config = {k: int(request.form.get(k, "")) for k in STANDARD_FIELDS[kind]}
    except ValueError:
        flash("Các ngưỡng phải là số nguyên.", "error")
        return redirect(url_for("draft.standards"))
    if not rules or not 0 <= examples <= standard.MAX_EXAMPLES or min(config.values()) < 0 or not 1 <= config["dup"] <= 100:
        flash("Quy tắc không được trống, số đề mẫu từ 0 đến 5, ngưỡng trùng từ 1 đến 100.", "error")
        return redirect(url_for("draft.standards"))
    standard.save(kind, rules, examples, config, g.user["userId"])
    flash(f"Đã lưu tiêu chuẩn cho {KINDS[kind].lower()}. Áp dụng từ yêu cầu tạo đề tiếp theo.", "ok")
    return redirect(url_for("draft.standards"))


@bp.route("/<int:draftId>")
@requires_auth("supervisor")
def detail(draftId):
    draft = query('SELECT * FROM "Draft" WHERE "draftId" = %s', (draftId,), one=True)
    if draft is None:
        abort(404)
    review = query("""SELECT r.*, u.username FROM "Review" r JOIN "User" u ON u."userId" = r."reviewerId"
                      WHERE r."draftId" = %s""", (draftId,), one=True)
    tests = []
    if draft["payload"] and draft["kind"] == "code":
        inputs = all_inputs(draft["payload"])
        outputs = draft["output"] or [None] * len(inputs)
        n_samples = len(draft["payload"]["samples"])
        tests = [{"input": i, "output": o, "sample": n < n_samples}
                 for n, (i, o) in enumerate(zip(inputs, outputs))]
    parts = split(draft["payload"]) if draft["payload"] and draft["kind"] == "predict" else None
    return render_template("draft_detail.html", draft=draft, tests=tests, review=review, parts=parts)


def approveCode(draft):
    payload = draft["payload"]
    edited = {k: request.form.get(k, "").strip() or payload[k] for k in EDITED}
    problem = execute("""INSERT INTO "Problem" (title, statement, input, output, constraints,
                         topic, difficulty, source, author)
                         VALUES (%s, %s, %s, %s, %s, %s, %s, 'llm', %s) RETURNING "problemId" """,
                      (*[edited[k] for k in EDITED], draft["topic"], draft["difficulty"],
                       g.user["userId"]), returning=True)
    n_samples = len(payload["samples"])
    for position, (stdin, out) in enumerate(zip(all_inputs(payload), draft["output"])):
        execute('INSERT INTO "TestCase" ("problemId", input, output, sample, position) VALUES (%s, %s, %s, %s, %s)',
                (problem["problemId"], stdin, out, position < n_samples, position))
    return problem["problemId"]


Q_EDITED = ("content", "code", "op1", "op2", "op3", "op4", "explain")


def edited_questions(draft):
    kept = []
    for i, q in enumerate(draft["payload"]["questions"]):
        if request.form.get(f"keep_{i}") != "on":
            continue
        q = {**q, **{k: request.form.get(f"{k}_{i}", q[k]) for k in Q_EDITED}}
        q = {k: (v.strip("\n") if k == "code" else v.strip()) if isinstance(v, str) else v for k, v in q.items()}
        key = request.form.get(f"key_{i}", q["key"])
        q["key"] = key if key in KEYS else q["key"]
        if not q["content"] or not all(q[f"op{n}"] for n in range(1, 5)):
            return None, f"Câu {i + 1} thiếu nội dung hoặc đáp án."
        kept.append(q)
    if not kept:
        return None, "Chọn ít nhất một câu để đưa vào ngân hàng, hoặc từ chối bản nháp."
    return kept, None


def approveQuestions(draft, kept):
    for q in kept:
        execute("""INSERT INTO "Question" (content, op1, op2, op3, op4, key, topic, difficulty, code, explain, author)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (q["content"], q["op1"], q["op2"], q["op3"], q["op4"], q["key"], draft["topic"],
                 draft["difficulty"], q["code"], q["explain"], g.user["userId"]))
    return None


def approveTask(draft):
    payload = draft["payload"]
    title = request.form.get("title", "").strip() or payload["title"]
    statement = request.form.get("statement", "").strip() or payload["statement"]
    data_desc = request.form.get("data_desc", "").strip() or payload["data_desc"]
    submit_format = request.form.get("submit_format", "").strip() or payload["submit_format"]
    problem = execute("""INSERT INTO "Problem" (title, statement, topic, difficulty, kind, source, author)
                         VALUES (%s, %s, %s, %s, 'predict', 'llm', %s) RETURNING "problemId" """,
                      (title, statement, draft["topic"], draft["difficulty"], g.user["userId"]), returning=True)
    task = execute("""INSERT INTO "Task" ("problemId", "dataDesc", "submitFormat", baseline, "pubLimit", "priLimit")
                      VALUES (%s, %s, %s, %s, %s, %s) RETURNING "taskId" """,
                   (problem["problemId"], data_desc, submit_format, payload["baseline"],
                    current_app.config["PUB_LIMIT"], current_app.config["PRI_LIMIT"]), returning=True)
    cols, id_col, label = payload["columns"], payload["id_col"], payload["label_col"]
    config = {"id": id_col, "label": label}
    execute("""INSERT INTO "Metric" ("taskId", name, metric, "fileName", config, "minScore")
               VALUES (%s, %s, %s, 'submission.csv', %s, %s)""",
            (task["taskId"], "Điểm phân loại", payload["metric"], Jsonb(config), draft["output"]["public"]))
    parts = split(payload)
    hidden = [c for c in cols if c != label]
    files = [("train", "train.csv", to_csv(parts["train"], cols)),
             ("public_test", "public_test.csv", to_csv(parts["public"], hidden)),
             ("private_test", "private_test.csv", to_csv(parts["private"], hidden)),
             ("public_key", "submission.csv", to_csv(parts["public"], [id_col, label])),
             ("private_key", "submission.csv", to_csv(parts["private"], [id_col, label]))]
    for role, name, text in files:
        path, size = storage.write(text, f"data/{task['taskId']}", name)
        execute('INSERT INTO "Dataset" ("taskId", role, "fileName", path, size) VALUES (%s, %s, %s, %s, %s)',
                (task["taskId"], role, name, path, size))
    return problem["problemId"]


@bp.route("/<int:draftId>/approve", methods=["POST"])
@requires_auth("supervisor")
def approve(draftId):
    draft = get_pending(draftId)
    if draft is None:
        return redirect(url_for("draft.detail", draftId=draftId))
    kept = None
    if draft["kind"] == "question":
        kept, error = edited_questions(draft)
        if error:
            flash(error, "error")
            return redirect(url_for("draft.detail", draftId=draftId))
    if not claim(draftId, "approved"):
        return redirect(url_for("draft.detail", draftId=draftId))
    if draft["kind"] == "question":
        problemId = approveQuestions(draft, kept)
    elif draft["kind"] == "predict":
        problemId = approveTask(draft)
    else:
        problemId = approveCode(draft)
    execute('UPDATE "Draft" SET "problemId" = %s WHERE "draftId" = %s', (problemId, draftId))
    execute("""INSERT INTO "Review" ("draftId", "reviewerId", decision, note) VALUES (%s, %s, 'approved', %s)""",
            (draftId, g.user["userId"], request.form.get("note", "")))
    flash("Đã duyệt, đề đã vào ngân hàng đề.", "ok")
    return redirect(url_for("draft.list"))


@bp.route("/<int:draftId>/reject", methods=["POST"])
@requires_auth("supervisor")
def reject(draftId):
    draft = get_pending(draftId)
    reason = request.form.get("reason")
    if draft is None:
        return redirect(url_for("draft.detail", draftId=draftId))
    if reason not in REJECT_REASONS:
        flash("Chọn lý do từ chối.", "error")
        return redirect(url_for("draft.detail", draftId=draftId))
    if not claim(draftId, "rejected"):
        return redirect(url_for("draft.detail", draftId=draftId))
    execute("""INSERT INTO "Review" ("draftId", "reviewerId", decision, reason, note) VALUES (%s, %s, 'rejected', %s, %s)""",
            (draftId, g.user["userId"], reason, request.form.get("note", "")))
    flash("Đã từ chối bản nháp.", "ok")
    return redirect(url_for("draft.list"))
