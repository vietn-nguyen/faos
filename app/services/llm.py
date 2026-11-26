import json

import anthropic
from flask import current_app

from ..labels import DIFFICULTIES, TOPICS

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statement": {"type": "string"},
        "input": {"type": "string"},
        "output": {"type": "string"},
        "constraints": {"type": "string"},
        "samples": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"input": {"type": "string"}, "output": {"type": "string"}},
                "required": ["input", "output"],
                "additionalProperties": False,
            },
        },
        "test_inputs": {"type": "array", "items": {"type": "string"}},
        "reference_solution": {"type": "string"},
        "brute_solution": {"type": "string"},
    },
    "required": ["title", "statement", "input", "output", "constraints",
                 "samples", "test_inputs", "reference_solution", "brute_solution"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Bạn là người ra đề cho một hệ thống luyện tập giải thuật dành cho sinh viên đại học.
Bạn viết đề bài lập trình mới, rõ ràng, bằng tiếng Việt, chấm tự động bằng so sánh output.

Yêu cầu với mỗi đề:
- Đề đọc input từ stdin và in output ra stdout. Output phải là duy nhất cho mỗi input
  (không có nhiều đáp án đúng), để có thể so sánh từng dòng.
- statement mô tả bài toán; input mô tả định dạng dữ liệu vào, output mô tả định dạng kết quả,
  constraints ghi rõ giới hạn dữ liệu.
- samples: 2 ví dụ nhỏ, output đúng chính xác.
- test_inputs: 8 input khác nhau gồm trường hợp thường, biên (rỗng/nhỏ nhất, lớn nhất theo
  constraints) và trường hợp dễ sai. Mỗi input là toàn bộ nội dung stdin. Giữ mỗi input dưới 2000 ký tự.
- reference_solution: lời giải Python 3.8 chuẩn, chỉ dùng thư viện chuẩn, đọc stdin, chạy
  dưới 1 giây với mọi test. Không in thêm gì ngoài đáp án.
- brute_solution: lời giải thứ hai viết độc lập theo cách vét cạn đơn giản nhất (có thể chậm), dùng để
  đối chiếu output với reference_solution. Python 3.8, chỉ thư viện chuẩn.
"""


def code_prompt(topic, difficulty):
    return (f"Viết một đề mới thuộc chủ đề \"{TOPICS[topic]}\", độ khó \"{DIFFICULTIES[difficulty]}\" "
            f"(mức sinh viên năm 2-3). Tránh các đề quá quen thuộc như tính tổng hai số.")


QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "code": {"type": "string"},
                    "op1": {"type": "string"},
                    "op2": {"type": "string"},
                    "op3": {"type": "string"},
                    "op4": {"type": "string"},
                    "key": {"type": "string", "enum": ["A", "B", "C", "D"]},
                    "explain": {"type": "string"},
                },
                "required": ["content", "code", "op1", "op2", "op3", "op4", "key", "explain"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "statement": {"type": "string"},
        "data_desc": {"type": "string"},
        "submit_format": {"type": "string"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "id_col": {"type": "string"},
        "label_col": {"type": "string"},
        "metric": {"type": "string", "enum": ["accuracy", "f1", "macro_f1"]},
        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
        "baseline": {"type": "string"},
    },
    "required": ["title", "statement", "data_desc", "submit_format", "columns", "id_col",
                 "label_col", "metric", "rows", "baseline"],
    "additionalProperties": False,
}

QUESTION_PROMPT = """Bạn là người ra đề trắc nghiệm cho hệ thống luyện thi Olympic Trí tuệ nhân tạo dành cho
sinh viên đại học. Bạn viết câu hỏi mới bằng tiếng Việt, thuật ngữ chuyên ngành giữ tiếng Anh khi cần.

Yêu cầu:
- questions: đúng 5 câu hỏi khác nhau, mỗi câu có 4 đáp án op1 đến op4 và đúng một đáp án đúng.
- key là chữ cái của đáp án đúng: A = op1, B = op2, C = op3, D = op4. Chia đều vị trí đáp án đúng.
- Câu hỏi kiểm tra hiểu biết hoặc tính toán, không hỏi mẹo. Đáp án sai phải hợp lý.
- code: đoạn mã Python ngắn (PyTorch, NumPy, pandas, scikit-learn, Hugging Face) nếu câu hỏi cần đọc mã,
  ngược lại để chuỗi rỗng. Ít nhất 1 câu có mã.
- explain: giải thích ngắn vì sao đáp án đúng, 1 đến 3 câu.
- Không dùng hình ảnh. Công thức viết bằng văn bản thường.
"""

TASK_PROMPT = """Bạn là người ra đề tác vụ cho hệ thống luyện thi Olympic Trí tuệ nhân tạo dành cho sinh viên
đại học. Bạn thiết kế một tác vụ phân loại nhỏ kèm bộ dữ liệu tự tạo, viết bằng tiếng Việt.
Sinh viên tải dữ liệu, huấn luyện mô hình ở máy của mình rồi nộp file dự đoán submission.csv.

Yêu cầu:
- statement: bối cảnh và nhiệm vụ. data_desc: mô tả từng cột. submit_format: mô tả file submission.csv
  gồm 2 cột là id_col và label_col.
- columns: tên các cột của dữ liệu, có id_col (mã dòng duy nhất) và label_col (nhãn cần dự đoán).
  Dữ liệu là văn bản ngắn hoặc bảng số liệu, 3 đến 8 cột.
- rows: 100 đến 150 dòng dữ liệu, mỗi dòng là mảng chuỗi theo đúng thứ tự columns. Dữ liệu phải
  đa dạng, có quy luật học được nhưng không tầm thường, nhãn có 2 đến 5 lớp và không quá lệch.
- metric: accuracy, f1 (nhị phân, lớp dương là "1") hoặc macro_f1 (nhiều lớp).
- baseline: mã Python 3.8 mẫu ngắn, chỉ dùng thư viện chuẩn (csv, collections, math), đọc train.csv và
  public_test.csv trong thư mục hiện tại, ghi submission.csv. Mô hình đơn giản nhưng phải tốt hơn đoán lớp
  phổ biến nhất. Hệ thống sẽ chạy thử đoạn mã này.
"""

PROMPTS = {"code": SYSTEM_PROMPT, "question": QUESTION_PROMPT, "predict": TASK_PROMPT}
SCHEMAS = {"code": DRAFT_SCHEMA, "question": QUESTION_SCHEMA, "predict": TASK_SCHEMA}


def context_prompt(context):
    parts = []
    if context["examples"]:
        items = json.dumps([e["item"] for e in context["examples"]], ensure_ascii=False, indent=1)
        parts.append("Các đề mẫu trong ngân hàng đề. Viết đề mới cùng văn phong, cùng mức chi tiết và "
                     "cùng mức độ khó, không chép lại nội dung:\n" + items)
    if context["titles"]:
        parts.append("Các đề cùng chủ đề đã có trong ngân hàng. Đề mới không được trùng ý tưởng với các đề này:\n"
                     + "\n".join(f"- {t}" for t in context["titles"]))
    if context["rejects"]:
        parts.append("Các bản nháp trước của chủ đề này đã bị người duyệt từ chối vì các lý do sau, cần tránh:\n"
                     + "\n".join(f"- {r}" for r in context["rejects"]))
    return "\n\n".join(parts)


def user_prompt(kind, topic, difficulty, context=None):
    if kind == "code":
        text = code_prompt(topic, difficulty)
    else:
        what = "5 câu hỏi trắc nghiệm" if kind == "question" else "một tác vụ"
        text = (f"Viết {what} thuộc chủ đề \"{TOPICS[topic]}\", độ khó \"{DIFFICULTIES[difficulty]}\" "
                f"(mức thi Olympic Trí tuệ nhân tạo sinh viên).")
    extra = context_prompt(context) if context else ""
    return f"{text}\n\n{extra}" if extra else text


SAME_SCHEMA = {
    "type": "object",
    "properties": {"duplicate_of": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["duplicate_of", "reason"],
    "additionalProperties": False,
}

SAME_PROMPT = """Bạn kiểm tra đề trùng cho ngân hàng đề. Hai đề là trùng khi cùng ý tưởng cốt lõi
(cùng bài toán, cùng kiến thức được hỏi), dù cách diễn đạt, tên biến hay số liệu khác nhau.
Trả về duplicate_of là id của đề trùng, hoặc -1 nếu không có đề nào trùng. reason: một câu ngắn."""


def get_client():
    return anthropic.Anthropic(api_key=current_app.config["ANTHROPIC_API_KEY"] or None)


def ask(system, content, schema, max_tokens, effort):
    with get_client().beta.messages.stream(
        model=current_app.config["CLAUDE_MODEL"],
        max_tokens=max_tokens,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=system,
        messages=[{"role": "user", "content": content}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("LLM từ chối yêu cầu này (refusal)")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("LLM trả về bị cắt (max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), response.usage


def callAPI(kind, topic, difficulty, rules=None, context=None):
    return ask(rules or PROMPTS[kind], user_prompt(kind, topic, difficulty, context), SCHEMAS[kind], 64000, "medium")


def sameIdea(text, candidates):
    items = "\n\n".join(f"[id {n}]\n{c['text'][:1500]}" for n, c in enumerate(candidates, 1))
    content = f"Đề mới:\n{text[:3000]}\n\nCác đề gần giống nhất trong ngân hàng:\n{items}"
    out, usage = ask(SAME_PROMPT, content, SAME_SCHEMA, 4000, "low")
    n = out["duplicate_of"]
    return (candidates[n - 1] if 1 <= n <= len(candidates) else None), out["reason"], usage
