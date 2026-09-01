"""测评流测试（QUIZ-001/002/008，F3 quiz_version 落地）。"""
from conftest import login, make_student


def _chapter(client, teacher_headers, name="第一章"):
    resp = client.post("/api/chapters", json={"folder": "模块", "name": name}, headers=teacher_headers)
    assert resp.status_code == 200
    return resp.get_json()["data"]["id"]


def _draft_and_publish(client, teacher_headers, chapter_id):
    resp = client.post("/api/quizzes/draft", json={"chapter_ids": [chapter_id]}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    qid = resp.get_json()["data"]["id"]
    resp = client.post(f"/api/quizzes/{qid}/publish", headers=teacher_headers)
    assert resp.status_code == 200
    return qid


def test_draft_not_answerable_by_student(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    resp = client.post("/api/quizzes/draft", json={"chapter_ids": [cid]}, headers=teacher_headers)
    qid = resp.get_json()["data"]["id"]
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    # 草稿不可见/不可作答
    resp = client.post(f"/api/quizzes/{qid}/attempts", json={"answers": []}, headers=h)
    assert resp.status_code == 400


def test_publish_attempt_and_version(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    qid = _draft_and_publish(client, teacher_headers, cid)
    make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    detail = client.get(f"/api/quizzes/{qid}", headers=h).get_json()["data"]
    qs = detail["questions"]
    answers = [{"question_id": q["id"], "answer": "1"} for q in qs]
    resp = client.post(f"/api/quizzes/{qid}/attempts", json={"answers": answers}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    # 报告可见
    resp = client.get(f"/api/quizzes/{qid}/report", headers=h)
    assert resp.status_code == 200
    assert resp.get_json()["data"]["taken"] is True


def test_revision_creates_new_version(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    qid = _draft_and_publish(client, teacher_headers, cid)
    resp = client.post(f"/api/quizzes/{qid}/revision", headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["version"] == 2
    # 旧版 superseded，新版 draft
    resp = client.get("/api/quizzes", headers=teacher_headers)
    qs = resp.get_json()["data"]["quizzes"]
    assert any(q["id"] == qid and q["status"] == "superseded" for q in qs)
    assert any(q["version"] == 2 and q["status"] == "draft" for q in qs)
