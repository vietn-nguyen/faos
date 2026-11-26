import csv
import io
import json
import math
import random
import zipfile
from datetime import datetime, timedelta, timezone

import click
from flask import current_app
from psycopg.types.json import Jsonb

from .db import connect
from .services import storage

QUESTIONS = [
    ("Trong học có giám sát, tập validation dùng để làm gì?", "",
     "Huấn luyện tham số của mô hình", "Chọn siêu tham số và phát hiện overfitting",
     "Báo cáo kết quả cuối cùng", "Tăng số lượng dữ liệu huấn luyện", "B", "ml_basic", "easy",
     "Tập validation không dùng để cập nhật tham số mà để chọn siêu tham số và theo dõi overfitting."),
    ("Mô hình có sai số huấn luyện rất thấp nhưng sai số kiểm tra cao. Hiện tượng này là gì?", "",
     "Underfitting", "Overfitting", "Data leakage", "Vanishing gradient", "B", "ml_basic", "easy",
     "Khoảng cách lớn giữa sai số huấn luyện và kiểm tra là dấu hiệu của overfitting."),
    ("Một bộ phân loại có TP = 40, FP = 10, FN = 20. Precision và Recall lần lượt là?", "",
     "0,80 và 0,67", "0,67 và 0,80", "0,80 và 0,50", "0,50 và 0,80", "A", "ml_basic", "medium",
     "Precision = 40 / (40 + 10) = 0,80; Recall = 40 / (40 + 20) ≈ 0,67."),
    ("Với dữ liệu mất cân bằng nặng giữa các lớp, độ đo nào phản ánh công bằng hơn accuracy?", "",
     "Macro F1", "Số tham số của mô hình", "Thời gian huấn luyện", "Top-5 accuracy", "A", "ml_basic", "easy",
     "Macro F1 lấy trung bình F1 của từng lớp nên lớp hiếm có trọng số ngang lớp phổ biến."),
    ("Trong k-fold cross-validation với k = 5, mỗi mẫu dữ liệu được dùng làm validation bao nhiêu lần?", "",
     "0 lần", "1 lần", "4 lần", "5 lần", "B", "ml_basic", "easy",
     "Mỗi mẫu nằm trong đúng một fold nên làm validation đúng một lần và làm huấn luyện 4 lần."),
    ("Regularization L1 khác L2 ở điểm nào?", "",
     "L1 làm nhiều trọng số bằng đúng 0, tạo mô hình thưa", "L1 luôn cho sai số thấp hơn",
     "L2 không phạt trọng số lớn", "L1 chỉ dùng được cho mạng nơ-ron", "A", "ml_basic", "medium",
     "Phạt theo trị tuyệt đối đẩy nhiều trọng số về đúng 0, còn L2 chỉ làm trọng số nhỏ dần."),
    ("Hàm kích hoạt nào giúp giảm hiện tượng vanishing gradient tốt hơn sigmoid trong mạng sâu?", "",
     "tanh", "ReLU", "Hàm bước", "Softmax", "B", "deep_learning", "easy",
     "Đạo hàm của ReLU bằng 1 ở vùng dương nên gradient không bị thu nhỏ qua nhiều lớp."),
    ("Dropout với p = 0,5 hoạt động thế nào khi suy luận (model.eval())?", "",
     "Vẫn tắt ngẫu nhiên 50% nơ-ron", "Không tắt nơ-ron nào",
     "Tắt cố định nửa đầu số nơ-ron", "Nhân đôi đầu ra của mọi nơ-ron", "B", "deep_learning", "medium",
     "Ở chế độ eval, dropout là phép đồng nhất; việc chia tỉ lệ đã được làm lúc huấn luyện."),
    ("Lớp Conv2d có 3 kênh vào, 16 kênh ra, kernel 3×3, có bias. Số tham số là bao nhiêu?", "",
     "432", "448", "144", "160", "B", "deep_learning", "medium",
     "3 × 16 × 3 × 3 = 432 trọng số, cộng 16 bias là 448."),
    ("Kết nối tắt (skip connection) trong ResNet có tác dụng chính là gì?", "",
     "Giảm số tham số", "Giúp gradient truyền qua mạng rất sâu dễ hơn",
     "Thay thế hàm kích hoạt", "Tăng độ phân giải ảnh", "B", "deep_learning", "medium",
     "Nhánh đồng nhất cho gradient một đường đi thẳng nên mạng rất sâu vẫn huấn luyện được."),
    ("Đoạn mã sau in ra gì?",
     "import torch\nx = torch.zeros(8, 3, 32, 32)\nconv = torch.nn.Conv2d(3, 16, kernel_size=3, stride=2, padding=1)\nprint(conv(x).shape)",
     "torch.Size([8, 16, 32, 32])", "torch.Size([8, 16, 16, 16])",
     "torch.Size([8, 16, 15, 15])", "torch.Size([8, 3, 16, 16])", "B", "deep_learning", "medium",
     "Kích thước ra = floor((32 + 2×1 − 3) / 2) + 1 = 16, số kênh ra là 16."),
    ("Learning rate quá lớn thường gây ra điều gì?", "",
     "Hội tụ chậm nhưng ổn định", "Loss dao động mạnh hoặc phân kỳ",
     "Mô hình luôn underfitting", "Không ảnh hưởng tới huấn luyện", "B", "deep_learning", "easy",
     "Bước cập nhật quá lớn làm tham số vượt qua điểm cực tiểu nên loss dao động hoặc tăng."),
    ("Trong tiền xử lý văn bản, tokenization là bước nào?", "",
     "Tách văn bản thành các đơn vị như từ hoặc subword", "Chuyển chữ hoa thành chữ thường",
     "Loại bỏ stop word", "Gán nhãn từ loại", "A", "nlp", "easy",
     "Tokenization chia chuỗi ký tự thành token để mô hình xử lý."),
    ("Trong Transformer, positional encoding dùng để làm gì?", "",
     "Giảm số tham số", "Cung cấp thông tin thứ tự của token",
     "Thay cho cơ chế attention", "Chuẩn hoá đầu ra", "B", "nlp", "medium",
     "Self-attention không phân biệt thứ tự nên cần cộng thêm thông tin vị trí."),
    ("BLEU đo điều gì giữa bản dịch máy và bản dịch tham chiếu?", "",
     "Độ trùng khớp n-gram, có phạt bản dịch quá ngắn", "Khoảng cách chỉnh sửa theo ký tự",
     "Độ tương đồng embedding", "Xác suất của câu theo mô hình ngôn ngữ", "A", "nlp", "medium",
     "BLEU là trung bình hình học của precision n-gram nhân với brevity penalty."),
    ("Trong bài toán ABSA, bộ ba (aspect, category, sentiment) của câu \"Màn hình đẹp nhưng pin yếu\" có mấy phần tử?", "",
     "1", "2", "3", "4", "B", "nlp", "medium",
     "Có hai khía cạnh được nhận xét: màn hình (tích cực) và pin (tiêu cực)."),
    ("Mô hình BERT thuộc kiến trúc nào?", "",
     "Encoder-only", "Decoder-only", "Encoder-decoder", "Mạng tích chập", "A", "nlp", "easy",
     "BERT chỉ dùng khối encoder của Transformer và được huấn luyện với masked language modeling."),
    ("Phép tăng cường dữ liệu nào KHÔNG phù hợp khi phân loại chữ số viết tay 6 và 9?", "",
     "Dịch chuyển vài pixel", "Xoay 180 độ", "Thêm nhiễu nhẹ", "Thay đổi độ sáng", "B", "cv", "medium",
     "Xoay 180 độ biến 6 thành 9 nên làm sai nhãn."),
    ("IoU giữa hai hộp bằng nhau hoàn toàn và giữa hai hộp không giao nhau lần lượt là?", "",
     "1 và 0", "0 và 1", "0,5 và 0", "1 và 0,5", "A", "cv", "easy",
     "IoU = diện tích giao / diện tích hợp, nên trùng hoàn toàn cho 1, không giao cho 0."),
    ("Max pooling 2×2 với stride 2 trên feature map 28×28 cho kích thước nào?", "",
     "27×27", "14×14", "56×56", "13×13", "B", "cv", "easy",
     "Mỗi chiều giảm một nửa: 28 / 2 = 14."),
    ("Transfer learning với mô hình tiền huấn luyện trên ImageNet có lợi nhất khi nào?", "",
     "Dữ liệu của bài toán mới ít", "Dữ liệu của bài toán mới rất nhiều và khác hẳn",
     "Không có GPU", "Bài toán không liên quan tới ảnh", "A", "cv", "medium",
     "Đặc trưng đã học giúp mô hình đạt kết quả tốt dù tập dữ liệu mới nhỏ."),
    ("Tham số temperature của LLM càng cao thì đầu ra thế nào?", "",
     "Ngẫu nhiên và đa dạng hơn", "Ngắn hơn", "Luôn chính xác hơn", "Không thay đổi", "A", "gen_ai", "easy",
     "Temperature cao làm phân phối xác suất phẳng hơn nên token ít khả năng cũng dễ được chọn."),
    ("RAG (Retrieval-Augmented Generation) bổ sung gì cho LLM?", "",
     "Thêm lớp attention", "Tài liệu truy xuất được đưa vào ngữ cảnh trước khi sinh câu trả lời",
     "Huấn luyện lại toàn bộ mô hình", "Giảm kích thước mô hình", "B", "gen_ai", "medium",
     "RAG tìm tài liệu liên quan rồi chèn vào prompt để câu trả lời bám theo nguồn."),
    ("LoRA tinh chỉnh mô hình lớn bằng cách nào?", "",
     "Cập nhật toàn bộ trọng số", "Học các ma trận hạng thấp cộng vào trọng số gốc đã đóng băng",
     "Xoá bớt các lớp", "Lượng tử hoá trọng số về 1 bit", "B", "gen_ai", "hard",
     "LoRA giữ nguyên trọng số gốc và chỉ huấn luyện hai ma trận hạng thấp nên rất ít tham số."),
    ("Trong mô hình diffusion, quá trình thuận (forward) làm gì?", "",
     "Thêm nhiễu dần vào dữ liệu", "Khử nhiễu dần", "Nén ảnh", "Phân loại ảnh", "A", "gen_ai", "medium",
     "Quá trình thuận thêm nhiễu Gauss từng bước; mô hình học quá trình ngược để khử nhiễu."),
    ("Đoạn mã pandas sau trả về gì?",
     "import pandas as pd\ndf = pd.DataFrame({'lop': ['A', 'A', 'B'], 'diem': [8, 6, 9]})\nprint(df.groupby('lop')['diem'].mean()['A'])",
     "8.0", "7.0", "6.0", "14.0", "B", "ai_tools", "easy",
     "Lớp A có hai điểm 8 và 6 nên trung bình là 7.0."),
    ("Trong vòng lặp huấn luyện PyTorch, thứ tự đúng của ba lệnh là gì?", "",
     "loss.backward(), optimizer.zero_grad(), optimizer.step()",
     "optimizer.zero_grad(), loss.backward(), optimizer.step()",
     "optimizer.step(), loss.backward(), optimizer.zero_grad()",
     "loss.backward(), optimizer.step(), không cần zero_grad()", "B", "ai_tools", "medium",
     "Xoá gradient cũ, lan truyền ngược để tính gradient mới, rồi cập nhật tham số."),
    ("Đoạn mã scikit-learn sau có lỗi phương pháp nào?",
     "scaler = StandardScaler().fit(X)\nX_train, X_test = train_test_split(scaler.transform(X))",
     "Không có lỗi", "Rò rỉ dữ liệu: scaler được fit trên cả tập test",
     "Thiếu random_state nên không chạy", "StandardScaler không dùng được với train_test_split", "B",
     "ai_tools", "medium",
     "Phải chia dữ liệu trước rồi chỉ fit scaler trên tập huấn luyện."),
    ("Kết quả của đoạn mã NumPy sau là gì?",
     "import numpy as np\na = np.array([[1, 2], [3, 4]])\nprint((a * a).sum())",
     "30", "54", "10", "100", "A", "ai_tools", "easy",
     "Phép * nhân từng phần tử: 1 + 4 + 9 + 16 = 30."),
    ("Đạo hàm của hàm sigmoid σ(x) là gì?", "",
     "σ(x)(1 − σ(x))", "1 − σ(x)²", "σ(x)²", "max(0, x)", "A", "ai_math", "medium",
     "Đạo hàm của sigmoid viết được theo chính nó: σ'(x) = σ(x)(1 − σ(x))."),
    ("Cho hai vector a = (1, 2) và b = (2, −1). Cosine similarity của chúng bằng?", "",
     "1", "0", "−1", "0,5", "B", "ai_math", "easy",
     "Tích vô hướng 1×2 + 2×(−1) = 0 nên hai vector vuông góc."),
    ("Cross-entropy của dự đoán p = 0,25 cho lớp đúng (dùng log cơ số 2) là?", "",
     "0,25", "1", "2", "4", "C", "ai_math", "medium",
     "−log2(0,25) = 2."),
    ("Một xét nghiệm có P(dương | bệnh) = 0,9; P(dương | không bệnh) = 0,1; tỉ lệ bệnh là 10%. P(bệnh | dương) bằng?", "",
     "0,9", "0,5", "0,1", "0,09", "B", "ai_math", "hard",
     "Bayes: 0,9×0,1 / (0,9×0,1 + 0,1×0,9) = 0,09 / 0,18 = 0,5."),
    ("Khi một cột số có vài giá trị ngoại lai rất lớn, đại lượng nào mô tả trung tâm dữ liệu tốt hơn?", "",
     "Trung bình", "Trung vị", "Giá trị lớn nhất", "Phương sai", "B", "data_analysis", "easy",
     "Trung vị ít bị ảnh hưởng bởi giá trị ngoại lai hơn trung bình."),
    ("Hệ số tương quan Pearson giữa hai biến bằng −0,95 cho biết điều gì?", "",
     "Hai biến gần như không liên quan", "Quan hệ tuyến tính nghịch rất mạnh",
     "Biến này gây ra biến kia", "Quan hệ tuyến tính thuận rất mạnh", "B", "data_analysis", "easy",
     "Giá trị gần −1 là quan hệ tuyến tính nghịch mạnh; tương quan không khẳng định nhân quả."),
    ("Cách xử lý giá trị thiếu nào dễ gây rò rỉ dữ liệu?", "",
     "Điền trung vị tính trên tập huấn luyện", "Điền trung bình tính trên toàn bộ dữ liệu gồm cả tập test",
     "Bỏ các dòng thiếu trong tập huấn luyện", "Thêm cột đánh dấu giá trị thiếu", "B", "data_analysis", "medium",
     "Thống kê dùng để điền phải được tính chỉ trên tập huấn luyện."),
]


