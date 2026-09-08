"""每日学习建议（RPT-003 改每日）与 daily_advice 表测试。"""
from conftest import login, make_student
from data import models, timeutil


def _insert_advice(client, user_id, advice_date, advice="建议文本"):
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        con.execute(
            "INSERT INTO daily_advice (id, user_id, advice_date, stats, advice, created_at)"
            " VALUES (?, ?, ?, '{}', ?, ?)",
            (models.new_id(), user_id, advice_date, advice, models.utcnow()),
        )
        con.commit()


def test_advice_empty(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    resp = client.get("/api/progress/advice", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["has_advice"] is False


def test_advice_returns_today_first(client, teacher_headers):
    uid = make_student(client, teacher_headers, "alice")
    # 昨天 + 今天各一条，应优先返回今天（UTC+8）
    _insert_advice(client, uid, "2020-01-01", "旧建议")
    _insert_advice(client, uid, timeutil.today_str(), "今天的建议")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    resp = client.get("/api/progress/advice", headers=h)
    d = resp.get_json()["data"]
    assert d["has_advice"] is True
    assert d["advice_date"] == timeutil.today_str()
    assert d["advice"] == "今天的建议"


def test_advice_is_per_student(client, teacher_headers):
    """建议按学生隔离：A 的 token 只能取 A 的建议。"""
    make_student(client, teacher_headers, "alice")
    uid_bob = make_student(client, teacher_headers, "bob")
    _insert_advice(client, uid_bob, timeutil.today_str(), "bob 的建议")
    alice = login(client, "alice", "student123")
    resp = client.get("/api/progress/advice", headers={"Authorization": f"Bearer {alice}"})
    assert resp.get_json()["data"]["has_advice"] is False


def test_advice_generate_once_per_day(client, teacher_headers):
    """点击生成今日建议：首次生成（generated=True），当天再点幂等不重生成（generated=False）。"""
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    # 首次生成：无 LLM key 环境走模板兜底，建议非空
    resp = client.post("/api/progress/advice/generate", json={}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    d = resp.get_json()["data"]
    assert d["generated"] is True and d["has_advice"] is True
    assert d["advice_date"] == timeutil.today_str()
    assert d["advice"].strip() != ""
    # 当天再点 → 直接返回已有（一天最多一次，不重复调用 AI）
    resp2 = client.post("/api/progress/advice/generate", json={}, headers=h)
    d2 = resp2.get_json()["data"]
    assert d2["generated"] is False
    assert d2["advice"] == d["advice"]
    # GET 同步可见
    resp3 = client.get("/api/progress/advice", headers=h)
    assert resp3.get_json()["data"]["has_advice"] is True


def test_advice_generate_is_per_student(client, teacher_headers):
    """A 生成后不影响 B：B 首次生成仍是 generated=True（按人隔离）。"""
    make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")
    alice = login(client, "alice", "student123")
    bob = login(client, "bob", "student123")
    client.post("/api/progress/advice/generate", json={}, headers={"Authorization": f"Bearer {alice}"})
    resp = client.post("/api/progress/advice/generate", json={}, headers={"Authorization": f"Bearer {bob}"})
    assert resp.get_json()["data"]["generated"] is True


def test_advice_uses_recent_quiz_chapter_mastery_and_wrong_concept(client, teacher_headers):
    """无 LLM 时，建议仍引用近 7 天的真实章节、错题和测评。"""
    from datetime import timedelta
    from ai import advice_gen
    from data import models, timeutil
    from data.db import get_db

    uid = make_student(client, teacher_headers, "alice")
    now = models.utcnow()
    yesterday = (timeutil.shanghai_now() - timedelta(days=1)).astimezone().isoformat()
    with client.application.app_context():
        con = get_db()
        con.execute(
            "INSERT INTO chapters (id, folder, name, order_no, status, created_at)"
            " VALUES ('ch-1', '模块一', '线性回归', 1, 'published', ?)", (now,)
        )
        con.execute(
            "INSERT INTO quizzes (id, title, chapter_ids, version, status, created_at, published_at)"
            " VALUES ('quiz-1', '回归测评', '[\"ch-1\"]', 1, 'published', ?, ?)",
            (yesterday, yesterday),
        )
        con.execute(
            "INSERT INTO questions (id, quiz_id, chapter_id, sub_concept, type, content, options, answer_key, points, created_at)"
            " VALUES ('q-1', 'quiz-1', 'ch-1', '损失函数', 'choice', '损失函数题', '[]', '', 5, ?)",
            (yesterday,),
        )
        con.execute(
            "INSERT INTO attempts (id, user_id, quiz_id, question_id, chapter_id, quiz_version, correct, score, created_at)"
            " VALUES ('a-1', ?, 'quiz-1', 'q-1', 'ch-1', 1, 0, 0, ?)",
            (uid, yesterday),
        )
        con.commit()
        context = advice_gen.recent_learning_context(con, uid)
        text = advice_gen.build_advice_text(con, uid, {"quizzes": 0}, ["线性回归"])

    assert context["has_recent_quiz"] is True
    assert context["latest_quiz_chapter"] == "线性回归"
    assert context["chapters"][0]["mastery"] == "薄弱"
    assert "损失函数" in context["weak_concepts"]
    assert "线性回归" in text
    assert "最近一次测评" in text
    assert "测评还没做" not in text

