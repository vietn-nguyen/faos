from datetime import datetime, timedelta, timezone

import click
from werkzeug.security import generate_password_hash

from .db import connect
from .seed_ai import add_practice, seed_ai, seed_ai_command

USERS = [
    ("admin@algo.local", "admin", "admin123", "admin"),
    ("giamsat@algo.local", "giamsat", "giamsat123", "supervisor"),
    ("sv1@algo.local", "sv1", "student123", "student"),
    ("sv2@algo.local", "sv2", "student123", "student"),
    ("sv3@algo.local", "sv3", "student123", "student"),
]

PROBLEMS = [
    {
        "title": "Tổng các số chẵn",
        "statement": "Cho dãy n số nguyên. Hãy tính tổng các số chẵn trong dãy.",
        "input": "Dòng 1: số nguyên n. Dòng 2: n số nguyên cách nhau bởi dấu cách.",
        "output": "Một số nguyên là tổng các số chẵn.",
        "constraints": "1 ≤ n ≤ 10^5, |a_i| ≤ 10^9",
        "topic": "array", "difficulty": "easy",
        "tests": [("5\n1 2 3 4 5\n", "6", True), ("3\n1 3 5\n", "0", True),
                  ("4\n-2 -4 7 8\n", "2", False), ("1\n1000000000\n", "1000000000", False)],
    },
    {
        "title": "Chuỗi đối xứng",
        "statement": "Cho một chuỗi chỉ gồm chữ cái thường. In YES nếu chuỗi đọc xuôi và ngược "
                     "giống nhau, ngược lại in NO.",
        "input": "Một dòng chứa chuỗi s.",
        "output": "YES hoặc NO.",
        "constraints": "1 ≤ |s| ≤ 10^5",
        "topic": "string", "difficulty": "easy",
        "tests": [("abba\n", "YES", True), ("abc\n", "NO", True), ("a\n", "YES", False),
                  ("abcdcba\n", "YES", False), ("ab\n", "NO", False)],
    },
    {
        "title": "Tìm kiếm nhị phân",
        "statement": "Cho dãy n số nguyên đã sắp xếp tăng dần và q truy vấn. Với mỗi truy vấn x, "
                     "in vị trí (đếm từ 1) của x trong dãy, hoặc -1 nếu không có.",
        "input": "Dòng 1: n và q. Dòng 2: n số tăng dần, khác nhau. Dòng 3: q số x.",
        "output": "q dòng, mỗi dòng một vị trí hoặc -1.",
        "constraints": "1 ≤ n, q ≤ 10^5",
        "topic": "searching", "difficulty": "medium",
        "tests": [("5 3\n1 3 5 7 9\n3 4 9\n", "2\n-1\n5", True),
                  ("1 2\n10\n10 5\n", "1\n-1", False),
                  ("4 4\n-5 0 5 10\n-5 10 0 7\n", "1\n4\n2\n-1", False)],
    },
]

QUESTIONS = [
    ("Độ phức tạp của tìm kiếm nhị phân trên mảng n phần tử đã sắp xếp là?",
     "O(n)", "O(log n)", "O(n log n)", "O(1)", "B", "searching"),
    ("Thuật toán sắp xếp nào có độ phức tạp trung bình O(n log n)?",
     "Bubble sort", "Insertion sort", "Merge sort", "Selection sort", "C", "sorting"),
    ("Cấu trúc dữ liệu nào dùng cho duyệt đồ thị theo chiều rộng (BFS)?",
     "Ngăn xếp", "Hàng đợi", "Cây nhị phân", "Bảng băm", "B", "tree_graph"),
    ("Điều kiện bắt buộc của một hàm đệ quy đúng là?",
     "Có vòng lặp", "Có điều kiện dừng", "Có biến toàn cục", "Trả về số nguyên", "B", "recursion"),
    ("Truy cập phần tử thứ i của mảng tốn thời gian?",
     "O(1)", "O(log n)", "O(n)", "O(n^2)", "A", "array"),
]


@click.command("seed")
def seed_command():
    with connect() as conn:
        ids = {}
        for email, name, password, role in USERS:
            row = conn.execute("""INSERT INTO "User" ("userEmail", username, "userPass", role)
                                  VALUES (%s, %s, %s, %s) ON CONFLICT ("userEmail") DO UPDATE
                                  SET username = EXCLUDED.username RETURNING "userId" """,
                               (email, name, generate_password_hash(password), role)).fetchone()
            ids[role] = row["userId"]
        author = ids["supervisor"]

        problems = []
        for p in PROBLEMS:
            row = conn.execute('SELECT "problemId" FROM "Problem" WHERE title = %s', (p["title"],)).fetchone()
            if row:
                problems.append(row["problemId"])
                continue
            row = conn.execute("""INSERT INTO "Problem" (title, statement, input, output, constraints,
                                  topic, difficulty, author)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING "problemId" """,
                               (p["title"], p["statement"], p["input"], p["output"],
                                p["constraints"], p["topic"], p["difficulty"], author)).fetchone()
            problems.append(row["problemId"])
            for position, (stdin, out, sample) in enumerate(p["tests"]):
                conn.execute("""INSERT INTO "TestCase" ("problemId", input, output, sample, position)
                                VALUES (%s, %s, %s, %s, %s)""",
                             (row["problemId"], stdin, out, sample, position))

        questions = []
        for q in QUESTIONS:
            row = conn.execute('SELECT "questionId" FROM "Question" WHERE content = %s', (q[0],)).fetchone()
            if row:
                questions.append(row["questionId"])
                continue
            row = conn.execute("""INSERT INTO "Question" (content, op1, op2, op3, op4, key, topic, author)
                                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING "questionId" """,
                               (*q, author)).fetchone()
            questions.append(row["questionId"])

        add_practice(conn, "Luyện tập giải thuật cơ bản", "Các bài toán và câu hỏi giải thuật mẫu.",
                     questions, problems, author)
        now = datetime.now(timezone.utc)
        title = "Kỳ thi thử giải thuật cơ bản"
        if conn.execute('SELECT 1 FROM "Contest" WHERE title = %s', (title,)).fetchone():
            click.echo(seed_ai(conn))
            click.echo("Seeded. Logins: admin/admin123, giamsat/giamsat123, sv1/student123")
            return
        contest = conn.execute("""INSERT INTO "Contest" (title, descp, duration, open, close, author)
                                  VALUES (%s, %s, %s, %s, %s, %s) RETURNING "contestId" """,
                               (title,
                                "5 câu trắc nghiệm (1 điểm) và 2 bài toán (10 điểm).",
                                45, now - timedelta(hours=1), now + timedelta(days=30), author)).fetchone()
        items = [("question", q, None, 1) for q in questions] + [("problem", None, p, 10) for p in problems[:2]]
        for position, (itemType, questionId, problemId, points) in enumerate(items):
            conn.execute("""INSERT INTO "ContestItem" ("contestId", "itemType", "questionId", "problemId", points, position)
                            VALUES (%s, %s, %s, %s, %s, %s)""",
                         (contest["contestId"], itemType, questionId, problemId, points, position))
        click.echo(seed_ai(conn))
    click.echo("Seeded. Logins: admin/admin123, giamsat/giamsat123, sv1/student123")


def init_app(app):
    app.cli.add_command(seed_command)
    app.cli.add_command(seed_ai_command)
