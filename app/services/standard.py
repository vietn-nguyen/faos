import re

from psycopg.types.json import Jsonb

from ..db import execute, query
from ..labels import REJECT_REASONS
from . import llm

LIMITS = {
    "code": {"min_samples": 1, "min_tests": 3, "dup": 50, "dup_hint": 15},
    "question": {"min_explain": 20, "min_code": 0, "dup": 50, "dup_hint": 15},
    "predict": {"min_rows": 50, "max_base": 90, "min_gain": 10, "dup": 50, "dup_hint": 15},
}
SAME_TOP = 3
EXAMPLES = 2
MAX_EXAMPLES = 5
MAX_TITLES = 40
MAX_REJECTS = 5
CUT = 1200


def get(kind):
    std = query('SELECT * FROM "Standard" WHERE kind = %s', (kind,), one=True)
    if std is None:
        std = execute("""INSERT INTO "Standard" (kind, rules, examples, config) VALUES (%s, %s, %s, %s)
                         ON CONFLICT (kind) DO UPDATE SET kind = EXCLUDED.kind RETURNING *""",
                      (kind, llm.PROMPTS[kind], EXAMPLES, Jsonb(LIMITS[kind])), returning=True)
    std["config"] = {**LIMITS[kind], **(std["config"] or {})}
    return std


def save(kind, rules, examples, config, userId):
    get(kind)
    execute("""UPDATE "Standard" SET rules = %s, examples = %s, config = %s, "updatedBy" = %s, updated = now()
               WHERE kind = %s""", (rules, examples, Jsonb(config), userId, kind))


def reset(kind, userId):
    save(kind, llm.PROMPTS[kind], EXAMPLES, LIMITS[kind], userId)


def short(text):
    text = (text or "").strip()
    return text if len(text) <= CUT else text[:CUT] + "..."


def code_examples(topic, difficulty, n):
    rows = query("""SELECT "problemId", title, statement, input, output, constraints, is_model FROM "Problem"
                    WHERE kind = 'code' AND (topic = %s OR is_model)
                    ORDER BY (topic = %s) DESC, is_model DESC, (difficulty = %s) DESC, random() LIMIT %s""",
                 (topic, topic, difficulty, n))
    for r in rows:
        sample = query("""SELECT input, output FROM "TestCase" WHERE "problemId" = %s AND sample
                          ORDER BY position LIMIT 1""", (r["problemId"],), one=True)
        r["sample"] = sample
    return [{"id": r["problemId"], "is_model": r["is_model"],
             "item": {"title": r["title"], "statement": short(r["statement"]), "input": short(r["input"]),
                      "output": short(r["output"]), "constraints": short(r["constraints"]),
                      "sample": r["sample"]}} for r in rows]


def question_examples(topic, difficulty, n):
    rows = query("""SELECT * FROM "Question" WHERE topic = %s OR is_model
                    ORDER BY (topic = %s) DESC, is_model DESC, (difficulty = %s) DESC, random() LIMIT %s""",
                 (topic, topic, difficulty, n))
    return [{"id": r["questionId"], "is_model": r["is_model"],
             "item": {k: short(r[k]) for k in ("content", "code", "op1", "op2", "op3", "op4", "key", "explain")}}
            for r in rows]


def task_examples(topic, difficulty, n):
    rows = query("""SELECT p."problemId", p.title, p.statement, p.is_model, t."dataDesc", t."submitFormat",
                           (SELECT string_agg(m.metric, ', ') FROM "Metric" m WHERE m."taskId" = t."taskId") AS metrics
                    FROM "Problem" p JOIN "Task" t ON t."problemId" = p."problemId"
                    WHERE p.kind = 'predict' AND (p.topic = %s OR p.is_model)
                    ORDER BY (p.topic = %s) DESC, p.is_model DESC, (p.difficulty = %s) DESC, random() LIMIT %s""",
                 (topic, topic, difficulty, n))
    return [{"id": r["problemId"], "is_model": r["is_model"],
             "item": {"title": r["title"], "statement": short(r["statement"]), "data_desc": short(r["dataDesc"]),
                      "submit_format": short(r["submitFormat"]), "metric": r["metrics"]}} for r in rows]


