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


def test_draft_config_must_sum_100(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    # 自定义组合合计非 100 → 400
    resp = client.post("/api/quizzes/draft", json={"chapter_ids": [cid], "config": {"choice": 1}},
                       headers=teacher_headers)
    assert resp.status_code == 400


def test_draft_preset_is_100_points(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    resp = client.post("/api/quizzes/draft",
                       json={"chapter_ids": [cid], "config": {"choice": 20}},
                       headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    qid = resp.get_json()["data"]["id"]
    detail = client.get(f"/api/quizzes/{qid}", headers=teacher_headers).get_json()["data"]
    assert detail["quiz"]["total_points"] == 100
    assert sum(q["points"] for q in detail["questions"]) == 100


def test_teacher_review_attempt(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    qid = _draft_and_publish(client, teacher_headers, cid)
    sid = make_student(client, teacher_headers, "alice")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    detail = client.get(f"/api/quizzes/{qid}", headers=h).get_json()["data"]
    qs = detail["questions"]
    # 全答错
    answers = [{"question_id": q["id"], "answer": ""} for q in qs]
    client.post(f"/api/quizzes/{qid}/attempts", json={"answers": answers}, headers=h)
    # 教师取该学生测评详情，拿到 attempt id
    resp = client.get(f"/api/teacher/students/{sid}/quizzes", headers=teacher_headers)
    attempts = resp.get_json()["data"]["attempts"]
    assert attempts and attempts[0]["details"]
    first = attempts[0]["details"][0]
    # 覆核改分：给该题满分
    resp = client.put(f"/api/attempts/{first['id']}/review",
                      json={"score": first["points"]}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"]["graded_by"] == "teacher"
    assert resp.get_json()["data"]["is_reviewed"] == 1
    # 越界分数被拒
    resp = client.put(f"/api/attempts/{first['id']}/review",
                      json={"score": first["points"] + 1}, headers=teacher_headers)
    assert resp.status_code == 400
