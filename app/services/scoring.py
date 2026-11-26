import csv
import io
import json
import zipfile
from pathlib import Path

from flask import current_app
from psycopg.types.json import Jsonb

from ..db import commit, execute, query, rollback
from . import attempt as attempts
from . import metrics, storage
from .jobs import in_app_context

TYPES = (".csv", ".json", ".jsonl")


def parse(raw, name):
    text = raw.decode("utf-8-sig")
    kind = Path(name).suffix.lower()
    if kind == ".json":
        return json.loads(text)
    if kind == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    rows = csv.DictReader(io.StringIO(text), skipinitialspace=True)
    return [{(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def readFile(path, fileName, taken=()):
    file = storage.full(path)
    if file.suffix.lower() != ".zip":
        return parse(file.read_bytes(), file.name if file.suffix.lower() in TYPES else fileName)
    with zipfile.ZipFile(file) as z:
        names = [n for n in z.namelist() if not n.endswith("/") and "__MACOSX" not in n]
        found = [n for n in names if Path(n).name == fileName]
        if not found:
            same = [n for n in names if Path(n).suffix.lower() == Path(fileName).suffix.lower()
                    and Path(n).name not in taken]
            found = same if len(same) == 1 else []
        if not found:
            raise FileNotFoundError(f"Không thấy tệp {fileName} trong file zip.")
        if z.getinfo(found[0]).file_size > current_app.config["MAX_CONTENT_LENGTH"]:
            raise ValueError(f"Tệp {fileName} trong file zip quá lớn.")
        return parse(z.read(found[0]), fileName)


def calc(metric, pred, key, config):
    return round(min(100.0, max(0.0, metrics.METRICS[metric](pred, key, config or {}))), 4)


def normScore(score, minScore, maxScore):
    if score is None or maxScore is None or score <= minScore or maxScore <= minScore:
        return 0.0
    return min(100.0, 100.0 * (score - minScore) / (maxScore - minScore))


def get_metrics(taskId):
    return query('SELECT * FROM "Metric" WHERE "taskId" = %s ORDER BY position, "metricId"', (taskId,))


def get_keys(taskId, phase):
    return query('SELECT * FROM "Dataset" WHERE "taskId" = %s AND role = %s ORDER BY "dataId"',
                 (taskId, f"{phase}_key"))


def key_for(keys, fileName):
    named = [k for k in keys if k["fileName"] == fileName]
    if named:
        return named[0]
    return keys[0] if len(keys) == 1 else None


def weighted(parts, mets):
    total = sum(m["weight"] for m in mets) or 1.0
    return sum(m["weight"] / total * (parts.get(str(m["metricId"])) or 0.0) for m in mets)


def scope_sql(contestId):
    if contestId is None:
        return 'p."attemptId" IS NULL', ()
    return 'p."attemptId" IN (SELECT "attemptId" FROM "ContestAttempt" WHERE "contestId" = %s)', (contestId,)


def all_rows(taskId, phase, contestId=None):
    where, params = scope_sql(contestId)
    return query(f"""SELECT p.*, u.username FROM "Prediction" p JOIN "User" u ON u."userId" = p."userId"
                     LEFT JOIN "ContestAttempt" a ON a."attemptId" = p."attemptId"
                     WHERE p."taskId" = %s AND p.phase = %s AND p.status = 'done' AND {where}
                       AND (a."attemptId" IS NULL OR p.created <= a.deadline)
                     ORDER BY p."predId" """, (taskId, phase, *params))


def part_scores(row):
    return {str(p["metricId"]): p["score"] for p in (row["detail"] or {}).get("parts", [])}


def taskBoard(taskId, phase, contestId=None):
    mets = get_metrics(taskId)
    rows = all_rows(taskId, phase, contestId)
    total = sum(m["weight"] for m in mets) or 1.0
    for r in rows:
        r["parts"] = part_scores(r)
    for m in mets:
        mid = str(m["metricId"])
        m["top"] = m["maxScore"]
        if m["top"] is None:
            m["top"] = max([r["parts"].get(mid) or 0.0 for r in rows], default=None)
    best = {}
    for r in rows:
        r["norms"] = [normScore(r["parts"].get(str(m["metricId"])), m["minScore"], m["top"]) for m in mets]
        r["final"] = round(sum(m["weight"] / total * n for m, n in zip(mets, r["norms"])), 2)
        if r["userId"] not in best or r["final"] > best[r["userId"]]["final"]:
            best[r["userId"]] = r
    board = sorted(best.values(), key=lambda r: (-r["final"], r["created"]))
    return board, mets


def taskScore(taskId, phase, userId, contestId=None, cache=None):
    key = (taskId, phase, contestId)
    if cache is None or key not in cache:
        rows, _ = taskBoard(taskId, phase, contestId)
        finals = {r["userId"]: r["final"] for r in rows}
        if cache is None:
            return finals.get(userId, 0.0)
        cache[key] = finals
    return cache[key].get(userId, 0.0)


def set_status(predId, status, errMess):
    execute("""UPDATE "Prediction" SET status = %s, "errMess" = %s, judged = now() WHERE "predId" = %s""",
            (status, errMess[:1000], predId))


@in_app_context
def score(predId):
    try:
        run_score(predId)
    except Exception as e:
        rollback()
        set_status(predId, "system_error", f"Lỗi khi chấm: {e}")
        commit()


def run_score(predId):
    pred = query('SELECT * FROM "Prediction" WHERE "predId" = %s', (predId,), one=True)
    if pred is None:
        return
    mets = get_metrics(pred["taskId"])
    keys = get_keys(pred["taskId"], pred["phase"])
    execute("""UPDATE "Prediction" SET status = 'scoring' WHERE "predId" = %s""", (predId,))
    commit()
    if not mets or not keys:
        set_status(predId, "system_error", "Bài chưa có phần điểm hoặc chưa có nhãn cho giai đoạn này.")
        return

    parts = []
    scored = 0
    for m in mets:
        part = {"metricId": m["metricId"], "name": m["name"], "metric": m["metric"], "score": None, "error": None}
        parts.append(part)
        key = key_for(keys, m["fileName"])
        try:
            if key is None:
                raise LookupError
            answer = readFile(key["path"], m["fileName"])
        except Exception as e:
            set_status(predId, "system_error", f"Không đọc được nhãn của phần {m['name']}: {e}")
            return
        try:
            mine = readFile(pred["path"], m["fileName"], [x["fileName"] for x in mets])
            part["score"] = calc(m["metric"], mine, answer, m["config"])
            scored += 1
        except FileNotFoundError as e:
            part["error"] = str(e)
        except (ValueError, KeyError, TypeError, AttributeError, UnicodeDecodeError, zipfile.BadZipFile) as e:
            part["error"] = f"Sai định dạng: {e}"[:300]

    if not scored:
        set_status(predId, "invalid", "; ".join(p["error"] for p in parts if p["error"]))
        execute('UPDATE "Prediction" SET detail = %s WHERE "predId" = %s', (Jsonb({"parts": parts}), predId))
        return
    raw = weighted({str(p["metricId"]): p["score"] for p in parts}, mets)
    execute("""UPDATE "Prediction" SET status = 'done', score = %s, detail = %s, judged = now()
               WHERE "predId" = %s""", (round(raw, 4), Jsonb({"parts": parts}), predId))
    commit()

    if pred["attemptId"]:
        attempts.recompute(pred["attemptId"])