FINDERS = {"code": code_examples, "question": question_examples, "predict": task_examples}


def draft_texts(kind, topic, draftId):
    rows = query("""SELECT "draftId", payload FROM "Draft" WHERE kind = %s AND topic = %s AND payload IS NOT NULL
                    AND status IN ('validating', 'pending_review') AND "draftId" <> %s ORDER BY "draftId" DESC""",
                 (kind, topic, draftId or 0))
    out = []
    for r in rows:
        p = r["payload"]
        if kind == "question":
            out += [{"id": f"nháp #{r['draftId']}", "title": q["content"], "text": q["content"] + " " + q["code"]}
                    for q in p.get("questions") or []]
        else:
            out.append({"id": f"nháp #{r['draftId']}", "title": p.get("title", ""),
                        "text": p.get("title", "") + " " + p.get("statement", "")})
    return out


def bank_texts(kind, topic, draftId=None):
    if kind == "question":
        rows = query("""SELECT "questionId" AS id, content AS title, content || ' ' || code AS text
                        FROM "Question" WHERE topic = %s ORDER BY "questionId" DESC""", (topic,))
    else:
        rows = query("""SELECT "problemId" AS id, title, title || ' ' || statement AS text
                        FROM "Problem" WHERE kind = %s AND topic = %s ORDER BY "problemId" DESC""", (kind, topic))
    return draft_texts(kind, topic, draftId) + rows


def rejects(kind, topic):
    rows = query("""SELECT r.reason, r.note FROM "Review" r JOIN "Draft" d ON d."draftId" = r."draftId"
                    WHERE r.decision = 'rejected' AND d.kind = %s AND d.topic = %s
                    ORDER BY r."revId" DESC LIMIT %s""", (kind, topic, MAX_REJECTS))
    return [REJECT_REASONS[r["reason"]] + (f": {r['note']}" if r["note"] else "") for r in rows]


def context(kind, topic, difficulty, std, draftId=None):
    n = max(0, min(std["examples"], MAX_EXAMPLES))
    return {"examples": FINDERS[kind](topic, difficulty, n) if n else [],
            "titles": [short(r["title"])[:160] for r in bank_texts(kind, topic, draftId)[:MAX_TITLES]],
            "rejects": rejects(kind, topic)}


def summary(std, ctx):
    return {"standardId": std["standardId"], "updated": std["updated"].isoformat(),
            "examples": [{"id": e["id"], "is_model": e["is_model"]} for e in ctx["examples"]],
            "titles": len(ctx["titles"]), "rejects": ctx["rejects"]}


def words(text):
    return set(re.findall(r"\w+", (text or "").lower()))


def similar(a, b):
    a, b = words(a), words(b)
    if not a or not b:
        return 0
    return round(100 * len(a & b) / len(a | b))


def find_dup(kind, topic, text, cfg, draftId=None, extra=(), usage=None):
    rows = list(extra) + bank_texts(kind, topic, draftId)
    scored = sorted(((similar(text, r["text"]), r) for r in rows), key=lambda x: -x[0])
    if scored and scored[0][0] >= cfg["dup"]:
        return {**scored[0][1], "how": f"giống {scored[0][0]}% về từ ngữ"}
    near = [r for sim, r in scored[:SAME_TOP] if sim >= cfg.get("dup_hint", 15)]
    if not near:
        return None
    dup, reason, used = llm.sameIdea(text, near)
    if usage is not None:
        usage["in"] += used.input_tokens
        usage["out"] += used.output_tokens
    return {**dup, "how": f"cùng ý tưởng: {reason}"} if dup else None
