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
    # 普通提问（不含视频关键词）不应返回相关视频（v1.5.1：避免每轮轰炸,优先指向资料）
    resp = client.post(f"/api/conversations/{conv_id}/message", json={
        "content": "transformer 是什么？",
        "chapter_id": cid,
        "chapter_ids": [cid],
        "concept_tags": ["transformer"],
    }, headers=h)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["related_videos"] == [], f"普通提问不应返回视频，got {data['related_videos']}"
    # 视频 URL 不作为答案内联
    assert "https://example.com" not in data["reply"]

    # 主动问及视频课 → 应返回相关视频
    resp2 = client.post(f"/api/conversations/{conv_id}/message", json={
        "content": "有没有相关视频课可以看？",
        "chapter_id": cid,
        "chapter_ids": [cid],
        "concept_tags": ["transformer"],
    }, headers=h)
    assert resp2.status_code == 200, resp2.get_json()
    rv = resp2.get_json()["data"]["related_videos"]
    assert any(v["title"] == "Transformer 讲解" for v in rv), f"问视频应返回相关视频，got {rv}"
    assert all("url" in v and "platform" in v for v in rv)


def test_kc_ctx_message_accepted(client, teacher_headers):
    """知识卡片「去问 TUTOR」（kc_ctx）消息被接受：200 + 有回复 + 用户/助教消息落库。"""
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    conv = client.post("/api/conversations", json={"title": "卡片提问", "chapter_id": cid}, headers=h)
    conv_id = conv.get_json()["data"]["id"]
    resp = client.post(f"/api/conversations/{conv_id}/message", json={
        "content": "请围绕「大模型是什么」详细展开讲解",
        "chapter_id": cid,
        "chapter_ids": [cid],
        "kc_ctx": {"front": "大模型是什么", "back": "大模型是参数规模巨大的神经网络…",
                   "sub_concept": "概念扫盲", "chapter_id": cid},
    }, headers=h)
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()["data"]
    assert data["reply"] and data["reply"].strip() != ""
    msgs = client.get(f"/api/conversations/{conv_id}", headers=h).get_json()["data"]["messages"]
    assert any(m["role"] == "user" for m in msgs)
    assert any(m["role"] == "assistant" for m in msgs)


def test_kc_ctx_rejects_non_dict(client, teacher_headers):
    """kc_ctx 非对象（如字符串）→ 400 输入错误。"""
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    conv = client.post("/api/conversations", json={"title": "提问", "chapter_id": cid}, headers=h)
    conv_id = conv.get_json()["data"]["id"]
    resp = client.post(f"/api/conversations/{conv_id}/message", json={
        "content": "讲讲", "chapter_id": cid, "kc_ctx": "not-a-dict",
    }, headers=h)
    assert resp.status_code == 400

