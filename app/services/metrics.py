import math
import re
from collections import Counter


def table(data):
    if isinstance(data, dict):
        data = [row for rows in data.values() if isinstance(rows, list) for row in rows]
    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
        raise ValueError("File phải là bảng gồm các dòng có tên cột.")
    return data


def cols(key, config):
    first = list(key[0].keys()) if key else []
    id_col = config.get("id") or (first[0] if first else "id")
    label = config.get("label") or (first[1] if len(first) > 1 else "label")
    return id_col, label


def norm(value):
    return "" if value is None else str(value).strip()


def by_id(rows, id_col, need=()):
    rows = table(rows)
    if rows:
        missing = [c for c in (id_col, *need) if c not in rows[0]]
        if missing:
            raise ValueError(f"Thiếu cột: {', '.join(missing)}.")
    out = {}
    for r in rows:
        out.setdefault(norm(r.get(id_col)), r)
    return out


def pairs(pred, key, config):
    key = table(key)
    id_col, label = cols(key, config)
    guess = by_id(pred, id_col, (label,))
    return [(norm(k.get(label)), norm(guess.get(norm(k.get(id_col)), {}).get(label)))
            for k in key if id_col in k], label


def prf(tp, n_pred, n_gold):
    p = tp / n_pred if n_pred else 0.0
    r = tp / n_gold if n_gold else 0.0
    return 2 * p * r / (p + r) if p + r > 0 else 0.0


def accuracy(pred, key, config):
    rows, _ = pairs(pred, key, config)
    return 100.0 * sum(g == p for g, p in rows) / len(rows) if rows else 0.0


def f1(pred, key, config):
    rows, _ = pairs(pred, key, config)
    pos = str(config.get("positive", "1"))
    tp = sum(g == pos and p == pos for g, p in rows)
    return 100.0 * prf(tp, sum(p == pos for _, p in rows), sum(g == pos for g, _ in rows))


def macro_f1(pred, key, config):
    rows, _ = pairs(pred, key, config)
    labels = sorted({g for g, _ in rows})
    if not labels:
        return 0.0
    total = 0.0
    for c in labels:
        tp = sum(g == c and p == c for g, p in rows)
        total += prf(tp, sum(p == c for _, p in rows), sum(g == c for g, _ in rows))
    return 100.0 * total / len(labels)


def is_true(value):
    return norm(value).lower() in ("true", "1", "yes")


def detect_f1(pred, key, config):
    key = table(key)
    id_col, label = cols(key, config)
    label = config.get("label", "category_id")
    neg = config.get("neg", "is_negative")
    guess = by_id(pred, id_col, (neg, label))
    tp = fp = fn = 0
    for k in key:
        g = guess.get(norm(k.get(id_col)))
        said = g is not None and not is_true(g.get(neg))
        if is_true(k.get(neg)):
            fp += said
        elif said and norm(g.get(label)) == norm(k.get(label)):
            tp += 1
        else:
            fn += 1
    return 100.0 * prf(tp, tp + fp, tp + fn)


def id_sets(rows, id_col, label):
    out = {}
    for r in table(rows):
        ids = {x.strip() for x in norm(r.get(label)).split(";") if x.strip()}
        out.setdefault(norm(r.get(id_col)), set()).update(ids)
    return out


def align_f1(pred, key, config):
    key = table(key)
    id_col, label = cols(key, config)
    by_id(pred, id_col, (label,))
    gold, guess = id_sets(key, id_col, label), id_sets(pred, id_col, label)
    tp = sum(len(g & guess.get(i, set())) for i, g in gold.items())
    n_pred = sum(len(guess.get(i, set())) for i in gold)
    return 100.0 * prf(tp, n_pred, sum(len(g) for g in gold.values()))


def domains(data):
    if isinstance(data, dict):
        return {d: rows for d, rows in data.items() if isinstance(rows, list)}
    if isinstance(data, list):
        return {"": data}
    raise ValueError("File phải là danh sách hoặc đối tượng theo miền.")


def tuples(row, list_col, fields):
    items = row.get(list_col) if isinstance(row, dict) else None
    return {tuple(norm(t.get(f)) for f in fields) for t in items or [] if isinstance(t, dict)}


def triple_f1(pred, key, config):
    id_col = config.get("id", "raw_words")
    list_col = config.get("list", "triples")
    fields = config.get("fields", ["aspect", "category", "sentiment"])
    gold, guess = domains(key), domains(pred)
    if not gold:
        return 0.0
    total = 0.0
    for d, rows in gold.items():
        mine = {}
        for r in guess.get(d, []):
            if isinstance(r, dict):
                mine.setdefault(norm(r.get(id_col)), r)
        tp = n_pred = n_gold = 0
        for r in rows:
            g = tuples(r, list_col, fields)
            p = tuples(mine.get(norm(r.get(id_col)), {}), list_col, fields)
            tp += len(g & p)
            n_pred += len(p)
            n_gold += len(g)
        total += prf(tp, n_pred, n_gold)
    return 100.0 * total / len(gold)


def number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def va_items(rows, id_col, list_col, fields, values):
    out = {}
    for r in table(rows):
        items = r.get(list_col) if list_col else [r]
        for t in items or []:
            if isinstance(t, dict):
                name = (norm(r.get(id_col)), *[norm(t.get(f)) for f in fields])
                out.setdefault(name, [number(t.get(v)) for v in values])
    return out


