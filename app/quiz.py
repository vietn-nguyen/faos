from flask import Blueprint

from .db import execute, query
from .user import requires_auth

bp = Blueprint("quiz", __name__, url_prefix="/quiz")


def statByTopic(userId):
    return query("""SELECT q.topic, count(DISTINCT q."questionId") AS total,
                           count(pa."practiceAId") AS answered,
                           count(pa."practiceAId") FILTER (WHERE pa.is_correct) AS correct
                    FROM "Question" q
                    JOIN "PracticeAnswer" pa ON pa."questionId" = q."questionId" AND pa."userId" = %s
                    GROUP BY q.topic ORDER BY q.topic""", (userId,))


def checkPractice(user, attemptId):
    execute("""INSERT INTO "PracticeAnswer" ("userId", "questionId", selected, is_correct)
               SELECT %s, aa."questionId", aa.selected, aa.is_correct FROM "AttemptAnswer" aa
               WHERE aa."attemptId" = %s AND aa.selected IS NOT NULL""", (user["userId"], attemptId))


@bp.route("")
@requires_auth()
def practice():
    from .contest import practice_list
    return practice_list("question")