def to_csv(rows, cols):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def to_jsonl(rows):
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def to_json(data):
    return json.dumps(data, ensure_ascii=False, indent=1)


def to_zip(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in files:
            z.writestr(name, text)
    return out.getvalue()


def cut(rows, n_pub, n_pri):
    return rows[:-(n_pub + n_pri)], rows[-(n_pub + n_pri):-n_pri], rows[-n_pri:]


def without(rows, cols):
    return [{k: v for k, v in r.items() if k not in cols} for r in rows]


def sentiment_task():
    rnd = random.Random(11)
    things = ["Điện thoại", "Tai nghe", "Laptop", "Bàn phím", "Màn hình", "Sạc dự phòng", "Loa", "Chuột"]
    parts = ["pin", "thiết kế", "âm thanh", "giá", "độ bền", "đóng gói", "giao hàng", "màn hình"]
    words = {"POS": ["rất tốt", "tuyệt vời", "đáng tiền", "ổn áp", "vượt mong đợi", "xuất sắc"],
             "NEG": ["quá tệ", "thất vọng", "kém", "không đáng tiền", "hay lỗi", "tệ hại"],
             "NEU": ["bình thường", "tạm được", "không có gì đặc biệt", "ở mức trung bình", "như mô tả"]}
    tails = ["", ", sẽ mua lại", ", dùng một tuần rồi", ", shop phản hồi chậm", ", mình mua lúc giảm giá", ""]
    rows = []
    for i in range(360):
        label = rnd.choice(list(words))
        text = f"{rnd.choice(things)} có {rnd.choice(parts)} {rnd.choice(words[label])}{rnd.choice(tails)}."
        if rnd.random() < 0.12:
            other = rnd.choice([k for k in words if k != label])
            text = f"{text[:-1]}, dù {rnd.choice(parts)} {rnd.choice(words[other])}."
        rows.append({"id": f"R{i:04d}", "text": text, "label": label})
    train, pub, pri = cut(rows, 60, 60)
    return {
        "title": "Phân loại cảm xúc bình luận sản phẩm", "topic": "nlp", "difficulty": "easy",
        "statement": "Cho các bình luận ngắn tiếng Việt về sản phẩm điện tử. Hãy xây dựng mô hình phân loại "
                     "mỗi bình luận vào một trong ba lớp cảm xúc: POS (khen), NEG (chê), NEU (trung tính).",
        "dataDesc": "train.csv: id, text, label.\npublic_test.csv, private_test.csv: id, text (không có nhãn).",
        "submitFormat": "Nộp file submission.csv (hoặc file .zip chứa submission.csv và notebook) gồm 2 cột:\n"
                        "id,label\nR0300,POS\nR0301,NEG",
        "baseline": "import pandas as pd\nfrom sklearn.feature_extraction.text import TfidfVectorizer\n"
                    "from sklearn.linear_model import LogisticRegression\nfrom sklearn.pipeline import make_pipeline\n\n"
                    "train = pd.read_csv('train.csv')\ntest = pd.read_csv('public_test.csv')\n"
                    "model = make_pipeline(TfidfVectorizer(), LogisticRegression(max_iter=1000))\n"
                    "model.fit(train['text'], train['label'])\n"
                    "test[['id']].assign(label=model.predict(test['text'])).to_csv('submission.csv', index=False)\n",
        "metrics": [("Macro F1", "macro_f1", "submission.csv", {"id": "id", "label": "label"}, 1, 30, None)],
        "files": [("train", "train.csv", to_csv(train, ["id", "text", "label"])),
                  ("public_test", "public_test.csv", to_csv(pub, ["id", "text"])),
                  ("private_test", "private_test.csv", to_csv(pri, ["id", "text"])),
                  ("public_key", "submission.csv", to_csv(pub, ["id", "label"])),
                  ("private_key", "submission.csv", to_csv(pri, ["id", "label"]))],
    }


def teencode_task():
    rnd = random.Random(12)
    slang = {"không": "ko", "được": "dc", "gì": "j", "với": "vs", "biết": "bít", "rồi": "r", "bạn": "bn",
             "mình": "mk", "yêu": "iu", "quá": "wá", "vậy": "z", "thôi": "thui", "người": "ng", "trời": "tr"}
    subjects = ["mình", "bạn", "người ta", "bọn mình", "bạn ấy"]
    verbs = ["không biết làm gì", "đi học với bạn rồi", "yêu môn này quá", "được điểm cao rồi",
             "không hiểu bài này", "làm bài với mình thôi", "biết vậy rồi", "nói gì vậy trời",
             "được nghỉ học rồi", "không đi được với bạn"]
    tails = ["", " đó", " nha", " hôm nay", " thật sự"]
    rows, seen = [], set()
    while len(rows) < 300:
        clean = f"{rnd.choice(subjects)} {rnd.choice(verbs)}{rnd.choice(tails)}"
        if rnd.random() < 0.65:
            text = " ".join(slang.get(w, w) if rnd.random() < 0.85 else w for w in clean.split())
            row = {"van_ban_goc": text, "nhan": "1" if text != clean else "0",
                   "ban_dich": clean if text != clean else ""}
        else:
            row = {"van_ban_goc": clean, "nhan": "0", "ban_dich": ""}
        if row["van_ban_goc"] not in seen:
            seen.add(row["van_ban_goc"])
            rows.append(row)
        if len(seen) > 280:
            tails.append(f" lần {len(seen)}")
    train, pub, pri = cut(rows, 50, 50)
    cols = ["van_ban_goc", "nhan", "ban_dich"]
    blank = lambda part: to_csv(without(part, ("nhan", "ban_dich")), cols)
    return {
        "title": "Nhận diện và chuẩn hoá teencode", "topic": "nlp", "difficulty": "medium",
        "statement": "Mỗi dòng là một câu tiếng Việt. Nhiệm vụ gồm hai phần, mô phỏng tác vụ phân loại và dịch "
                     "của VOAI 2025:\n1. Phân loại: nhan = 1 nếu câu viết bằng teencode, 0 nếu là tiếng Việt chuẩn.\n"
                     "2. Dịch: với câu teencode, viết lại thành tiếng Việt chuẩn ở cột ban_dich; câu chuẩn thì để trống.",
        "dataDesc": "train.csv: van_ban_goc, nhan, ban_dich.\npublic_test.csv, private_test.csv: cùng 3 cột "
                    "nhưng nhan và ban_dich để trống.",
        "submitFormat": "Nộp file output.csv gồm 3 cột van_ban_goc, nhan, ban_dich đã điền đầy đủ, mã hoá UTF-8, "
                        "dùng dấu phẩy làm phân cách.",
        "baseline": "import pandas as pd\n\ntest = pd.read_csv('public_test.csv')\n"
                    "test['nhan'] = 1\ntest['ban_dich'] = test['van_ban_goc']\ntest.to_csv('output.csv', index=False)\n",
        "metrics": [("Điểm phân loại", "accuracy", "output.csv", {"id": "van_ban_goc", "label": "nhan"}, 0.2, 60, None),
                    ("Điểm dịch thuật", "bleu", "output.csv", {"id": "van_ban_goc", "label": "ban_dich"}, 0.8, 20, None)],
        "files": [("train", "train.csv", to_csv(train, cols)),
                  ("public_test", "public_test.csv", blank(pub)), ("private_test", "private_test.csv", blank(pri)),
                  ("public_key", "output.csv", to_csv(pub, cols)), ("private_key", "output.csv", to_csv(pri, cols))],
    }


def absa_task():
    rnd = random.Random(13)
    bank = {
        "Restaurant": [("phở", "Food#Quality"), ("nước dùng", "Food#Quality"), ("nhân viên", "Service#General"),
                       ("không gian", "Ambience#General"), ("giá", "Restaurant#Prices"), ("trà đá", "Drinks#Quality")],
        "Laptop": [("màn hình", "Display#General"), ("bàn phím", "Keyboard#General"), ("pin", "Battery#General"),
                   ("quạt", "Fans#General"), ("giá", "Laptop#Price"), ("loa", "Multimedia#General")],
    }
    words = {"POS": ["rất tốt", "ổn", "tuyệt"], "NEG": ["tệ", "kém", "đáng thất vọng"], "NEU": ["bình thường", "tạm được"]}
    general = {"Restaurant": "Restaurant#General", "Laptop": "Laptop#General"}

    def make(domain, n):
        out, seen = [], set()
        while len(out) < n:
            if rnd.random() < 0.12:
                s = rnd.choice(["POS", "NEG"])
                text = f"Nói chung {'rất hài lòng' if s == 'POS' else 'không hài lòng'} lần {len(out) + 1}."
                triples = [{"aspect": "NULL", "category": general[domain], "sentiment": s}]
            else:
                picks = rnd.sample(bank[domain], rnd.choice([1, 2, 2]))
                chunks, triples = [], []
                for aspect, cat in picks:
                    s = rnd.choice(list(words))
                    chunks.append(f"{aspect} {rnd.choice(words[s])}")
                    triples.append({"aspect": aspect, "category": cat, "sentiment": s})
                text = (" nhưng " if len(chunks) == 2 and rnd.random() < 0.5 else ", ").join(chunks).capitalize()
                text += rnd.choice([".", " lắm.", " thật.", f", lần thứ {rnd.randint(2, 30)} dùng.", " nhé."])
            if text not in seen:
                seen.add(text)
                out.append({"raw_words": text, "triples": triples})
        return out

    data = {d: make(d, 150) for d in bank}
    part = lambda a, b: {d: rows[a:b] for d, rows in data.items()}
    hide = lambda p: {d: [{"raw_words": r["raw_words"]} for r in rows] for d, rows in p.items()}
    return {
        "title": "Trích xuất bộ ba khía cạnh, danh mục, cảm xúc (ACSTE)", "topic": "nlp", "difficulty": "hard",
        "statement": "Với mỗi câu đánh giá thuộc hai miền Restaurant và Laptop, hãy liệt kê các bộ ba "
                     "(aspect, category, sentiment). aspect là cụm từ chỉ khía cạnh trong câu, dùng NULL khi "
                     "khía cạnh ẩn; category thuộc danh mục định sẵn của từng miền; sentiment thuộc {POS, NEG, NEU}.",
        "dataDesc": "train.json: đối tượng theo miền, mỗi phần tử có raw_words và triples.\n"
                    "public_test.json, private_test.json: chỉ có raw_words.",
        "submitFormat": "Nộp file submission.zip chứa submission.json (kèm notebook nếu có). submission.json:\n"
                        "{\"Restaurant\": [{\"raw_words\": \"...\", \"triples\": [{\"aspect\": \"...\", "
                        "\"category\": \"...\", \"sentiment\": \"POS\"}]}], \"Laptop\": [...]}\n"
                        "raw_words phải khớp với tập kiểm tra. So khớp chính xác cả ba thành phần.",
        "baseline": "import json\n\ntest = json.load(open('public_test.json', encoding='utf-8'))\n"
                    "out = {d: [{'raw_words': r['raw_words'], 'triples': []} for r in rows] for d, rows in test.items()}\n"
                    "json.dump(out, open('submission.json', 'w', encoding='utf-8'), ensure_ascii=False)\n",
        "metrics": [("F1 bộ ba", "triple_f1", "submission.json", {}, 1, 10, None)],
        "files": [("train", "train.json", to_json(part(0, 100))),
                  ("public_test", "public_test.json", to_json(hide(part(100, 125)))),
                  ("private_test", "private_test.json", to_json(hide(part(125, 150)))),
                  ("public_key", "submission.json", to_json(part(100, 125))),
                  ("private_key", "submission.json", to_json(part(125, 150)))],
    }


def storm_task():
    rnd = random.Random(14)
    rows = []
    for i in range(400):
        negative = rnd.random() < 0.3
        level = 0 if negative else rnd.randint(1, 4)
        wind = rnd.gauss(18 if negative else 25 + level * 22, 7)
        rows.append({"file_name": f"{201801010000 + i * 300}_{i:04d}.jpg",
                     "wind_kt": round(max(wind, 0), 1),
                     "pressure_hpa": round(1012 - level * 17 + rnd.gauss(0, 6), 1),
                     "cloud_top_c": round(-35 - level * 9 + rnd.gauss(0, 6), 1),
                     "eye_score": round(min(max(level / 4 + rnd.gauss(0, 0.18), 0), 1), 2),
                     "is_negative": "TRUE" if negative else "FALSE",
                     "category_id": "" if negative else str(level)})
    train, pub, pri = cut(rows, 80, 80)
    feats = ["file_name", "wind_kt", "pressure_hpa", "cloud_top_c", "eye_score"]
    key = ["file_name", "is_negative", "category_id"]
    return {
        "title": "Phân loại cường độ bão", "topic": "cv", "difficulty": "medium",
        "statement": "Mỗi dòng mô tả một ảnh vệ tinh bằng các đặc trưng đã trích sẵn. Hãy dự đoán ảnh có bão hay "
                     "không (is_negative) và nếu có thì cường độ bão thuộc cấp 1 đến 4 (category_id). "
                     "Bản luyện tập này dùng đặc trưng số thay cho ảnh gốc để chạy được trên máy cá nhân.",
        "dataDesc": "annotations.csv (train): file_name, wind_kt, pressure_hpa, cloud_top_c, eye_score, "
                    "is_negative, category_id.\npublic_test.csv, private_test.csv: không có is_negative, category_id.",
        "submitFormat": "Nộp submission.csv gồm 3 cột file_name, is_negative, category_id. "
                        "Nếu is_negative là TRUE thì để trống category_id.\n"
                        "file_name,is_negative,category_id\n201801010000_0320.jpg,FALSE,4\n201801010300_0321.jpg,TRUE,",
        "baseline": "import pandas as pd\n\ntest = pd.read_csv('public_test.csv')\n"
                    "test['is_negative'] = (test['wind_kt'] < 30).map({True: 'TRUE', False: 'FALSE'})\n"
                    "test['category_id'] = test['is_negative'].map({'TRUE': '', 'FALSE': '2'})\n"
                    "test[['file_name', 'is_negative', 'category_id']].to_csv('submission.csv', index=False)\n",
        "metrics": [("F1 phát hiện và phân cấp", "detect_f1", "submission.csv",
                     {"id": "file_name", "neg": "is_negative", "label": "category_id"}, 1, 35, None)],
        "files": [("train", "annotations.csv", to_csv(train, feats + key[1:])),
                  ("public_test", "public_test.csv", to_csv(pub, feats)),
                  ("private_test", "private_test.csv", to_csv(pri, feats)),
                  ("public_key", "submission.csv", to_csv(pub, key)),
                  ("private_key", "submission.csv", to_csv(pri, key))],
    }


def align_task():
    rnd = random.Random(15)
    who = [("The boy", "Cậu bé"), ("The old man", "Ông lão"), ("My sister", "Chị tôi"), ("The teacher", "Cô giáo"),
           ("A farmer", "Người nông dân"), ("The little cat", "Chú mèo nhỏ"), ("The king", "Nhà vua")]
    acts = [("walked to the river", "đi bộ ra sông"), ("opened the old book", "mở cuốn sách cũ"),
            ("looked at the stars", "ngắm những vì sao"), ("planted a tree", "trồng một cái cây"),
            ("sang a quiet song", "hát một bài hát khe khẽ"), ("waited by the door", "đợi bên cánh cửa"),
            ("counted the coins", "đếm những đồng xu"), ("crossed the bridge", "đi qua cây cầu")]
    extra = [("and smiled", "Rồi mỉm cười."), ("and said nothing", "Và không nói gì."),
             ("before the rain came", "Trước khi mưa tới.")]

    def make(n):
        en, vi, pairs, seen = [], [], [], set()
        while len(en) < n:
            (we, wv), (ae, av) = rnd.choice(who), rnd.choice(acts)
            if (we, ae) in seen:
                continue
            seen.add((we, ae))
            if rnd.random() < 0.25:
                ee, ev = rnd.choice(extra)
                en.append(f"{we} {ae} {ee}.")
                vi.append([f"{wv} {av}.", ev])
            else:
                en.append(f"{we} {ae}.")
                vi.append([f"{wv} {av}."])
        flat = [(i, s) for i, group in enumerate(vi) for s in group]
        rnd.shuffle(flat)
        for i in range(len(en)):
            pairs.append({"id_en": i, "id_vn": ";".join(str(j) for j, (src, _) in enumerate(flat) if src == i)})
        en_csv = to_csv([{"id_en": i, "english_sentence": s} for i, s in enumerate(en)], ["id_en", "english_sentence"])
        vi_csv = to_csv([{"id_vn": j, "vietnamese_sentence": s} for j, (_, s) in enumerate(flat)],
                        ["id_vn", "vietnamese_sentence"])
        return en_csv, vi_csv, to_csv(pairs, ["id_en", "id_vn"])

    train, pub, pri = make(36), make(20), make(20)
    return {
        "title": "Đối sánh câu Anh-Việt", "topic": "nlp", "difficulty": "medium",
        "statement": "Cho một tập câu tiếng Anh và một tập câu tiếng Việt đã bị xáo trộn. Hãy xác định với mỗi câu "
                     "tiếng Anh các câu tiếng Việt tương ứng về nội dung. Một câu tiếng Anh có thể ứng với nhiều "
                     "câu tiếng Việt.",
        "dataDesc": "Mỗi tập là một file .zip gồm en.csv (id_en, english_sentence) và vi.csv (id_vn, "
                    "vietnamese_sentence). Riêng train.zip có thêm correct_alignment.csv (id_en, id_vn).",
        "submitFormat": "Nộp alignment.csv gồm 2 cột id_en, id_vn, định dạng giống correct_alignment.csv. "
                        "Nhiều ID tương ứng thì phân tách bằng dấu chấm phẩy, ví dụ: 3,7;12",
        "baseline": "import pandas as pd\n\nen = pd.read_csv('en.csv')\n"
                    "en[['id_en']].assign(id_vn=en['id_en']).to_csv('alignment.csv', index=False)\n",
        "metrics": [("F1 đối sánh", "align_f1", "alignment.csv", {"id": "id_en", "label": "id_vn"}, 1, 5, None)],
        "files": [("train", "train.zip", to_zip([("en.csv", train[0]), ("vi.csv", train[1]),
                                                 ("correct_alignment.csv", train[2])])),
                  ("public_test", "public_test.zip", to_zip([("en.csv", pub[0]), ("vi.csv", pub[1])])),
                  ("private_test", "private_test.zip", to_zip([("en.csv", pri[0]), ("vi.csv", pri[1])])),
                  ("public_key", "alignment.csv", pub[2]), ("private_key", "alignment.csv", pri[2])],
    }


def dimabsa_task():
    rnd = random.Random(16)
    aspects = [("ứng dụng", "APP#PERFORMANCE"), ("giao diện", "APP#UI_UX"), ("nhân viên", "STAFF#ATTITUDE"),
               ("tài xế", "STAFF#PROFESSIONALISM"), ("sản phẩm", "PRODUCT#QUALITY"), ("bao bì", "PRODUCT#DESIGN"),
               ("giao hàng", "SERVICE#TIME"), ("giá cước", "PRICE#RATES"), ("khuyến mãi", "PRICE#PROMO")]
    opinions = [("tuyệt vời", 8.2, 6.8), ("ổn", 6.4, 4.2), ("mượt", 7.4, 5.0), ("bình thường", 5.0, 3.0),
                ("chậm", 3.0, 5.6), ("quá tệ", 1.8, 7.6), ("thô lỗ", 1.6, 8.0), ("đắt", 3.2, 5.0), ("hấp dẫn", 7.6, 6.2)]
    rows, seen = [], set()
    while len(rows) < 220:
        picks = rnd.sample(aspects, rnd.choice([1, 2]))
        chunks, quads = [], []
        for aspect, cat in picks:
            op, v, a = rnd.choice(opinions)
            chunks.append(f"{aspect} {op}")
            quads.append({"aspect": aspect, "category": cat, "opinion": op,
                          "valence": round(min(max(v + rnd.gauss(0, 0.4), 1), 9), 2),
                          "arousal": round(min(max(a + rnd.gauss(0, 0.4), 1), 9), 2)})
        text = (" nhưng " if len(chunks) == 2 else "").join(chunks).capitalize() + rnd.choice([".", " lắm.", " thật sự."])
        if text not in seen:
            seen.add(text)
            rows.append({"text": text, "quadruplets": quads})
    train, pub, pri = cut(rows, 40, 40)

    def pack(part, tag):
        one_in, one_key, two_in, two_key = [], [], [], []
        for i, r in enumerate(part):
            rid = f"{tag}_{i:03d}"
            one_in.append({"id": rid, "text": r["text"], "aspects": [q["aspect"] for q in r["quadruplets"]]})
            one_key.append({"id": rid, "aspects": [{"aspect": q["aspect"], "valence": q["valence"],
                                                    "arousal": q["arousal"]} for q in r["quadruplets"]]})
            two_in.append({"id": rid, "text": r["text"]})
            two_key.append({"id": rid, "quadruplets": r["quadruplets"]})
        return one_in, one_key, two_in, two_key

    tr, pu, pr = pack(train, "TRN"), pack(pub, "PUB"), pack(pri, "PRI")
    one = {"id": "id", "list": "aspects", "fields": ["aspect"], "values": ["valence", "arousal"], "base": 3.0}
    two = {"id": "id", "list": "quadruplets", "fields": ["aspect", "category", "opinion"],
           "values": ["valence", "arousal"], "range": 8}
    return {
        "title": "Phân tích cảm xúc đa chiều theo khía cạnh (DimABSA)", "topic": "nlp", "difficulty": "hard",
        "statement": "Subtask 1 (hồi quy): cho câu đánh giá và danh sách khía cạnh, dự đoán valence và arousal "
                     "(thang 1 đến 9) cho từng khía cạnh.\nSubtask 2 (trích xuất bộ tứ): cho câu đánh giá, trích "
                     "xuất các bộ (aspect, category, opinion, valence, arousal).\nĐiểm tác vụ = 0,3 × Norm_score("
                     "Subtask 1) + 0,7 × Norm_score(Subtask 2). Thiếu tệp của một subtask thì subtask đó 0 điểm.",
        "dataDesc": "train.zip: subtask1.jsonl và subtask2.jsonl có nhãn.\npublic_test.zip, private_test.zip: "
                    "subtask1_input.jsonl (id, text, aspects) và subtask2_input.jsonl (id, text).",
        "submitFormat": "Nộp submission.zip gồm subtask1.jsonl và subtask2.jsonl (kèm notebook).\n"
                        "subtask1.jsonl: {\"id\": \"PUB_000\", \"aspects\": [{\"aspect\": \"...\", \"valence\": 7.5, "
                        "\"arousal\": 6.0}]}\nsubtask2.jsonl: {\"id\": \"PUB_000\", \"quadruplets\": [{\"aspect\": "
                        "\"...\", \"category\": \"...\", \"opinion\": \"...\", \"valence\": 7.5, \"arousal\": 6.0}]}",
        "baseline": "import json\n\nwith open('subtask1.jsonl', 'w', encoding='utf-8') as out:\n"
                    "    for line in open('subtask1_input.jsonl', encoding='utf-8'):\n"
                    "        r = json.loads(line)\n"
                    "        items = [{'aspect': a, 'valence': 5.0, 'arousal': 5.0} for a in r['aspects']]\n"
                    "        out.write(json.dumps({'id': r['id'], 'aspects': items}, ensure_ascii=False) + '\\n')\n",
        "metrics": [("Subtask 1: hồi quy cảm xúc", "rmse_gain", "subtask1.jsonl", one, 0.3, 0, None),
                    ("Subtask 2: trích xuất bộ tứ", "cf1", "subtask2.jsonl", two, 0.7, 0, None)],
        "files": [("train", "train.zip", to_zip([("subtask1.jsonl", to_jsonl([dict(a, text=b["text"]) for a, b in
                                                                                 zip(tr[1], tr[0])])),
                                                 ("subtask2.jsonl", to_jsonl([dict(a, text=b["text"]) for a, b in
                                                                                 zip(tr[3], tr[2])]))])),
                  ("public_test", "public_test.zip", to_zip([("subtask1_input.jsonl", to_jsonl(pu[0])),
                                                             ("subtask2_input.jsonl", to_jsonl(pu[2]))])),
                  ("private_test", "private_test.zip", to_zip([("subtask1_input.jsonl", to_jsonl(pr[0])),
                                                               ("subtask2_input.jsonl", to_jsonl(pr[2]))])),
                  ("public_key", "subtask1.jsonl", to_jsonl(pu[1])), ("public_key", "subtask2.jsonl", to_jsonl(pu[3])),
                  ("private_key", "subtask1.jsonl", to_jsonl(pr[1])), ("private_key", "subtask2.jsonl", to_jsonl(pr[3]))],
    }


def vpr_task():
    rnd = random.Random(17)
    dims = [f"f{i}" for i in range(8)]
    waves = [(rnd.uniform(0.004, 0.05), rnd.uniform(0, 6.28)) for _ in dims]

    def feature(pos, season):
        base = [math.sin(pos * w + p) for w, p in waves]
        if season == "summer":
            return [round(0.7 * b + 0.25 + rnd.gauss(0, 0.07), 3) for b in base]
        return [round(b + rnd.gauss(0, 0.03), 3) for b in base]

    def make(start, n_db, n_q, tag):
        places = {f"{tag}_w{j:04d}": start + j * 4 for j in range(n_db)}
        queries = {f"{tag}_q{j:03d}": rnd.choice(list(places.values())) + rnd.randint(-3, 3) for j in range(n_q)}
        db = [dict({"winter_id": k}, **dict(zip(dims, feature(v, "winter")))) for k, v in places.items()]
        qs = [dict({"query_id": k}, **dict(zip(dims, feature(v, "summer")))) for k, v in queries.items()]
        return (to_csv(db, ["winter_id"] + dims), to_csv(qs, ["query_id"] + dims), places, queries)

    tr, pu, pr = make(1000, 300, 60, "trn"), make(4000, 300, 40, "pub"), make(7000, 300, 40, "pri")
    truth = to_csv([{"id": k, "pos": v} for k, v in {**tr[2], **tr[3]}.items()], ["id", "pos"])
    return {
        "title": "Định vị tàu hoả bốn mùa (đặc trưng trích sẵn)", "topic": "cv", "difficulty": "hard",
        "statement": "Với mỗi ảnh mùa hè (query), hãy tìm ảnh mùa đông trong kho (database) được chụp ở cùng vị "
                     "trí trên tuyến. Một dự đoán đúng khi vị trí của ảnh mùa đông được chọn lệch không quá 10 so "
                     "với vị trí thật của ảnh mùa hè. Bản luyện tập dùng vector đặc trưng 8 chiều thay cho ảnh; "
                     "đặc trưng mùa hè bị co giãn và nhiễu so với mùa đông.",
        "dataDesc": "Mỗi tập là file .zip gồm database.csv (winter_id, f0..f7) và queries.csv (query_id, f0..f7). "
                    "train.zip có thêm positions.csv (id, pos) cho cả hai loại ảnh.",
        "submitFormat": "Nộp output.csv có dòng tiêu đề query_id,winter_id và đúng một dòng cho mỗi query_id. "
                        "query_id lặp lại thì chỉ dòng đầu được chấm; winter_id không thuộc kho bị tính sai.",
        "baseline": "import pandas as pd\n\ndb = pd.read_csv('database.csv')\nqs = pd.read_csv('queries.csv')\n"
                    "cols = [c for c in db.columns if c.startswith('f')]\nrows = []\n"
                    "for _, q in qs.iterrows():\n"
                    "    dist = ((db[cols] - q[cols].astype(float)) ** 2).sum(axis=1)\n"
                    "    rows.append({'query_id': q['query_id'], 'winter_id': db.loc[dist.idxmin(), 'winter_id']})\n"
                    "pd.DataFrame(rows).to_csv('output.csv', index=False)\n",
        "metrics": [("Recall@1", "recall_at_1", "output.csv",
                     {"id": "query_id", "label": "winter_id", "tol": 10}, 1, 10, None)],
        "files": [("train", "train.zip", to_zip([("database.csv", tr[0]), ("queries.csv", tr[1]),
                                                 ("positions.csv", truth)])),
                  ("public_test", "public_test.zip", to_zip([("database.csv", pu[0]), ("queries.csv", pu[1])])),
                  ("private_test", "private_test.zip", to_zip([("database.csv", pr[0]), ("queries.csv", pr[1])])),
                  ("public_key", "key.json", to_json({"queries": pu[3], "database": pu[2]})),
                  ("private_key", "key.json", to_json({"queries": pr[3], "database": pr[2]}))],
    }


def puzzle_task():
    rnd = random.Random(18)
    R, C = 3, 5
    slots = [f"piece_at_{r}_{c}" for r in range(R) for c in range(C)]

    def make(n, tag):
        pieces, keys = [], []
        for k in range(n):
            task = "nv1" if k % 2 == 0 else "nv2"
            name = f"{task}_{tag}_{k:03d}.png"
            horiz = [[round(rnd.uniform(0, 255), 1) for _ in range(C)] for _ in range(R + 1)]
            vert = [[round(rnd.uniform(0, 255), 1) for _ in range(C + 1)] for _ in range(R)]
            order = list(range(R * C))
            if task == "nv1":
                last = order[-C:]
                rnd.shuffle(last)
                order[-C:] = last
            else:
                rnd.shuffle(order)
            noise = lambda v: round(v + rnd.gauss(0, 1.5), 1)
            for shown, origin in enumerate(order):
                r, c = divmod(origin, C)
                pieces.append({"image_filename": name, "piece": shown, "top": noise(horiz[r][c]),
                               "right": noise(vert[r][c + 1]), "bottom": noise(horiz[r + 1][c]),
                               "left": noise(vert[r][c])})
            row = {"image_filename": name}
            for shown, origin in enumerate(order):
                row[slots[origin]] = shown
            keys.append(row)
        return to_csv(pieces, ["image_filename", "piece", "top", "right", "bottom", "left"]), \
            to_csv(keys, ["image_filename"] + slots)

    tr, pu, pr = make(40, "trn"), make(20, "pub"), make(20, "pri")
    return {
        "title": "Khôi phục tranh ghép 15 mảnh", "topic": "cv", "difficulty": "hard",
        "statement": "Mỗi ảnh bị cắt thành 15 mảnh theo lưới 3 hàng 5 cột rồi xáo trộn. Các mảnh trong ảnh xáo "
                     "trộn được đánh số 0 đến 14 theo thứ tự trái sang phải, trên xuống dưới. Hãy cho biết mảnh "
                     "nào đặt vào từng vị trí (r, c) của ảnh gốc.\nNhiệm vụ 1 (ảnh nv1_*): chỉ hàng cuối bị xáo "
                     "trộn. Nhiệm vụ 2 (ảnh nv2_*): cả 15 mảnh bị xáo trộn.\nBản luyện tập mô tả mỗi mảnh bằng "
                     "giá trị trung bình của 4 cạnh; hai mảnh kề nhau có cạnh chung gần bằng nhau.\n"
                     "Điểm tác vụ = 0,3 × Norm_score(PPA nhiệm vụ 1) + 0,7 × Norm_score(PPA nhiệm vụ 2).",
        "dataDesc": "pieces.csv: image_filename, piece, top, right, bottom, left.\ntrain.zip có thêm output.csv "
                    "là đáp án của tập huấn luyện.",
        "submitFormat": "Nộp output.csv: cột image_filename và 15 cột piece_at_0_0, piece_at_0_1, ..., "
                        "piece_at_2_4. Giá trị ở piece_at_r_c là chỉ số (0 đến 14) của mảnh đặt vào vị trí (r, c).",
        "baseline": "import pandas as pd\n\npieces = pd.read_csv('pieces.csv')\nrows = []\n"
                    "for name in pieces['image_filename'].unique():\n"
                    "    row = {'image_filename': name}\n"
                    "    for i in range(15):\n        row[f'piece_at_{i // 5}_{i % 5}'] = i\n    rows.append(row)\n"
                    "pd.DataFrame(rows).to_csv('output.csv', index=False)\n",
        "metrics": [("PPA nhiệm vụ 1", "ppa", "output.csv", {"id": "image_filename", "prefix": "nv1_"}, 0.3, 66, None),
                    ("PPA nhiệm vụ 2", "ppa", "output.csv", {"id": "image_filename", "prefix": "nv2_"}, 0.7, 7, None)],
        "files": [("train", "train.zip", to_zip([("pieces.csv", tr[0]), ("output.csv", tr[1])])),
                  ("public_test", "public_test.csv", pu[0]), ("private_test", "private_test.csv", pr[0]),
                  ("public_key", "output.csv", pu[1]), ("private_key", "output.csv", pr[1])],
    }


TASKS = (sentiment_task, teencode_task, absa_task, storm_task, align_task, dimabsa_task, vpr_task, puzzle_task)


def add_task(conn, t, author):
    if conn.execute("""SELECT 1 FROM "Problem" WHERE title = %s AND kind = 'predict'""", (t["title"],)).fetchone():
        return None
    problem = conn.execute("""INSERT INTO "Problem" (title, statement, topic, difficulty, kind, author)
                              VALUES (%s, %s, %s, %s, 'predict', %s) RETURNING "problemId" """,
                           (t["title"], t["statement"], t["topic"], t["difficulty"], author)).fetchone()
    task = conn.execute("""INSERT INTO "Task" ("problemId", "dataDesc", "submitFormat", baseline, "pubLimit", "priLimit")
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING "taskId" """,
                        (problem["problemId"], t["dataDesc"], t["submitFormat"], t["baseline"],
                         current_app.config["PUB_LIMIT"], current_app.config["PRI_LIMIT"])).fetchone()
    for position, (name, metric, fileName, config, weight, low, high) in enumerate(t["metrics"]):
        conn.execute("""INSERT INTO "Metric" ("taskId", name, metric, "fileName", config, weight, "minScore", "maxScore", position)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                     (task["taskId"], name, metric, fileName, Jsonb(config), weight, low, high, position))
    for role, name, data in t["files"]:
        path, size = storage.write(data, f"data/{task['taskId']}", name)
        conn.execute('INSERT INTO "Dataset" ("taskId", role, "fileName", path, size) VALUES (%s, %s, %s, %s, %s)',
                     (task["taskId"], role, name, path, size))
    return problem["problemId"]


def seed_ai(conn):
    author = conn.execute("""SELECT "userId" FROM "User" WHERE role IN ('supervisor', 'admin')
                             ORDER BY role DESC, "userId" LIMIT 1""").fetchone()
    if author is None:
        return "Chưa có tài khoản giám sát, hãy chạy flask seed trước."
    author = author["userId"]
    n_q = 0
    for content, code, op1, op2, op3, op4, key, topic, difficulty, explain in QUESTIONS:
        if conn.execute('SELECT 1 FROM "Question" WHERE content = %s', (content,)).fetchone():
            continue
        conn.execute("""INSERT INTO "Question" (content, code, op1, op2, op3, op4, key, topic, difficulty, explain, author)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (content, code, op1, op2, op3, op4, key, topic, difficulty, explain, author))
        n_q += 1
    n_t = sum(add_task(conn, make(), author) is not None for make in TASKS)

    title = "Thi thử Olympic AI"
    if not conn.execute('SELECT 1 FROM "Contest" WHERE title = %s', (title,)).fetchone():
        now = datetime.now(timezone.utc)
        contest = conn.execute("""INSERT INTO "Contest" (title, descp, duration, open, close, "privMin", author)
                                  VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING "contestId" """,
                               (title, "Trắc nghiệm AI và 2 tác vụ. Giai đoạn private mở trong 60 phút cuối.",
                                180, now - timedelta(hours=1), now + timedelta(days=30), 60, author)).fetchone()
        questions = conn.execute("""SELECT "questionId" FROM "Question" WHERE content = ANY(%s)
                                    ORDER BY "questionId" """, ([q[0] for q in QUESTIONS],)).fetchall()
        tasks = conn.execute("""SELECT "problemId" FROM "Problem" WHERE kind = 'predict' AND title = ANY(%s)
                                ORDER BY "problemId" """,
                             (["Phân loại cảm xúc bình luận sản phẩm", "Nhận diện và chuẩn hoá teencode"],)).fetchall()
        items = [("question", q["questionId"], None, 1) for q in questions]
        items += [("problem", None, t["problemId"], 50) for t in tasks]
        for position, (itemType, questionId, problemId, points) in enumerate(items):
            conn.execute("""INSERT INTO "ContestItem" ("contestId", "itemType", "questionId", "problemId", points, position)
                            VALUES (%s, %s, %s, %s, %s, %s)""",
                         (contest["contestId"], itemType, questionId, problemId, points, position))
    questions = [r["questionId"] for r in conn.execute("""SELECT "questionId" FROM "Question" WHERE content = ANY(%s)
                                                          ORDER BY "questionId" """, ([q[0] for q in QUESTIONS],)).fetchall()]
    tasks = [r["problemId"] for r in conn.execute("""SELECT "problemId" FROM "Problem" WHERE kind = 'predict'
                                                     ORDER BY "problemId" """).fetchall()]
    add_practice(conn, "Luyện tập Olympic AI", "Trắc nghiệm AI và các tác vụ mẫu, làm lại bao nhiêu lần cũng được.",
                 questions, tasks, author)
    return f"Seeded AI content: {n_q} questions, {n_t} tasks."


def add_practice(conn, title, descp, questions, problems, author):
    if conn.execute('SELECT 1 FROM "Contest" WHERE title = %s', (title,)).fetchone():
        return
    now = datetime.now(timezone.utc)
    contest = conn.execute("""INSERT INTO "Contest" (title, descp, duration, open, close, kind, author)
                              VALUES (%s, %s, %s, %s, %s, 'practice', %s) RETURNING "contestId" """,
                           (title, descp, 3650 * 24 * 60, now, now + timedelta(days=3650), author)).fetchone()
    items = [("question", q, None, 1) for q in questions] + [("problem", None, p, 10) for p in problems]
    for position, (itemType, questionId, problemId, points) in enumerate(items):
        conn.execute("""INSERT INTO "ContestItem" ("contestId", "itemType", "questionId", "problemId", points, position)
                        VALUES (%s, %s, %s, %s, %s, %s)""",
                     (contest["contestId"], itemType, questionId, problemId, points, position))


@click.command("seed-ai")
def seed_ai_command():
    with connect() as conn:
        click.echo(seed_ai(conn))
