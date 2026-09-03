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
