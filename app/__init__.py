from dotenv import load_dotenv
from flask import Flask, g, render_template, request

load_dotenv()


def create_app():
    from . import codecontests, contest, db, draft, problem, question, quiz, seed, submission, task, user
    from .config import Config
    from .db import query
    from .labels import register_filters

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    seed.init_app(app)
    codecontests.init_app(app)
    user.init_app(app)

    app.register_blueprint(user.bp)
    app.register_blueprint(problem.bp)
    app.register_blueprint(question.bp)
    app.register_blueprint(submission.bp)
    app.register_blueprint(contest.bp)
    app.register_blueprint(draft.bp)
    app.register_blueprint(task.bp)
    app.register_blueprint(quiz.bp)

    @app.route("/")
    def index():
        counts = query("""SELECT (SELECT count(*) FROM "Problem" WHERE is_publish AND kind = 'code') AS problems,
                                 (SELECT count(*) FROM "Problem" WHERE is_publish AND kind = 'predict') AS tasks,
                                 (SELECT count(*) FROM "Question") AS questions,
                                 (SELECT count(*) FROM "Contest") AS contests,
                                 (SELECT count(*) FROM "User" WHERE role = 'student') AS students""", one=True)
        contests = query("""SELECT c.*, now() AS server_now FROM "Contest" c
                            WHERE c.close > now() ORDER BY c.open LIMIT 5""")
        return render_template("home.html", counts=counts, contests=contests)

    @app.route("/practice")
    @user.requires_auth()
    def practice():
        return contest.practice_list("mix" if request.args.get("section") == "mix" else "all")

    @app.route("/leaderboard")
    @user.requires_auth()
    def ranking():
        from .services import leaderboard
        boards = {}
        for kind in ("practice", "exam"):
            rows = leaderboard.overall(kind)
            mine = next((dict(r, rank=n + 1) for n, r in enumerate(rows) if r["userId"] == g.user["userId"]), None)
            boards[kind] = {"top": rows[:10], "mine": mine, "count": len(rows)}
        return render_template("ranking.html", boards=boards)

    register_filters(app)
    return app
