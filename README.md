## faos

Hệ thống thi và luyện tập giải thuật trực tuyến, có dùng Claude API để sinh đề tự động.

Sinh viên làm đề luyện tập và kỳ thi gồm ba loại bài: lập trình Python (chấm bằng Judge0), trắc nghiệm và học máy nâng cao (nộp file kết quả, chấm theo metric). Điểm được tính theo kết quả và thời gian nộp, có bảng xếp hạng. Giám sát viên quản lý ngân hàng đề, tạo kỳ thi và duyệt đề do Claude sinh ra trước khi đưa vào ngân hàng.

# Techstack

Flask, PostgreSQL, Redis + RQ, Judge0 1.13.1 (chạy local trong docker), Claude API.

# Cài đặt

Cần có PostgreSQL, Redis và Judge0 đang chạy (Judge0 mặc định ở `http://localhost:2358`).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
createdb -U postgres algojudge
flask --app run init-db
flask --app run seed
```

Điền `DATABASE_URL`, `SECRET_KEY` và `ANTHROPIC_API_KEY` trong `.env`.

# Chạy

```bash
flask --app run run
python worker.py
```

url: http://127.0.0.1:5000.

Test account: 
1. admin, pass: admin123
2. giamsat, pass: giamsat123
3. sv1, pass: student123

