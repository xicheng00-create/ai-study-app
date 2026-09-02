"""TUTOR 视频融合测试（CHAT-010 / VIDEO-003）：响应含 related_videos，不含视频正文。"""
from conftest import login, make_student


def _chapter(client, teacher_headers):
    resp = client.post("/api/chapters", json={"folder": "模块", "name": "第一章"}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def test_tutor_response_contains_related_videos(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    resp = client.post("/api/curriculum/sessions", json={
        "week_no": 1, "session_no": 1, "title": "第1周第1节",
        "chapter_ids": [cid], "concept_tags": ["transformer"],
    }, headers=teacher_headers)
    sid = resp.get_json()["data"]["id"]
    client.post("/api/curriculum/videos", json={
        "title": "Transformer 讲解", "url": "https://example.com/v1",
        "platform": "bilibili", "week_no": 1, "session_no": 1,
        "concept_tags": ["transformer"],
    }, headers=teacher_headers)
    client.post(f"/api/curriculum/sessions/{sid}/publish", headers=teacher_headers)

    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    conv = client.post("/api/conversations", json={"title": "提问", "chapter_id": cid}, headers=h)
    conv_id = conv.get_json()["data"]["id"]
    resp = client.post(f"/api/conversations/{conv_id}/message", json={
        "content": "transformer 是什么？",
        "chapter_id": cid,
        "chapter_ids": [cid],
        "concept_tags": ["transformer"],
    }, headers=h)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    rv = data["related_videos"]
    assert any(v["title"] == "Transformer 讲解" for v in rv)
    assert all("url" in v and "platform" in v for v in rv)
    # 视频 URL 不作为答案内联
    assert "https://example.com" not in data["reply"]
