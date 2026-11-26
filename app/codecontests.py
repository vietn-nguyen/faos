import json
import re
from pathlib import Path

import click
import requests
from flask import current_app
from psycopg.types.json import Jsonb

from .db import commit, execute, query, rollback
from .services import judge0, llm
from .services.generation import TIME_LIMIT

HF_TREE = "https://huggingface.co/api/datasets/deepmind/code_contests/tree/main/data"
HF_FILE = "https://huggingface.co/datasets/deepmind/code_contests/resolve/main/"
COLUMNS = ["name", "description", "public_tests", "private_tests", "generated_tests", "source",
           "solutions", "cf_contest_id", "cf_index", "cf_rating", "cf_tags", "time_limit",
           "input_file", "output_file"]
TARGETS = {"easy": 80, "medium": 80, "hard": 40}
OVERSAMPLE = {"easy": 3, "medium": 3, "hard": 5}
MAX_TESTS = 30
MAX_BIG = 4
MAX_IO = 64 * 1024
MIN_TESTS = 10
MAX_SOLUTIONS = 6
PYTHON3 = 3
CODEFORCES = 2
BAD_WORDS = ("<image>", "interact", "flush", "any of them", "print any", "output any", "any such",
             "any valid", "any possible", "any correct", "any one of", "any answer", "multiple answers",
             "multiple solutions", "several answers", "several solutions", "more than one answer",
             "relative error", "absolute error", "special judge")
TOPIC_TAGS = [
    ("string", {"strings", "hashing", "string suffix structures"}),
    ("tree_graph", {"graphs", "trees", "shortest paths", "dsu", "graph matchings", "flows"}),
    ("searching", {"binary search", "two pointers", "ternary search"}),
    ("sorting", {"sortings"}),
    ("recursion", {"dp", "divide and conquer", "bitmasks"}),
]

TRANSLATE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statement": {"type": "string"},
        "input": {"type": "string"},
        "output": {"type": "string"},
        "constraints": {"type": "string"},
        "note": {"type": "string"},
    },
    "required": ["title", "statement", "input", "output", "constraints", "note"],
    "additionalProperties": False,
}

TRANSLATE_PROMPT = """Bạn dịch đề bài lập trình thi đấu từ tiếng Anh sang tiếng Việt cho sinh viên đại học.
Dịch sát nghĩa, tự nhiên, không thêm hay bớt ý, không gợi ý lời giải.
- Giữ nguyên mọi công thức, ký hiệu toán, tên biến, số, giới hạn, ký tự $ và định dạng xuống dòng.
- Giữ nguyên các chuỗi phải in ra hoặc đọc vào (ví dụ YES, NO, -1) và tên riêng.
- title: tên bài đã dịch, không kèm mã bài.
- statement: phần mô tả bài toán (trước mục Input).
- input: mục Input, mô tả định dạng dữ liệu vào. output: mục Output.
- constraints: các giới hạn dữ liệu chép lại từ mục Input (ví dụ 1 ≤ n ≤ 10^5), mỗi giới hạn một dòng; để trống nếu đề không có.
- note: mục Note nếu có, ngược lại để trống.
- Bỏ mục Examples, các ví dụ được hệ thống hiển thị riêng.
- Hệ thống chấm so sánh output chính xác từng ký tự. Nếu đề gốc cho phép in chữ hoa hoặc thường tùy ý,
  thay câu đó bằng câu: "Hệ thống so sánh chính xác, hãy in đúng chữ hoa, chữ thường như trong đề."
"""


def data_dir():
    path = Path(current_app.config["STORAGE_DIR"]) / "codecontests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def add_jsonl(path, row):
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_difficulty(rating):
    if rating <= 1200:
        return "easy"
    return "medium" if rating <= 1800 else "hard"


def get_topic(tags):
    tags = set(tags or [])
    return next((topic for topic, names in TOPIC_TAGS if tags & names), "array")


def pick_tests(row):
    def pairs(key):
        t = row[key] or {"input": [], "output": []}
        return [(i, o) for i, o in zip(t["input"], t["output"]) if len(i) <= MAX_IO and len(o) <= MAX_IO and o.strip()]
    public = pairs("public_tests")
    rest = pairs("private_tests") + pairs("generated_tests")
    seen = {i for i, _ in public}
    rest = [p for p in rest if not (p[0] in seen or seen.add(p[0]))]
    room = MAX_TESTS - len(public)
    big = sorted(rest, key=lambda p: -len(p[0]))[:MAX_BIG]
    small = [p for p in rest if p not in big][:max(room - len(big), 0)]
    return public, small + big


