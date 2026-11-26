from functools import wraps

_app = None


def in_app_context(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        global _app
        if _app is None:
            from app import create_app
            _app = create_app()
        with _app.app_context():
            return func(*args, **kwargs)
    return wrapper


STUCK_MINUTES = 10


def reset_stuck():
    from ..db import commit, execute
    note = "Tiến trình chấm dừng giữa chừng, hãy nộp lại."
    execute(f"""UPDATE "Submission" SET status = 'system_error', "errMess" = %s, judged = now()
                WHERE status = 'judging' AND created < now() - interval '{STUCK_MINUTES} minutes'""", (note,))
    execute(f"""UPDATE "Prediction" SET status = 'system_error', "errMess" = %s, judged = now()
                WHERE status = 'scoring' AND created < now() - interval '{STUCK_MINUTES} minutes'""", (note,))
    execute(f"""UPDATE "Draft" SET status = 'failed', "errMess" = %s
                WHERE status = 'validating' AND created < now() - interval '{STUCK_MINUTES} minutes'""",
            ("Tiến trình tạo đề dừng giữa chừng.",))
    commit()
