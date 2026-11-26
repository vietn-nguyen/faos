from ..db import commit, execute, query, rollback
from . import attempt as attempts
from . import judge0
from .jobs import in_app_context


def overallVerdict(verdicts):
    for v in verdicts:
        if v != "AC":
            return v
    return "AC"


def set_error(submissionId, errMess):
    execute("""UPDATE "Submission" SET status = 'system_error', "errMess" = %s, judged = now()
               WHERE "submissionId" = %s""", (errMess[:500], submissionId))


@in_app_context
def grade(submissionId):
    try:
        run_grade(submissionId)
    except Exception as e:
        rollback()
        set_error(submissionId, f"Lỗi khi chấm: {e}")
        commit()


def run_grade(submissionId):
    sub = query('SELECT * FROM "Submission" WHERE "submissionId" = %s', (submissionId,), one=True)
    if sub is None:
        return
    problem = query('SELECT * FROM "Problem" WHERE "problemId" = %s', (sub["problemId"],), one=True)
    tests = query("""SELECT * FROM "TestCase" t WHERE t."problemId" = %s
                     ORDER BY t.sample DESC, t.position, t."TestCaseId" """, (sub["problemId"],))
    if not tests:
        set_error(submissionId, "Bài toán chưa có test case.")
        return
    execute("""UPDATE "Submission" SET status = 'judging', total = %s WHERE "submissionId" = %s""",
            (len(tests), submissionId))
    commit()

    try:
        results = judge0.runBatch(sub["sourceCode"], [t["input"] for t in tests],
                                  problem["timeLimit"], problem["memoryLimit"])
    except Exception as e:
        execute("""UPDATE "Submission" SET status = 'system_error', "errMess" = %s, judged = now()
                   WHERE "submissionId" = %s""", (str(e)[:500], submissionId))
        return

    verdicts = []
    failed = 0
    execute('DELETE FROM "SubmissionResult" WHERE "submissionId" = %s', (submissionId,))
    for test, res in zip(tests, results):
        verdict = judge0.get_verdict(res, test["output"])
        if verdict is None:
            failed += 1
            continue
        verdicts.append(verdict)
        execute("""INSERT INTO "SubmissionResult"
                   ("submissionId", "TestCaseId", verdict, time, memory, stdout, stderr, judge0_token)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (submissionId, test["TestCaseId"], verdict, res["time"], res["memory"],
                 (res["stdout"] or "")[:2000], res["stderr"], res["token"]))

    if failed:
        execute("""UPDATE "Submission" SET status = 'system_error', passed = %s, judged = now(),
                   "errMess" = %s WHERE "submissionId" = %s""",
                (verdicts.count("AC"), f"judge0 không xử lý được {failed}/{len(tests)} test", submissionId))
        return
    execute("""UPDATE "Submission" SET status = 'done', verdict = %s, passed = %s, judged = now()
               WHERE "submissionId" = %s""",
            (overallVerdict(verdicts), verdicts.count("AC"), submissionId))
    commit()

    if sub["attemptId"]:
        attempts.recompute(sub["attemptId"])
