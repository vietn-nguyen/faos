import csv
import io

from psycopg.types.json import Jsonb

from ..db import commit, execute, query, rollback
from ..labels import KEYS
from . import judge0, llm, metrics, scoring, standard
from .jobs import in_app_context

TIME_LIMIT = 2.0
BASE_TIME = 5.0


def all_inputs(payload):
    return [s["input"] for s in payload["samples"]] + payload["test_inputs"]


def set_failed(draftId, errMess):
    execute("""UPDATE "Draft" SET status = 'failed', "errMess" = %s WHERE "draftId" = %s""",
            (errMess[:1000], draftId))


def validatePayload(payload, cfg=None):
    cfg = cfg or standard.LIMITS["code"]
    if len(payload["samples"]) < cfg["min_samples"] or len(payload["test_inputs"]) < cfg["min_tests"]:
        return False, f"Cần ít nhất {cfg['min_samples']} ví dụ mẫu và {cfg['min_tests']} test.", None
    try:
        results = judge0.runBatch(payload["reference_solution"], all_inputs(payload), 2.0)
    except Exception as e:
        return False, f"Judge0 lỗi: {e}", None

    for i, res in enumerate(results):
        if res["status"] != "ok":
            return False, f"Lời giải mẫu bị {res['status']} ở input #{i + 1}: {res['stderr'][:300]}", None
        if not res["stdout"].strip():
            return False, f"Lời giải mẫu không in gì ở input #{i + 1}.", None

    for i, sample in enumerate(payload["samples"]):
        if not judge0.outputsMatch(results[i]["stdout"], sample["output"]):
            return False, f"Output ví dụ #{i + 1} trong đề khác với kết quả lời giải mẫu.", None

    for i, res in enumerate(results):
        if res["time"] is not None and res["time"] > TIME_LIMIT / 2:
            return False, (f"Lời giải mẫu chạy {res['time']} giây ở input #{i + 1}, "
                           f"quá nửa giới hạn {TIME_LIMIT} giây."), None

    brute = payload.get("brute_solution", "").strip()
    if not brute:
        return False, "LLM không trả về lời giải vét cạn để đối chiếu.", None
    try:
        checks = judge0.runBatch(brute, all_inputs(payload), TIME_LIMIT * 3)
    except Exception as e:
        return False, f"Judge0 lỗi khi chạy lời giải vét cạn: {e}", None
    n_samples = len(payload["samples"])
    compared = 0
    for i, (res, ref) in enumerate(zip(checks, results)):
        if res["status"] != "ok":
            if i < n_samples:
                return False, f"Lời giải vét cạn bị {res['status']} ở ví dụ #{i + 1}.", None
            continue
        compared += 1
        if not judge0.outputsMatch(res["stdout"], ref["stdout"]):
            return False, f"Lời giải mẫu và lời giải vét cạn cho kết quả khác nhau ở input #{i + 1}.", None

    return True, None, {"outputs": [r["stdout"] for r in results], "compared": compared}


def checkQuestions(payload, cfg=None, topic=None, draftId=None, usage=None):
    cfg = cfg or standard.LIMITS["question"]
    questions = payload.get("questions") or []
    if len(questions) < 1:
        return False, "LLM không trả về câu hỏi nào.", None
    for i, q in enumerate(questions):
        options = [q["op1"].strip(), q["op2"].strip(), q["op3"].strip(), q["op4"].strip()]
        if not q["content"].strip() or not all(options) or q["key"] not in KEYS:
            return False, f"Câu hỏi #{i + 1} thiếu nội dung, đáp án hoặc đáp án đúng.", None
        if len(set(options)) < 4:
            return False, f"Câu hỏi #{i + 1} có đáp án trùng nhau.", None
        if len(q["explain"].strip()) < cfg["min_explain"]:
            return False, f"Câu hỏi #{i + 1} có giải thích ngắn hơn {cfg['min_explain']} ký tự.", None
    if sum(1 for q in questions if q["code"].strip()) < cfg["min_code"]:
        return False, f"Cần ít nhất {cfg['min_code']} câu hỏi có mã nguồn.", None
    kept, dropped = [], []
    for q in questions:
        text = q["content"] + " " + q["code"]
        mine = [{"id": "câu khác trong bản nháp", "title": k["content"], "text": k["content"] + " " + k["code"]}
                for k in kept]
        dup = standard.find_dup("question", topic, text, cfg, draftId, mine, usage) if topic else None
        if dup:
            dropped.append({"content": q["content"][:120], "id": dup["id"], "how": dup["how"]})
        else:
            kept.append(q)
    if not kept:
        return False, "Mọi câu hỏi đều trùng với câu đã có trong ngân hàng.", None
    payload["questions"] = kept
    payload["title"] = kept[0]["content"][:120]
    return True, None, {"count": len(kept), "dropped": dropped}


