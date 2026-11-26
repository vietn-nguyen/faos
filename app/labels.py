TOPICS = {
    "array": "Mảng",
    "string": "Chuỗi",
    "recursion": "Đệ quy",
    "tree_graph": "Cây, đồ thị",
    "sorting": "Sắp xếp",
    "searching": "Tìm kiếm",
    "ml_basic": "Học máy cơ bản",
    "deep_learning": "Học sâu",
    "nlp": "Xử lý ngôn ngữ tự nhiên",
    "cv": "Thị giác máy tính",
    "gen_ai": "AI tạo sinh và LLM",
    "ai_tools": "Công cụ lập trình AI",
    "ai_math": "Toán cho AI",
    "data_analysis": "Phân tích dữ liệu",
}

ALGO_TOPICS = ("array", "string", "recursion", "tree_graph", "sorting", "searching")
AI_TOPICS = ("ml_basic", "deep_learning", "nlp", "cv", "gen_ai", "ai_tools", "ai_math", "data_analysis")

KINDS = {"code": "Bài toán lập trình", "question": "Câu hỏi trắc nghiệm", "predict": "Học máy nâng cao"}

METRICS = {
    "accuracy": "Accuracy",
    "f1": "F1",
    "macro_f1": "Macro F1",
    "triple_f1": "F1 bộ ba (trung bình theo miền)",
    "detect_f1": "F1 phát hiện và phân cấp",
    "align_f1": "F1 đối sánh ID",
    "bleu": "SacreBLEU",
    "rmse_gain": "Mức giảm RMSE so với baseline",
    "cf1": "Continuous F1 (cF1)",
    "recall_at_1": "Recall@1",
    "ppa": "Piece Position Accuracy (PPA)",
}

DATA_ROLES = {
    "train": "Tập huấn luyện",
    "public_test": "Public test",
    "private_test": "Private test",
    "public_key": "Nhãn public (ẩn)",
    "private_key": "Nhãn private (ẩn)",
    "other": "Tệp khác",
}

PHASES = {"public": "Public test", "private": "Private test"}

PRED_STATUSES = {
    "queued": "Đang chờ",
    "scoring": "Đang chấm",
    "done": "Đã chấm",
    "invalid": "File không hợp lệ",
    "system_error": "Lỗi hệ thống",
}

STANDARD_FIELDS = {
    "code": {"min_samples": "Số ví dụ mẫu tối thiểu", "min_tests": "Số test ẩn tối thiểu",
             "dup": "Ngưỡng trùng với ngân hàng (%)",
             "dup_hint": "Từ mức giống này nhờ Claude xét cùng ý tưởng (%)"},
    "question": {"min_explain": "Độ dài giải thích tối thiểu (ký tự)", "min_code": "Số câu có mã nguồn tối thiểu",
                 "dup": "Ngưỡng trùng với ngân hàng (%)",
             "dup_hint": "Từ mức giống này nhờ Claude xét cùng ý tưởng (%)"},
    "predict": {"min_rows": "Số dòng dữ liệu tối thiểu", "max_base": "Điểm tối đa của cách đoán lớp phổ biến",
                "min_gain": "Mã mẫu phải hơn cách đoán lớp phổ biến ít nhất (điểm)",
                "dup": "Ngưỡng trùng với ngân hàng (%)",
             "dup_hint": "Từ mức giống này nhờ Claude xét cùng ý tưởng (%)"},
}

DIFFICULTIES = {"easy": "Dễ", "medium": "Trung bình", "hard": "Khó"}

VERDICTS = {
    "AC": "Đúng (AC)",
    "WA": "Sai kết quả (WA)",
    "TLE": "Quá thời gian (TLE)",
    "RE": "Lỗi khi chạy (RE)",
    "CE": "Lỗi biên dịch (CE)",
}

ROLES = {"student": "Sinh viên", "supervisor": "Giám sát hệ thống", "admin": "Quản trị viên"}

KEYS = ("A", "B", "C", "D")

REJECT_REASONS = {
    "unclear": "Đề không rõ",
    "wrong_difficulty": "Sai độ khó",
    "weak_tests": "Test yếu",
    "duplicate": "Trùng đề",
    "wrong_solution": "Lời giải sai",
    "other": "Khác",
}

DRAFT_STATUSES = {
    "generating": "Đang tạo",
    "validating": "Đang kiểm tra",
    "failed": "Lỗi",
    "pending_review": "Chờ duyệt",
    "approved": "Đã duyệt",
    "rejected": "Bị từ chối",
}

SUBMISSION_STATUSES = {
    "queued": "Đang chờ",
    "judging": "Đang chấm",
    "done": "Đã chấm",
    "system_error": "Lỗi hệ thống",
}


def register_filters(app):
    tables = {
        "topic": TOPICS,
        "difficulty": DIFFICULTIES,
        "verdict": VERDICTS,
        "role": ROLES,
        "reason": REJECT_REASONS,
        "draft_status": DRAFT_STATUSES,
        "sub_status": SUBMISSION_STATUSES,
        "kind": KINDS,
        "metric": METRICS,
        "data_role": DATA_ROLES,
        "phase": PHASES,
        "pred_status": PRED_STATUSES,
    }
    for name, table in tables.items():
        app.add_template_filter(lambda v, t=table: t.get(v, v or ""), name)

    @app.template_filter("dt")
    def format_dt(value):
        return value.astimezone().strftime("%d/%m/%Y %H:%M:%S") if value else ""

    @app.template_filter("pts")
    def format_pts(value):
        return "—" if value is None else f"{value:.2f}"

    @app.template_filter("size")
    def format_size(value):
        value = value or 0
        return f"{value / 1048576:.1f} MB" if value >= 1048576 else f"{max(value // 1024, 1)} KB"

    app.jinja_env.globals.update(TOPICS=TOPICS, DIFFICULTIES=DIFFICULTIES, KEYS=KEYS,
                                 REJECT_REASONS=REJECT_REASONS, ALGO_TOPICS=ALGO_TOPICS,
                                 AI_TOPICS=AI_TOPICS, KINDS=KINDS, METRICS=METRICS,
                                 DATA_ROLES=DATA_ROLES, PHASES=PHASES)
