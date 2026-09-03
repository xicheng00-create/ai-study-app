"""班级排行榜测试（REQ-CLASS-001~006）。"""
from conftest import login, make_student


def _chapter(client, teacher_headers, name="班级章"):
    resp = client.post("/api/chapters", json={"folder": "模块", "name": name}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def _draft_and_publish(client, teacher_headers, chapter_id):
    resp = client.post("/api/quizzes/draft", json={"chapter_ids": [chapter_id]}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    qid = resp.get_json()["data"]["id"]
    resp = client.post(f"/api/quizzes/{qid}/publish", headers=teacher_headers)
    assert resp.status_code == 200
    return qid


def test_leaderboard_excludes_hermestest(client, teacher_headers):
    """测试账号 Hermestest 绝不出现在班级榜单。"""
    make_student(client, teacher_headers, "alice", display_name="晨晨")
    make_student(client, teacher_headers, "Hermestest", display_name="测试号")
    teacher = login(client, "teacher", "teacher123")
    h = {"Authorization": f"Bearer {teacher}"}
    resp = client.get("/api/class/leaderboard", headers=h)
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    names = [s["display_name"] for s in d["students"]]
    assert "晨晨" in names
    assert "测试号" not in names
    assert all(e["display_name"] != "测试号" for e in d["total_turns"])
    assert all(e["display_name"] != "测试号" for e in d["mastery"])


def test_student_leaderboard_shape(client, teacher_headers):
    """学生可访问同班榜单，me_user_id 与 mastery 榜结构正确。"""
    uid = make_student(client, teacher_headers, "alice", display_name="晨晨")
    make_student(client, teacher_headers, "bob", display_name="小宇")
    alice = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {alice}"}
    resp = client.get("/api/class/leaderboard", headers=h)
    assert resp.status_code == 200
    d = resp.get_json()["data"]
    assert d["is_teacher"] is False
    assert d["me_user_id"] == uid
    assert len(d["mastery"]) == 2
    assert all(m["avg_m"] is None for m in d["mastery"])  # 无测评/练习 → 未评估


def test_quiz_leaderboard_absent_marking(client, teacher_headers):
    """测评分数榜：参加者得分+排名，未参加者标注 absent。"""
    cid = _chapter(client, teacher_headers)
    qid = _draft_and_publish(client, teacher_headers, cid)
    make_student(client, teacher_headers, "alice", display_name="晨晨")
    make_student(client, teacher_headers, "bob", display_name="小宇")
    alice = login(client, "alice", "student123")
    # 仅 alice 作答
    detail = client.get(f"/api/quizzes/{qid}", headers={"Authorization": f"Bearer {alice}"}).get_json()["data"]
    answers = [{"question_id": q["id"], "answer": "1"} for q in detail["questions"]]
    client.post(f"/api/quizzes/{qid}/attempts", json={"answers": answers},
                headers={"Authorization": f"Bearer {alice}"})

    teacher = login(client, "teacher", "teacher123")
    d = client.get("/api/class/leaderboard", headers={"Authorization": f"Bearer {teacher}"}).get_json()["data"]
    assert any(q["quiz_id"] == qid for q in d["quizzes"])
    board = d["quiz_boards"][qid]
    by_name = {e["display_name"]: e for e in board}
    assert by_name["晨晨"]["absent"] is False
    assert by_name["晨晨"]["rank"] == 1
    assert by_name["小宇"]["absent"] is True
    assert by_name["小宇"]["rank"] is None
