"""通知中心 / Web Push 降级 / 发布通知 / nudge 限流（NOTIF-001~008）。"""
from conftest import login, make_student
from data import models


def _chapter(client, teacher_headers, name="第一章"):
    r = client.post("/api/chapters", json={"folder": "模块", "name": name}, headers=teacher_headers)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["id"]


def _student(client, teacher_headers, name):
    make_student(client, teacher_headers, name)
    return {"Authorization": "Bearer " + login(client, name, "student123")}


def _session(client, teacher_headers, chapter_ids, title="第1周第1节"):
    r = client.post("/api/curriculum/sessions", json={
        "week_no": 1, "session_no": 1, "title": title,
        "chapter_ids": chapter_ids, "concept_tags": [],
    }, headers=teacher_headers)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["id"]


def _notifications(client, h):
    return client.get("/api/notifications", headers=h).get_json()["data"]


# ---- 通知落库 / 未读 / 已读 ----

def test_notification_persist_unread_read(client, teacher_headers):
    uid = make_student(client, teacher_headers, "nf_a")
    h = {"Authorization": "Bearer " + login(client, "nf_a", "student123")}
    with client.application.app_context():
        from data.db import get_db
        from services.notify import notify_users

        con = get_db()
        notify_users(con, [uid], "path_published", "老师发布了新学习路径", "第1周第1节 · x",
                     image="", ref_kind="session", ref_id="s1")

    d = _notifications(client, h)
    assert d["unread"] == 1 and len(d["notifications"]) == 1
    n = d["notifications"][0]
    assert n["type"] == "path_published" and n["is_read"] is False

    # 单条标记已读
    client.post("/api/notifications/read", json={"ids": [n["id"]]}, headers=h)
    d = _notifications(client, h)
    assert d["unread"] == 0 and d["notifications"][0]["is_read"] is True


# ---- nudge 限流：自己=400，同日同对第二次=400，反向不受限 ----

def test_nudge_same_day_same_pair_rate_limit(client, teacher_headers):
    hb = _student(client, teacher_headers, "nf_b")
    hc = _student(client, teacher_headers, "nf_c")
    id_b = client.get("/api/auth/me", headers=hb).get_json()["data"]["id"]
    id_c = client.get("/api/auth/me", headers=hc).get_json()["data"]["id"]

    assert client.post("/api/checkin/nudge", json={"to_user_id": id_b}, headers=hb).status_code == 400
    assert client.post("/api/checkin/nudge", json={"to_user_id": id_c}, headers=hb).status_code == 200
    assert client.post("/api/checkin/nudge", json={"to_user_id": id_c}, headers=hb).status_code == 400
    assert client.post("/api/checkin/nudge", json={"to_user_id": id_b}, headers=hc).status_code == 200


# ---- 发布学习路径 / 测评 → 每个在用学生各 1 条 ----

def test_publish_session_notifies_each_active_student_once(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    h1 = _student(client, teacher_headers, "nf_d")
    h2 = _student(client, teacher_headers, "nf_e")
    sid = _session(client, teacher_headers, [cid])
    r = client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    assert r.status_code == 200
    for h in (h1, h2):
        kinds = [n["type"] for n in _notifications(client, h)["notifications"]]
        assert kinds.count("path_published") == 1


def test_publish_quiz_notifies_each_active_student_once(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    h1 = _student(client, teacher_headers, "nf_f")
    h2 = _student(client, teacher_headers, "nf_g")
    r = client.post("/api/quizzes/draft", json={"chapter_ids": [cid]}, headers=teacher_headers)
    assert r.status_code == 200, r.get_json()
    qid = r.get_json()["data"]["id"]
    r = client.post(f"/api/quizzes/{qid}/publish", headers=teacher_headers)
    assert r.status_code == 200
    for h in (h1, h2):
        kinds = [n["type"] for n in _notifications(client, h)["notifications"]]
        assert kinds.count("quiz_published") == 1


# ---- push 抛错仍落库、HTTP 200（降级） ----

def test_push_failure_still_persists_and_returns_200(client, teacher_headers, monkeypatch):
    make_student(client, teacher_headers, "nf_h")
    h = {"Authorization": "Bearer " + login(client, "nf_h", "student123")}

    from services import push

    def boom(*args, **kwargs):
        raise RuntimeError("push exploded")

    monkeypatch.setattr(push, "send_push", boom)

    cid = _chapter(client, teacher_headers)
    sid = _session(client, teacher_headers, [cid])
    r = client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    assert r.status_code == 200

    kinds = [n["type"] for n in _notifications(client, h)["notifications"]]
    assert kinds.count("path_published") == 1


# ---- prefs：remind_daily 口径 + has_push_sub 订阅存在性 ----

def test_prefs_remind_daily_and_has_push_sub(client, teacher_headers):
    make_student(client, teacher_headers, "nf_pref")
    h = {"Authorization": "Bearer " + login(client, "nf_pref", "student123")}
    d = client.get("/api/notifications/prefs", headers=h).get_json()["data"]
    assert d["remind_daily"] is True
    assert d["has_push_sub"] is False

    r = client.post("/api/notifications/prefs", json={"remind_daily": False}, headers=h)
    assert r.status_code == 200
    assert r.get_json()["data"]["remind_daily"] is False
    d = client.get("/api/notifications/prefs", headers=h).get_json()["data"]
    assert d["remind_daily"] is False


def test_prefs_has_push_sub_true_when_subscribed(client, teacher_headers):
    uid = make_student(client, teacher_headers, "nf_sub")
    with client.application.app_context():
        from data.db import get_db

        con = get_db()
        con.execute(
            "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (models.new_id(), uid, "https://example.com/ep", "p256dh", "auth", models.utcnow()),
        )
        con.commit()
    h = {"Authorization": "Bearer " + login(client, "nf_sub", "student123")}
    d = client.get("/api/notifications/prefs", headers=h).get_json()["data"]
    assert d["has_push_sub"] is True
