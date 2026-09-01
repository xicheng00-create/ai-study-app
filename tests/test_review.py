"""间隔复习状态机测试（PROG-006 / §5.3）。"""
import json

from ai import review_sched
from data import models


def test_next_interval_sequence():
    assert review_sched.next_interval(True, 1) == 3
    assert review_sched.next_interval(True, 3) == 7   # 3*3=9 封顶 7
    assert review_sched.next_interval(True, 7) == 7
    assert review_sched.next_interval(False, 7) == 1  # 答错重置
    assert review_sched.next_interval(False, 3) == 1


def _seed_review_item(client, user_id, chapter_id, interval=1):
    from data.db import get_db
    from data import models as m
    from ai import review_sched as rs
    with client.application.app_context():
        con = get_db()
        payload = json.dumps({
            "content": "1+1=?", "type": "choice",
            "options": json.dumps(["1", "2", "3"]), "answer_key": "1",
        }, ensure_ascii=False)
        iid = m.new_id()
        con.execute(
            "INSERT INTO review_items (id, user_id, chapter_id, question_id, payload,"
            " next_review_at, interval_days, status, created_at)"
            " VALUES (?, ?, ?, NULL, ?, ?, ?, 'pending', ?)",
            (iid, user_id, chapter_id, payload, rs.next_review_at_iso(interval), interval, m.utcnow()),
        )
        con.commit()
        return iid


def test_complete_review_correct_extends_interval(client, teacher_headers):
    from conftest import login, make_student
    make_student(client, teacher_headers, "alice")
    token = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {token}"}
    # 直接建章节（教师）
    from data.db import get_db
    from data import models as m
    with client.application.app_context():
        con = get_db()
        cid = m.new_id()
        con.execute("INSERT INTO chapters (id, folder, name, order_no, created_by, created_at)"
                    " VALUES (?, '模块', '测试章', 0, NULL, ?)", (cid, m.utcnow()))
        # 取 alice 的 user id
        uid = con.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
        con.commit()
    iid = _seed_review_item(client, uid, cid, interval=1)

    resp = client.post(f"/api/progress/review-items/{iid}/complete",
                       json={"answer": "1"}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["correct"] == 1
    assert data["next_interval_days"] == 3
    # 新 pending 项已生成，interval=3
    resp = client.get("/api/progress/review-items", headers=h)
    pending = [r for r in resp.get_json()["data"]["review_items"] if r["status"] == "pending"]
    assert any(r["interval_days"] == 3 for r in pending)


def test_complete_review_wrong_resets_interval(client, teacher_headers):
    from conftest import login, make_student
    make_student(client, teacher_headers, "alice")
    token = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {token}"}
    from data.db import get_db
    from data import models as m
    with client.application.app_context():
        con = get_db()
        cid = m.new_id()
        con.execute("INSERT INTO chapters (id, folder, name, order_no, created_by, created_at)"
                    " VALUES (?, '模块', '测试章', 0, NULL, ?)", (cid, m.utcnow()))
        uid = con.execute("SELECT id FROM users WHERE username='alice'").fetchone()["id"]
        con.commit()
    iid = _seed_review_item(client, uid, cid, interval=3)
    resp = client.post(f"/api/progress/review-items/{iid}/complete",
                       json={"answer": "0"}, headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["correct"] == 0
    assert resp.get_json()["data"]["next_interval_days"] == 1