def split(payload):
    cols = payload["columns"]
    rows = [dict(zip(cols, r)) for r in payload["rows"]]
    parts = {"train": [], "public": [], "private": []}
    for i, r in enumerate(rows):
        parts["public" if i % 5 == 3 else "private" if i % 5 == 4 else "train"].append(r)
    return parts


def checkTask(payload, cfg=None):
    cfg = cfg or standard.LIMITS["predict"]
    cols = payload["columns"]
    id_col, label = payload["id_col"], payload["label_col"]
    if id_col not in cols or label not in cols or id_col == label or len(set(cols)) != len(cols):
        return False, "Cột mã dòng hoặc cột nhãn không nằm trong danh sách cột.", None
    rows = payload["rows"]
    if len(rows) < cfg["min_rows"] or any(len(r) != len(cols) for r in rows):
        return False, f"Dữ liệu cần ít nhất {cfg['min_rows']} dòng và mỗi dòng phải đủ cột.", None
    ids = [r[cols.index(id_col)] for r in rows]
    if len(set(ids)) != len(ids):
        return False, "Mã dòng bị trùng.", None
    parts = split(payload)
    labels = [r[label] for r in parts["train"]]
    if len(set(labels)) < 2:
        return False, "Tập huấn luyện chỉ có một lớp nhãn.", None
    if payload["metric"] == "f1" and {str(r[label]) for part in parts.values() for r in part} - {"0", "1"}:
        return False, "Độ đo f1 cần nhãn 0 và 1 (lớp dương là 1).", None
    common = max(set(labels), key=labels.count)
    config = {"id": id_col, "label": label}
    out = {"sizes": {k: len(v) for k, v in parts.items()}, "majority": common}
    for phase in ("public", "private"):
        key = [{id_col: r[id_col], label: r[label]} for r in parts[phase]]
        if len({r[label] for r in key}) < 2:
            return False, f"Tập {phase} chỉ có một lớp nhãn.", None
        guess = [{id_col: r[id_col], label: common} for r in key]
        out[phase] = round(metrics.METRICS[payload["metric"]](guess, key, config), 2)
        if out[phase] > cfg["max_base"]:
            return False, (f"Đoán theo lớp phổ biến nhất đã đạt {out[phase]} điểm ở tập {phase}, "
                           f"vượt mức {cfg['max_base']}: dữ liệu quá lệch."), None
    test = parts["public"] + parts["private"]
    key = [{id_col: r[id_col], label: r[label]} for r in test]
    guess = round(metrics.METRICS[payload["metric"]]([{id_col: r[id_col], label: common} for r in key], key, config), 2)
    ok, errMess, base = run_baseline(payload, parts["train"], test)
    if not ok:
        return False, errMess, None
    gain = cfg.get("min_gain", 10)
    if base < guess + gain:
        return False, (f"Mã mẫu đạt {round(base, 2)} điểm trên tập test, chưa hơn cách đoán lớp phổ biến nhất "
                       f"({guess}) ít nhất {gain} điểm: dữ liệu chưa có quy luật học được."), None
    out["baseline"] = round(base, 2)
    out["guess"] = guess
    return True, None, out


