from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import urlparse

import jwt
from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

from .db import execute, query
from .labels import ROLES

bp = Blueprint("user", __name__)
COOKIE = "access_token"


def make_token(user):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user["userId"]),
        "role": user["role"],
        "iat": now,
        "exp": now + timedelta(hours=current_app.config["JWT_HOURS"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def load_user():
    g.user = None
    token = request.cookies.get(COOKIE)
    if not token:
        return
    try:
        payload = jwt.decode(token, current_app.config["SECRET_KEY"], algorithms=["HS256"])
    except jwt.InvalidTokenError:
        return
    user = query("""SELECT "userId", "userEmail", username, role, is_active, created
                    FROM "User" WHERE "userId" = %s""", (int(payload["sub"]),), one=True)
    if user and user["is_active"]:
        g.user = user


def requires_auth(*roles):
    def wrapper(view):
        @wraps(view)
        def inner(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("user.login", next=request.path))
            if roles and g.user["role"] not in roles and g.user["role"] != "admin":
                abort(403)
            return view(*args, **kwargs)
        return inner
    return wrapper


def check_register(email, name, password):
    if not email or "@" not in email or not name or len(password) < 6:
        return "Nhập đủ email, tên đăng nhập và mật khẩu từ 6 ký tự."
    if query('SELECT 1 FROM "User" WHERE "userEmail" = %s', (email,), one=True):
        return "Email đã được đăng ký."
    if query('SELECT 1 FROM "User" WHERE username = %s', (name,), one=True):
        return "Tên đăng nhập đã tồn tại."
    return None


@bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        name = request.form.get("name", "").strip()
        password = request.form.get("password", "")
        error = check_register(email, name, password)
        if error:
            flash(error, "error")
        else:
            execute('INSERT INTO "User" ("userEmail", username, "userPass") VALUES (%s, %s, %s)',
                    (email, name, generate_password_hash(password)))
            flash("Đăng ký thành công, mời đăng nhập.", "ok")
            return redirect(url_for("user.login"))
    return render_template("register.html")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user = query('SELECT * FROM "User" WHERE username = %s', (username,), one=True)
        if not user or not check_password_hash(user["userPass"], request.form.get("password", "")):
            flash("Sai tên đăng nhập hoặc mật khẩu.", "error")
        elif not user["is_active"]:
            flash("Tài khoản đã bị khoá.", "error")
        else:
            target = request.args.get("next") or ""
            if not target.startswith("/") or target.startswith("//") or "\\" in target:
                target = url_for({"admin": "user.dashboard", "supervisor": "problem.bank"}.get(user["role"], "practice"))
            resp = redirect(target)
            resp.set_cookie(COOKIE, make_token(user), httponly=True, samesite="Lax",
                            max_age=current_app.config["JWT_HOURS"] * 3600)
            return resp
    return render_template("login.html")


@bp.route("/logout")
def logout():
    resp = redirect(url_for("index"))
    resp.delete_cookie(COOKIE)
    return resp


@bp.route("/profile")
@requires_auth()
def viewProfile():
    stats = query("""SELECT count(*) AS total,
                            count(*) FILTER (WHERE verdict = 'AC') AS accepted,
                            count(DISTINCT "problemId") FILTER (WHERE verdict = 'AC') AS solved
                     FROM "Submission" WHERE "userId" = %s""", (g.user["userId"],), one=True)
    ai = query("""SELECT (SELECT count(*) FROM "PracticeAnswer" WHERE "userId" = %s) AS answered,
                         (SELECT count(*) FROM "PracticeAnswer" WHERE "userId" = %s AND is_correct) AS correct,
                         (SELECT count(*) FROM "Prediction" WHERE "userId" = %s) AS preds,
                         (SELECT count(DISTINCT "taskId") FROM "Prediction"
                          WHERE "userId" = %s AND status = 'done') AS tasks""",
               (g.user["userId"],) * 4, one=True)
    attempts = query("""SELECT c."contestId", c.title, c.kind, a.start, a.finished, a."totalScore", a.duration
                        FROM "ContestAttempt" a JOIN "Contest" c ON c."contestId" = a."contestId"
                        WHERE a."userId" = %s ORDER BY a."attemptId" DESC""", (g.user["userId"],))
    from .services import leaderboard
    totals = {}
    for kind in ("practice", "exam"):
        rows = leaderboard.overall(kind)
        mine = next((dict(r, rank=n + 1) for n, r in enumerate(rows) if r["userId"] == g.user["userId"]), None)
        totals[kind] = {"total": mine["total"] if mine else 0, "n": mine["n"] if mine else 0,
                        "rank": mine["rank"] if mine else None, "count": len(rows)}
    return render_template("profile.html", stats=stats, attempts=attempts, ai=ai, totals=totals)


@bp.route("/manage/users")
@requires_auth("admin")
def users():
    rows = query('SELECT "userId", "userEmail", username, role, is_active, created FROM "User" ORDER BY "userId"')
    return render_template("users.html", users=rows, roles=ROLES)


@bp.route("/manage/users/create", methods=["POST"])
@requires_auth("admin")
def createByAdmin():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    email = request.form.get("email", "").strip().lower()
    role = request.form.get("role", "student")
    error = check_register(email, username, password)
    if role not in ROLES:
        error = "Vai trò không hợp lệ."
    if error:
        flash(error, "error")
    else:
        execute('INSERT INTO "User" ("userEmail", username, "userPass", role) VALUES (%s, %s, %s, %s)',
                (email, username, generate_password_hash(password), role))
        flash("Đã tạo tài khoản.", "ok")
    return redirect(url_for("user.users"))


@bp.route("/manage/users/<int:userId>/toggle", methods=["POST"])
@requires_auth("admin")
def toggleActive(userId):
    if userId != g.user["userId"]:
        execute('UPDATE "User" SET is_active = NOT is_active WHERE "userId" = %s', (userId,))
    return redirect(url_for("user.users"))


@bp.route("/manage/users/<int:userId>/role", methods=["POST"])
@requires_auth("admin")
def changeRole(userId):
    role = request.form.get("role")
    if userId != g.user["userId"] and role in ROLES:
        execute('UPDATE "User" SET role = %s WHERE "userId" = %s', (role, userId))
    return redirect(url_for("user.users"))


FAIL_TYPES = (("Gọi LLM API lỗi", "Lỗi LLM"), ("Trùng", "Trùng"), ("Mọi câu hỏi đều trùng", "Trùng"),
              ("Judge0", "Lỗi Judge0"), ("Lời giải", "Lời giải sai"), ("Output ví dụ", "Lời giải sai"),
              ("Câu hỏi", "Câu hỏi sai cấu trúc"), ("Cần ít nhất", "Thiếu nội dung"))


def fail_type(errMess):
    for prefix, name in FAIL_TYPES:
        if (errMess or "").startswith(prefix):
            return name
    return "Dữ liệu học máy nâng cao" if errMess else "Khác"


def gen_benchmark():
    rows = query("""SELECT kind, status, "errMess", output, COALESCE("inputT", 0) + COALESCE("outputT", 0) AS tokens,
                           context->>'updated' AS version FROM "Draft" ORDER BY kind, version""")
    groups = {}
    for r in rows:
        grp = groups.setdefault((r["kind"], r["version"]), {"kind": r["kind"], "version": r["version"], "total": 0,
                                                          "approved": 0, "rejected": 0, "failed": {}, "dropped": 0,
                                                          "tokens": 0})
        grp["total"] += 1
        grp["tokens"] += r["tokens"]
        if r["status"] in ("approved", "rejected"):
            grp[r["status"]] += 1
        if r["status"] == "failed":
            name = fail_type(r["errMess"])
            grp["failed"][name] = grp["failed"].get(name, 0) + 1
        if r["kind"] == "question" and r["output"]:
            grp["dropped"] += len(r["output"].get("dropped") or [])
    for grp in groups.values():
        grp["dropped"] += grp["failed"].get("Trùng", 0)
        done = grp["approved"] + grp["rejected"]
        grp["rate"] = round(100 * grp["approved"] / done, 1) if done else None
        grp["per_item"] = round(grp["tokens"] / grp["approved"]) if grp["approved"] else None
    return list(groups.values())


@bp.route("/manage/dashboard")
@requires_auth("admin")
def dashboard():
    counts = query("""SELECT (SELECT count(*) FROM "User") AS users,
                             (SELECT count(*) FROM "Problem" WHERE kind = 'code') AS problems,
                             (SELECT count(*) FROM "Problem" WHERE kind = 'predict') AS tasks,
                             (SELECT count(*) FROM "Prediction") AS predictions,
                             (SELECT count(*) FROM "PracticeAnswer") AS practice,
                             (SELECT count(*) FROM "Question") AS questions,
                             (SELECT count(*) FROM "Contest") AS contests,
                             (SELECT count(*) FROM "Submission") AS submissions,
                             (SELECT count(*) FROM "Draft") AS drafts""", one=True)
    verdicts = query("""SELECT COALESCE(verdict, status) AS v, count(*) AS n FROM "Submission"
                        GROUP BY 1 ORDER BY n DESC""")
    by_status = query('SELECT status, count(*) AS n FROM "Draft" GROUP BY status ORDER BY status')
    by_reason = query("""SELECT reason, count(*) AS n FROM "Review" WHERE decision = 'rejected'
                         GROUP BY reason ORDER BY n DESC""")
    by_kind = query('SELECT kind, count(*) AS n FROM "Draft" GROUP BY kind ORDER BY kind')
    by_topic = query("""SELECT topic, count(*) AS total,
                               count(*) FILTER (WHERE status = 'approved') AS approved,
                               count(*) FILTER (WHERE status = 'rejected') AS rejected,
                               count(*) FILTER (WHERE status = 'failed') AS failed
                        FROM "Draft" GROUP BY topic ORDER BY topic""")
    tokens = query("""SELECT COALESCE(sum("inputT"), 0) AS inp, COALESCE(sum("outputT"), 0) AS outp
                      FROM "Draft" """, one=True)
    approved = sum(r["approved"] for r in by_topic)
    done = approved + sum(r["rejected"] for r in by_topic)
    rate = round(100 * approved / done, 1) if done else None
    return render_template("dashboard.html", counts=counts, verdicts=verdicts, by_status=by_status,
                           by_reason=by_reason, by_topic=by_topic, by_kind=by_kind, tokens=tokens, rate=rate,
                           bench=gen_benchmark())


def check_origin():
    if request.method != "POST":
        return
    src = request.headers.get("Origin") or request.headers.get("Referer")
    if src and urlparse(src).netloc != request.host:
        abort(403)


def init_app(app):
    app.before_request(check_origin)
    app.before_request(load_user)