def rmse_gain(pred, key, config):
    id_col = config.get("id", "id")
    list_col = config.get("list", "aspects")
    fields = config.get("fields", ["aspect"])
    values = config.get("values", ["valence", "arousal"])
    worst = float(config.get("max_err", 8))
    base = float(config.get("base", 1))
    gold = va_items(key, id_col, list_col, fields, values)
    guess = va_items(pred, id_col, list_col, fields, values)
    if not gold or base <= 0:
        return 0.0
    total = 0.0
    for name, g in gold.items():
        p = guess.get(name) or [None] * len(g)
        total += sum((worst if a is None or b is None else a - b) ** 2 for a, b in zip(p, g))
    rmse = math.sqrt(total / len(gold))
    return 100.0 * max(0.0, (base - rmse) / base)


def cf1(pred, key, config):
    id_col = config.get("id", "id")
    list_col = config.get("list", "quadruplets")
    fields = config.get("fields", ["aspect", "category", "opinion"])
    values = config.get("values", ["valence", "arousal"])
    d_max = math.sqrt(len(values)) * float(config.get("range", 8))
    gold = va_items(key, id_col, list_col, fields, values)
    guess = va_items(pred, id_col, list_col, fields, values)
    ids = {name[0] for name in gold}
    guess = {name: v for name, v in guess.items() if name[0] in ids}
    ctp = 0.0
    matched = 0
    for name, p in guess.items():
        g = gold.get(name)
        if g is None:
            continue
        matched += 1
        if all(a is not None and b is not None for a, b in zip(p, g)):
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(p, g))) / d_max
            ctp += max(0.0, 1 - dist)
    c_rec = ctp / len(gold) if gold else 0.0
    c_pre = ctp / len(guess) if guess else 0.0
    return 100.0 * (2 * c_pre * c_rec / (c_pre + c_rec) if c_pre + c_rec > 0 else 0.0)


def recall_at_1(pred, key, config):
    tol = float(config.get("tol", 10))
    if isinstance(key, dict) and "queries" in key:
        queries = {norm(k): number(v) for k, v in key["queries"].items()}
        places = {norm(k): number(v) for k, v in key.get("database", {}).items()}
        id_col, label = config.get("id", "query_id"), config.get("label", "winter_id")
    else:
        rows = table(key)
        id_col, label = cols(rows, config)
        queries = {norm(r.get(id_col)): number(r.get(label)) for r in rows}
        places = None
    guess = by_id(pred, id_col, (label,))
    hit = 0
    for q, pos in queries.items():
        said = norm(guess.get(q, {}).get(label))
        where = number(said) if places is None else places.get(said)
        hit += where is not None and pos is not None and abs(where - pos) <= tol
    return 100.0 * hit / len(queries) if queries else 0.0


def ppa(pred, key, config):
    key = table(key)
    if not key:
        return 0.0
    names = [c.strip() for c in key[0].keys()]
    id_col = config.get("id") or names[0]
    pieces = [c for c in names if c != id_col]
    prefix = config.get("prefix", "")
    guess = by_id(pred, id_col, pieces)
    right = total = 0
    for k in key:
        name = norm(k.get(id_col))
        if not name.startswith(prefix):
            continue
        g = guess.get(name, {})
        right += sum(norm(g.get(c)) == norm(k.get(c)) for c in pieces)
        total += len(pieces)
    return 100.0 * right / total if total else 0.0


def tokenize(text):
    text = norm(text).replace("\n", " ")
    text = re.sub(r"([\{-\~\[-\` -\&\(-\+\:-\@\/])", r" \1 ", text)
    text = re.sub(r"([^0-9])([\.,])", r"\1 \2 ", text)
    text = re.sub(r"([\.,])([^0-9])", r" \1 \2", text)
    text = re.sub(r"([0-9])(-)", r"\1 \2 ", text)
    return text.split()


def ngrams(tokens, n):
    return Counter(tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1))


def corpus_bleu(hyps, refs):
    match, total = [0] * 4, [0] * 4
    hyp_len = ref_len = 0
    for hyp, ref in zip(hyps, refs):
        h, r = tokenize(hyp), tokenize(ref)
        hyp_len += len(h)
        ref_len += len(r)
        for n in range(1, 5):
            hn, rn = ngrams(h, n), ngrams(r, n)
            match[n - 1] += sum(min(c, rn[g]) for g, c in hn.items())
            total[n - 1] += max(len(h) - n + 1, 0)
    if hyp_len == 0 or match[0] == 0:
        return 0.0
    smooth = 1.0
    log_sum = 0.0
    for m, t in zip(match, total):
        if t == 0:
            return 0.0
        if m == 0:
            smooth *= 2
            p = 1.0 / (smooth * t)
        else:
            p = m / t
        log_sum += math.log(p) / 4
    bp = 1.0 if hyp_len > ref_len else math.exp(1 - ref_len / hyp_len)
    return 100.0 * bp * math.exp(log_sum)


def bleu(pred, key, config):
    key = table(key)
    id_col, label = cols(key, config)
    guess = by_id(pred, id_col, (label,))
    hyps, refs = [], []
    for k in key:
        if norm(k.get(label)):
            refs.append(k.get(label))
            hyps.append(guess.get(norm(k.get(id_col)), {}).get(label))
    return corpus_bleu(hyps, refs)


METRICS = {
    "accuracy": accuracy, "f1": f1, "macro_f1": macro_f1, "triple_f1": triple_f1,
    "detect_f1": detect_f1, "align_f1": align_f1, "bleu": bleu, "rmse_gain": rmse_gain,
    "cf1": cf1, "recall_at_1": recall_at_1, "ppa": ppa,
}