def to_candidate(row):
    if row["source"] != CODEFORCES or not row["cf_rating"] or row["input_file"] or row["output_file"]:
        return None
    limit = row["time_limit"] or {"seconds": 0, "nanos": 0}
    seconds = limit["seconds"] + limit["nanos"] / 1e9
    if not 0 < seconds <= 2 or "interactive" in (row["cf_tags"] or []):
        return None
    text = row["description"].lower()
    if any(w in text for w in BAD_WORDS):
        return None
    sols = [s for lang, s in zip(row["solutions"]["language"], row["solutions"]["solution"]) if lang == PYTHON3]
    if not sols:
        return None
    public, tests = pick_tests(row)
    if not public or len(public) + len(tests) < MIN_TESTS:
        return None
    sols = sorted(set(sols), key=len)[:MAX_SOLUTIONS]
    return {"name": row["name"], "description": row["description"], "contest": row["cf_contest_id"],
            "index": row["cf_index"], "rating": row["cf_rating"], "tags": row["cf_tags"],
            "time": seconds, "difficulty": get_difficulty(row["cf_rating"]), "topic": get_topic(row["cf_tags"]),
            "samples": public, "tests": tests, "solutions": sols}


def same_key(c):
    return re.sub(r"\W+", "", c["description"].lower())[:400]


def shard_names():
    files = [f["path"] for f in requests.get(HF_TREE, timeout=30).json() if f["path"].endswith(".parquet")]
    first = [f for f in files if "/valid-" in f or "/test-" in f]
    return first + sorted(f for f in files if "/train-" in f)


