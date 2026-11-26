import base64
import time

import requests
from flask import current_app

BATCH_SIZE = 20
POLL_INTERVAL = 0.5
POLL_TIMEOUT = 90


def map_status(status_id):
    if status_id in (3, 4):
        return "ok"
    if status_id == 5:
        return "TLE"
    if status_id == 6:
        return "CE"
    if 7 <= status_id <= 12:
        return "RE"
    return "error"


def b64(text):
    return base64.b64encode((text or "").encode("utf-8")).decode("ascii")


def unb64(text):
    return base64.b64decode(text).decode("utf-8", errors="replace") if text else ""


def get_headers():
    headers = {"Content-Type": "application/json"}
    token = current_app.config["JUDGE0_AUTH_TOKEN"]
    if token:
        headers["X-Auth-Token"] = token
    return headers


def format_result(status, stdout="", stderr="", time_s=None, memory=None, token=None):
    return {"status": status, "stdout": stdout, "stderr": stderr,
            "time": time_s, "memory": memory, "token": token}


def outputsMatch(actual, expected):
    def norm(s):
        lines = [line.rstrip() for line in (s or "").replace("\r\n", "\n").split("\n")]
        while lines and lines[-1] == "":
            lines.pop()
        return lines
    return norm(actual) == norm(expected)


def runBatch(code, stdins, timeLimit=2.0, memLimit=128):
    results = []
    for start in range(0, len(stdins), BATCH_SIZE):
        batch = stdins[start:start + BATCH_SIZE]
        try:
            results.extend(run_one_batch(code, batch, timeLimit, memLimit))
        except TimeoutError as e:
            results.extend(format_result("error", stderr=str(e)) for _ in batch)
    return results


def run_one_batch(code, stdins, timeLimit, memLimit):
    base = current_app.config["JUDGE0_URL"]
    body = {"submissions": [{
        "language_id": current_app.config["JUDGE0_PYTHON_ID"],
        "source_code": b64(code),
        "stdin": b64(stdin),
        "cpu_time_limit": timeLimit,
        "wall_time_limit": max(timeLimit * 3, 5),
        "memory_limit": int(memLimit * 1024),
    } for stdin in stdins]}

    resp = requests.post(f"{base}/submissions/batch?base64_encoded=true",
                         json=body, headers=get_headers(), timeout=30)
    resp.raise_for_status()
    tokens = [item.get("token") for item in resp.json()]
    if not all(tokens):
        raise RuntimeError(f"judge0 rejected the batch: {resp.text[:300]}")

    fields = "token,status,stdout,stderr,compile_output,time,memory"
    deadline = time.time() + POLL_TIMEOUT
    while True:
        r = requests.get(f"{base}/submissions/batch",
                         params={"tokens": ",".join(tokens), "base64_encoded": "true",
                                 "fields": fields},
                         headers=get_headers(), timeout=30)
        r.raise_for_status()
        subs = r.json()["submissions"]
        if all(s["status"]["id"] not in (1, 2) for s in subs):
            break
        if time.time() > deadline:
            raise TimeoutError("judge0 batch timed out")
        time.sleep(POLL_INTERVAL)

    return [format_result(map_status(s["status"]["id"]), unb64(s.get("stdout")),
                          (unb64(s.get("stderr")) or unb64(s.get("compile_output")))[:4000],
                          float(s["time"]) if s.get("time") else None, s.get("memory"), s["token"])
            for s in subs]


def get_verdict(result, expected):
    if result["status"] == "ok":
        return "AC" if outputsMatch(result["stdout"], expected) else "WA"
    if result["status"] in ("TLE", "RE", "CE"):
        return result["status"]
    return None
