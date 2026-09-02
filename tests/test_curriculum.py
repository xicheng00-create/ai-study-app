"""学习路径与视频课测试（CURR-001~003 / VIDEO-001~003）。"""
from conftest import login, make_student


def _chapter(client, teacher_headers, name="第一章"):
    resp = client.post("/api/chapters", json={"folder": "模块", "name": name}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def _session(client, teacher_headers, chapter_ids, week=1, no=1, tags=None):
    resp = client.post("/api/curriculum/sessions", json={
        "week_no": week, "session_no": no, "title": "第1周第1节",
        "chapter_ids": chapter_ids, "concept_tags": tags or [],
    }, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def test_teacher_session_crud(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    sid = _session(client, teacher_headers, [cid])
    resp = client.put(f"/api/curriculum/sessions/{sid}", json={"title": "改名"}, headers=teacher_headers)
    assert resp.status_code == 200
    resp = client.delete(f"/api/curriculum/sessions/{sid}", headers=teacher_headers)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["deleted"] == 1


def test_student_cannot_write_session_or_video(client, teacher_headers):
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    resp = client.post("/api/curriculum/sessions", json={"title": "越权"}, headers=h)
    assert resp.status_code == 403
    resp = client.post("/api/curriculum/videos", json={"title": "越权", "url": "x"}, headers=h)
    assert resp.status_code == 403


def test_student_overview_only_published(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    sid = _session(client, teacher_headers, [cid])
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    # 未发布：学生总览为空
    resp = client.get("/api/curriculum", headers=h)
    assert resp.get_json()["data"]["weeks"] == []
    # 发布后可见
    client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    resp = client.get("/api/curriculum", headers=h)
    weeks = resp.get_json()["data"]["weeks"]
    assert len(weeks) == 1
    assert weeks[0]["sessions"][0]["id"] == sid


def test_publish_syncs_content_status(client, teacher_headers):
    cid = _chapter(client, teacher_headers)  # 默认 published
    sid = _session(client, teacher_headers, [cid])  # draft
    from data.db import get_db
    # 取消发布（虽是草稿，但会把其下章节回 draft）
    client.post(f"/api/curriculum/sessions/{sid}/unpublish", headers=teacher_headers)
    with client.application.app_context():
        con = get_db()
        assert con.execute("SELECT status FROM chapters WHERE id=?", (cid,)).fetchone()["status"] == "draft"
    # 发布 → 章节同步 published
    client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    with client.application.app_context():
        con = get_db()
        assert con.execute("SELECT status FROM chapters WHERE id=?", (cid,)).fetchone()["status"] == "published"


def test_video_crud_and_visibility(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    sid = _session(client, teacher_headers, [cid])
    resp = client.post("/api/curriculum/videos", json={
        "title": "Transformer 讲解", "url": "https://example.com/v1",
        "platform": "bilibili", "week_no": 1, "session_no": 1,
        "concept_tags": ["transformer"],
    }, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    vid = resp.get_json()["data"]["id"]
    assert resp.get_json()["data"]["status"] == "draft"
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    # 草稿视频学生不可见
    assert client.get("/api/curriculum/videos", headers=h).get_json()["data"]["videos"] == []
    # 发布 session 后视频同步 published，学生可见
    client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    vids = client.get("/api/curriculum/videos", headers=h).get_json()["data"]["videos"]
    assert len(vids) == 1 and vids[0]["id"] == vid
    # 教师可改/删
    assert client.put(f"/api/curriculum/videos/{vid}", json={"title": "改"}, headers=teacher_headers).status_code == 200
    assert client.delete(f"/api/curriculum/videos/{vid}", headers=teacher_headers).status_code == 200
