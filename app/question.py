import csv
import io
import json
from pathlib import Path

from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_file, url_for

from .db import execute, query
from .labels import DIFFICULTIES, KEYS, TOPICS
from .services import attempt as attempts
from .services import storage
from .user import requires_auth

bp = Blueprint("question", __name__, url_prefix="/manage/questions")

FIELDS = ("content", "op1", "op2", "op3", "op4", "key", "topic", "difficulty", "code", "explain")
IMAGES = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def check(data):
    data = {k: str(data.get(k) or "").strip("\n") if k == "code" else str(data.get(k) or "").strip()
            for k in FIELDS}
    data["key"] = data["key"].upper()
    data["difficulty"] = data["difficulty"] or "easy"
    if not all(data[k] for k in ("content", "op1", "op2", "op3", "op4")):
        return None
    if data["key"] not in KEYS or data["topic"] not in TOPICS or data["difficulty"] not in DIFFICULTIES:
        return None
    return data


def save_image():
    file = request.files.get("image")
    if file is None or not file.filename or Path(file.filename).suffix.lower() not in IMAGES:
        return None
    return storage.save(file, "img")[0]


def insert(data, image=None):
    execute("""INSERT INTO "Question" (content, op1, op2, op3, op4, key, topic, difficulty, code, explain,
               image, author) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (*[data[k] for k in FIELDS], image, g.user["userId"]))


@bp.route("")
@requires_auth("supervisor")
def bank():
    topic = request.args.get("topic", "")
    sql = 'SELECT * FROM "Question"'
    params = ()
    if topic in TOPICS:
        sql += " WHERE topic = %s"
        params = (topic,)
    rows = query(sql + ' ORDER BY "questionId" DESC', params)
    editing = query('SELECT * FROM "Question" WHERE "questionId" = %s',
                    (request.args.get("edit", type=int),), one=True)
    return render_template("question_bank.html", questions=rows, editing=editing, topic=topic)


@bp.route("/create", methods=["POST"])
@requires_auth("supervisor")
def create():
    data = check(request.form)
    if data is None:
        flash("Nhập đủ nội dung, 4 đáp án, đáp án đúng và chủ đề.", "error")
    else:
        insert(data, save_image())
        flash("Đã thêm câu hỏi.", "ok")
    return redirect(url_for("question.bank"))


@bp.route("/<int:questionId>/update", methods=["POST"])
@requires_auth("supervisor")
def update(questionId):
    data = check(request.form)
    if data is None:
        flash("Nhập đủ nội dung, 4 đáp án, đáp án đúng và chủ đề.", "error")
        return redirect(url_for("question.bank", edit=questionId))
    execute("""UPDATE "Question" SET content=%s, op1=%s, op2=%s, op3=%s, op4=%s, key=%s,
               topic=%s, difficulty=%s, code=%s, explain=%s WHERE "questionId"=%s""",
            (*[data[k] for k in FIELDS], questionId))
    image = save_image()
    if image or request.form.get("drop_image") == "on":
        old = query('SELECT image FROM "Question" WHERE "questionId" = %s', (questionId,), one=True)
        if old and old["image"]:
            storage.remove(old["image"])
        execute('UPDATE "Question" SET image = %s WHERE "questionId" = %s', (image, questionId))
    flash("Đã lưu câu hỏi.", "ok")
    return redirect(url_for("question.bank"))


@bp.route("/import", methods=["POST"])
@requires_auth("supervisor")
def importFile():
    file = request.files.get("file")
    try:
        text = file.read().decode("utf-8-sig")
        if Path(file.filename).suffix.lower() == ".json":
            rows = json.loads(text)
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
        good = [d for d in (check(r) for r in rows if isinstance(r, dict)) if d]
    except Exception:
        flash("Không đọc được tệp. Cần tệp .json hoặc .csv mã hoá UTF-8.", "error")
        return redirect(url_for("question.bank"))
    for data in good:
        insert(data)
    flash(f"Đã nhập {len(good)}/{len(rows)} câu hỏi.", "ok" if good else "error")
    return redirect(url_for("question.bank"))


@bp.route("/<int:questionId>/image")
@requires_auth()
def image(questionId):
    row = query('SELECT image FROM "Question" WHERE "questionId" = %s', (questionId,), one=True)
    if row is None or not row["image"] or not storage.full(row["image"]).is_file():
        abort(404)
    if g.user["role"] == "student" and not attempts.has_attempt_with(g.user["userId"], questionId):
        abort(404)
    return send_file(storage.full(row["image"]))


@bp.route("/<int:questionId>/model", methods=["POST"])
@requires_auth("supervisor")
def setModel(questionId):
    row = execute("""UPDATE "Question" SET is_model = NOT is_model WHERE "questionId" = %s RETURNING is_model""",
                  (questionId,), returning=True)
    if row is None:
        abort(404)
    flash("Đã đánh dấu là câu hỏi mẫu cho việc tạo đề." if row["is_model"] else "Đã bỏ đánh dấu câu hỏi mẫu.", "ok")
    return redirect(url_for("question.bank", topic=request.form.get("topic", "")))


@bp.route("/<int:questionId>/delete", methods=["POST"])
@requires_auth("supervisor")
def delete(questionId):
    used = query("""SELECT EXISTS (SELECT 1 FROM "ContestItem" WHERE "questionId" = %s)
                        OR EXISTS (SELECT 1 FROM "AttemptAnswer" WHERE "questionId" = %s) AS used""",
                 (questionId, questionId), one=True)["used"]
    if used:
        flash("Câu hỏi đang dùng trong kỳ thi, không xoá được.", "error")
    else:
        execute('DELETE FROM "Question" WHERE "questionId" = %s', (questionId,))
        flash("Đã xoá câu hỏi.", "ok")
    return redirect(url_for("question.bank"))
