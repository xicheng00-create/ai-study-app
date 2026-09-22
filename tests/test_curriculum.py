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
    assert resp.get_json()["data"]["chapters"] == []
    # 发布后可见
    client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)
    resp = client.get("/api/curriculum", headers=h)
    chapters = resp.get_json()["data"]["chapters"]
    assert len(chapters) == 1
    assert chapters[0]["id"] == sid


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


def test_curriculum_speaks_chapter_no_only(client, teacher_headers):
    """KNOW-009（v2.7.1）：学习路径/视频课对外**只有章号**，不再暴露 week_no/session_no。

    章号 ⇄ 周/节 换算是 `data.models.chapter_no/week_session` 的唯一定义。
    """
    c3 = _chapter(client, teacher_headers, name="第 3 章 · AIPM vs 传统 PM")
    c4 = _chapter(client, teacher_headers, name="第 4 章 · 真实落地案例")
    # 新入参：章号。第 3 章 → 库内 W2S1，第 4 章 → W2S2
    s3 = client.post("/api/curriculum/sessions", json={
        "chapter_no": 3, "title": "AIPM vs 传统 PM", "chapter_ids": [c3],
    }, headers=teacher_headers).get_json()["data"]["id"]
    s4 = client.post("/api/curriculum/sessions", json={
        "chapter_no": 4, "title": "真实落地案例", "chapter_ids": [c4],
    }, headers=teacher_headers).get_json()["data"]["id"]

    data = client.get("/api/curriculum", headers=teacher_headers).get_json()["data"]
    assert "weeks" not in data                                  # 旧「第X周」分组口径已下线
    assert {c["chapter_no"]: c["id"] for c in data["chapters"]} == {3: s3, 4: s4}
    first = data["chapters"][0]
    assert "week_no" not in first and "session_no" not in first  # 周/节不再外显
    assert first["card_count"] == 0 and first["days"] == 0       # 无卡片 → 0 天

    # 视频按章号绑定（第 4 章 → W2S2），列表同样只回章号
    vid = client.post("/api/curriculum/videos", json={
        "title": "案例精讲", "url": "https://example.com/v", "chapter_no": 4,
    }, headers=teacher_headers).get_json()["data"]["id"]
    vids = client.get("/api/curriculum/videos", headers=teacher_headers).get_json()["data"]["videos"]
    row = [v for v in vids if v["id"] == vid][0]
    assert row["chapter_no"] == 4 and "week_no" not in row

    # 旧入参（week_no/session_no）仍兼容：W3S2 = 第 6 章
    legacy = client.post("/api/curriculum/sessions", json={
        "week_no": 3, "session_no": 2, "title": "旧口径入参", "chapter_ids": [],
    }, headers=teacher_headers)
    assert legacy.status_code == 200
    legacy_id = legacy.get_json()["data"]["id"]
    chs = client.get("/api/curriculum", headers=teacher_headers).get_json()["data"]["chapters"]
    assert [c["chapter_no"] for c in chs if c["id"] == legacy_id] == [6]
    assert client.delete(f"/api/curriculum/sessions/{legacy_id}",
                         headers=teacher_headers).status_code == 200