def fetch_shard(name, folder):
    import pyarrow.parquet as pq
    local = folder / "shard.parquet"
    with requests.get(HF_FILE + name, stream=True, timeout=60) as r:
        r.raise_for_status()
        with local.open("wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    out = []
    try:
        for batch in pq.ParquetFile(local).iter_batches(batch_size=32, columns=COLUMNS):
            for row in batch.to_pylist():
                c = to_candidate(row)
                if c:
                    out.append(c)
    finally:
        local.unlink(missing_ok=True)
    return out


def bucket_counts(rows):
    counts = {d: 0 for d in TARGETS}
    for r in rows:
        counts[r["difficulty"]] += 1
    return counts


def enough(counts):
    return all(counts[d] >= TARGETS[d] * OVERSAMPLE[d] for d in TARGETS)


@click.command("cc-fetch")
@click.option("--max-shards", default=8)
def fetch_command(max_shards):
    folder = data_dir()
    cand_path, shard_path = folder / "candidates.jsonl", folder / "shards.txt"
    done = set(shard_path.read_text().split()) if shard_path.exists() else set()
    cands = read_jsonl(cand_path)
    keys = {same_key(c) for c in cands}
    counts = bucket_counts(cands)
    fetched = 0
    for name in shard_names():
        if enough(counts) or fetched >= max_shards:
            break
        if name in done:
            continue
        click.echo(f"Tải {name} ...")
        added = 0
        for c in fetch_shard(name, folder):
            k = same_key(c)
            if k in keys or counts[c["difficulty"]] >= TARGETS[c["difficulty"]] * OVERSAMPLE[c["difficulty"]]:
                continue
            keys.add(k)
            counts[c["difficulty"]] += 1
            add_jsonl(cand_path, c)
            added += 1
        with shard_path.open("a") as f:
            f.write(name + "\n")
        fetched += 1
        click.echo(f"  +{added} đề, tổng {counts}")
    click.echo(f"Ứng viên: {counts}")


def imported():
    rows = query("""SELECT difficulty, payload->'origin'->>'name' AS name FROM "Draft"
                    WHERE kind = 'code' AND payload ? 'origin'""")
    return {r["name"] for r in rows}, bucket_counts(rows)


def run_solution(code, tests):
    results = judge0.runBatch(code, [i for i, _ in tests], TIME_LIMIT)
    worst = 0.0
    for n, (res, (_, out)) in enumerate(zip(results, tests), 1):
        if res["status"] != "ok":
            return False, f"{res['status']} ở test #{n}", None
        if not judge0.outputsMatch(res["stdout"], out):
            return False, f"sai ở test #{n}", None
        worst = max(worst, res["time"] or 0)
        if worst > TIME_LIMIT / 2:
            return False, f"chạy {res['time']} giây ở test #{n}, quá nửa giới hạn {TIME_LIMIT} giây", None
    return True, None, worst


def pick_solution(c):
    tests = c["samples"] + c["tests"]
    reasons = []
    for code in c["solutions"]:
        ok, why, worst = run_solution(code, tests)
        if ok:
            return code, worst, None
        reasons.append(why)
    return None, None, "; ".join(reasons)


ANY_CASE = re.compile(r"any (letter )?case|any register|upper ?case or lower ?case|lower ?case or upper ?case|case[- ]insensitive", re.I)
EXACT = "Hệ thống so sánh chính xác"


def numbers(text):
    return set(re.findall(r"\d+", text))


def body(description):
    return re.split(r"\n\s*Examples?\s*\n", description)[0]


def translate(c):
    total = {"in": 0, "out": 0}
    src = body(c["description"])
    note = re.split(r"\n\s*Note\s*\n", c["description"])
    if len(note) > 1:
        src += "\n\nNote\n\n" + note[-1]
    lost = set()
    for _ in range(2):
        out, usage = llm.ask(TRANSLATE_PROMPT, src, TRANSLATE_SCHEMA, 16000, "low")
        total["in"] += usage.input_tokens
        total["out"] += usage.output_tokens
        fields = [out[k].strip() for k in ("title", "statement", "input", "output")]
        lost = numbers(src) - numbers(" ".join(out.values()))
        exact = not ANY_CASE.search(src) or EXACT in out["output"] + out["statement"]
        if all(fields) and exact and len(lost) <= max(1, len(numbers(src)) // 20):
            return out, total, None
    return None, total, f"bản dịch thiếu nội dung, mất số {sorted(lost)[:10]} hoặc còn cho in hoa thường tùy ý"


def origin(c):
    url = f"https://codeforces.com/contest/{c['contest']}/problem/{c['index']}"
    return {"dataset": "DeepMind CodeContests", "license": "CC BY 4.0", "name": c["name"],
            "contest": f"Codeforces contest {c['contest']}", "index": c["index"], "url": url,
            "rating": c["rating"], "tags": c["tags"]}


def credit(o):
    return (f"Nguồn: {o['contest']}, bài {o['index']} ({o['url']}), lấy từ bộ dữ liệu "
            f"{o['dataset']} ({o['license']}). Đề đã được dịch sang tiếng Việt.")


def make_payload(c, tr, code, worst):
    o = origin(c)
    statement = tr["statement"].strip()
    if tr["note"].strip():
        statement += "\n\nGhi chú:\n" + tr["note"].strip()
    statement += "\n\n" + credit(o)
    o["ref_time"] = worst
    return {"title": tr["title"].strip(), "statement": statement, "input": tr["input"].strip(),
            "output": tr["output"].strip(), "constraints": tr["constraints"].strip(),
            "samples": [{"input": i, "output": out} for i, out in c["samples"]],
            "test_inputs": [i for i, _ in c["tests"]], "reference_solution": code,
            "brute_solution": "", "origin": o}


def save_draft(c, payload, usage):
    outputs = [out for _, out in c["samples"] + c["tests"]]
    row = execute("""INSERT INTO "Draft" (kind, topic, difficulty, status, payload, output, "inputT", "outputT")
                     VALUES ('code', %s, %s, 'pending_review', %s, %s, %s, %s) RETURNING "draftId" """,
                  (get_topic(c["tags"]), c["difficulty"], Jsonb(payload), Jsonb(outputs), usage["in"], usage["out"]),
                  returning=True)
    commit()
    return row["draftId"]


def import_one(c):
    code, worst, why = pick_solution(c)
    if code is None:
        return None, f"không lời giải Python 3 nào qua Judge0 ({why})"[:500]
    tr, usage, why = translate(c)
    if tr is None:
        return None, why
    return save_draft(c, make_payload(c, tr, code, worst), usage), None


@click.command("cc-import")
@click.option("--limit", default=0)
@click.option("--retry", is_flag=True)
def import_command(limit, retry):
    folder = data_dir()
    log_path = folder / "log.jsonl"
    names, counts = imported()
    skipped = set() if retry else {r["name"] for r in read_jsonl(log_path) if r.get("skip")}
    added = 0
    for c in read_jsonl(folder / "candidates.jsonl"):
        if limit and added >= limit:
            break
        if all(counts[d] >= TARGETS[d] for d in TARGETS):
            break
        if c["name"] in names or c["name"] in skipped or counts[c["difficulty"]] >= TARGETS[c["difficulty"]]:
            continue
        try:
            draftId, why = import_one(c)
        except Exception as e:
            rollback()
            click.echo(f"{c['name']}: lỗi {e}")
            continue
        if draftId is None:
            add_jsonl(log_path, {"name": c["name"], "difficulty": c["difficulty"], "skip": why})
            click.echo(f"bỏ {c['name']} [{c['difficulty']}]: {why[:160]}")
            continue
        add_jsonl(log_path, {"name": c["name"], "difficulty": c["difficulty"], "draftId": draftId})
        names.add(c["name"])
        counts[c["difficulty"]] += 1
        added += 1
        click.echo(f"draft #{draftId} {c['name']} [{c['difficulty']}, {get_topic(c['tags'])}] tổng {counts}")
    click.echo(f"Đã nhập {added} đề trong lần này. Tổng theo độ khó: {counts}")


def init_app(app):
    app.cli.add_command(fetch_command)
    app.cli.add_command(import_command)