def to_csv(rows, cols):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def run_baseline(payload, train, test):
    cols, id_col, label = payload["columns"], payload["id_col"], payload["label_col"]
    hidden = [c for c in cols if c != label]
    files = {"train.csv": to_csv(train, cols), "public_test.csv": to_csv(test, hidden)}
    code = ("import os\n"
            + "".join(f"open({n!r}, 'w', encoding='utf-8').write({t!r})\n" for n, t in files.items())
            + payload["baseline"]
            + "\nprint(open('submission.csv', encoding='utf-8').read())\n")
    try:
        res = judge0.runBatch(code, [""], BASE_TIME, 256)[0]
    except Exception as e:
        return False, f"Judge0 lỗi khi chạy mã mẫu: {e}", None
    if res["status"] != "ok":
        return False, f"Mã mẫu bị {res['status']} khi chạy thử: {(res['stderr'] or '')[:300]}", None
    try:
        pred = scoring.parse(res["stdout"].encode("utf-8"), "submission.csv")
        key = [{id_col: r[id_col], label: r[label]} for r in test]
        base = metrics.METRICS[payload["metric"]](pred, key, {"id": id_col, "label": label})
    except Exception as e:
        return False, f"File submission.csv của mã mẫu không chấm được: {e}"[:400], None
    return True, None, base


def check(kind, payload, cfg=None, topic=None, draftId=None, usage=None):
    if kind == "question":
        return checkQuestions(payload, cfg, topic, draftId, usage)
    cfg = cfg or standard.LIMITS[kind]
    if topic:
        text = payload["title"] + " " + payload["statement"]
        dup = standard.find_dup(kind, topic, text, cfg, draftId, (), usage)
        if dup:
            return False, f"Trùng với đề {dup['id']} ({dup['how']}): {dup['title'][:120]}", None
    if kind == "predict":
        return checkTask(payload, cfg)
    return validatePayload(payload, cfg)


@in_app_context
def generate(draftId):
    try:
        run_generate(draftId)
    except Exception as e:
        rollback()
        set_failed(draftId, f"Lỗi khi tạo đề: {e}")
        commit()


def run_generate(draftId):
    draft = query('SELECT * FROM "Draft" WHERE "draftId" = %s', (draftId,), one=True)
    if draft is None or draft["status"] != "generating":
        return
    std = standard.get(draft["kind"])
    ctx = standard.context(draft["kind"], draft["topic"], draft["difficulty"], std, draftId)
    execute('UPDATE "Draft" SET context = %s WHERE "draftId" = %s', (Jsonb(standard.summary(std, ctx)), draftId))
    commit()
    try:
        payload, usage = llm.callAPI(draft["kind"], draft["topic"], draft["difficulty"], std["rules"], ctx)
    except Exception as e:
        set_failed(draftId, f"Gọi LLM API lỗi: {e}")
        return

    execute("""UPDATE "Draft" SET status = 'validating', payload = %s, "inputT" = %s, "outputT" = %s
               WHERE "draftId" = %s""",
            (Jsonb(payload), usage.input_tokens, usage.output_tokens, draftId))
    commit()

    usage = {"in": 0, "out": 0}
    try:
        ok, errMess, output = check(draft["kind"], payload, std["config"], draft["topic"], draftId, usage)
    finally:
        execute("""UPDATE "Draft" SET "inputT" = "inputT" + %s, "outputT" = "outputT" + %s WHERE "draftId" = %s""",
                (usage["in"], usage["out"], draftId))
        commit()
    if ok and draft["kind"] == "code":
        output = output["outputs"]
    if ok and draft["kind"] == "question":
        execute("""UPDATE "Draft" SET status = 'pending_review', output = %s, payload = %s WHERE "draftId" = %s""",
                (Jsonb(output), Jsonb(payload), draftId))
    elif ok:
        execute("""UPDATE "Draft" SET status = 'pending_review', output = %s WHERE "draftId" = %s""",
                (Jsonb(output), draftId))
    else:
        set_failed(draftId, errMess)
