"""自主练习测试（REQ-PRACTICE-001~003）：AI 自主题量合计 100、GRADER 复用、错题联动。"""
from ai import agents, quizzer
from conftest import login, make_student


def _chapter(client, teacher_headers, name="练习章"):
    resp = client.post("/api/chapters", json={"folder": "模块", "name": name}, headers=teacher_headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]["id"]


def _generate(client, h, chapter_ids):
    resp = client.post("/api/practice/generate", json={"chapter_ids": chapter_ids}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()["data"]


# ---- 单元：AI 自主题量 + 难度 hard ----

def _mock_quizzer(monkeypatch, first_result, second_result=None):
    calls = []

    def fake_generate(system):
        calls.append(system)
        if len(calls) == 1:
            return first_result
        return second_result

    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    # 单元测试无 app context：绕过 RAG 检索（与出题链路本身无关）
    monkeypatch.setattr(quizzer.rag, "retrieve", lambda *a, **k: [])
    return calls


def _q(qtype, n):
    return [{"type": qtype, "content": f"q{i}", "options": ["A", "B"], "answer": "0",
             "reason": "", "sub_concept": ""} for i in range(n)]


def test_practice_free_form_exact_100(monkeypatch):
    """AI 固定 20 道选择时原样保留（合计 100 分）。"""
    _mock_quizzer(monkeypatch, _q("choice", 20))
    out = quizzer.generate_practice_questions(["ch1"])
    assert sum(quizzer.POINTS[q["type"]] for q in out) == 100
    assert len(out) == 20
    assert all(q["type"] in ("choice", "bool") for q in out)


def test_practice_trim_over_100(monkeypatch):
    """AI 出题超 100 分时裁剪到恰好 20 道（100 分）。"""
    _mock_quizzer(monkeypatch, _q("choice", 25))  # 125 分
    out = quizzer.generate_practice_questions(["ch1"])
    assert sum(quizzer.POINTS[q["type"]] for q in out) == 100
    assert len(out) == 20


def test_practice_fill_under_100(monkeypatch):
    """AI 出题不足 100 分时模板补足到恰好 20 道（100 分）。"""
    _mock_quizzer(monkeypatch, _q("choice", 5))  # 25 分
    out = quizzer.generate_practice_questions(["ch1"])
    assert sum(quizzer.POINTS[q["type"]] for q in out) == 100
    assert len(out) == 20


def test_practice_difficulty_hard(monkeypatch):
    """练习出题提示词注入 difficulty=hard（高于教师默认 normal）。"""
    calls = _mock_quizzer(monkeypatch, _q("choice", 20))
    quizzer.generate_practice_questions(["ch1"])
    assert "难度：hard" in calls[0]


def test_teacher_quiz_default_normal(monkeypatch):
    """教师测评默认难度仍为 normal，不被练习改动影响。"""
    calls = _mock_quizzer(monkeypatch, _q("choice", 1))
    quizzer.generate_questions(["ch1"], config={"choice": 1})
    assert "难度：normal" in calls[0]


# ---- API：生成/批改/隔离/错题联动 ----

def test_practice_generate_and_submit(client, teacher_headers):
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    token = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {token}"}

    data = _generate(client, h, [cid])
    assert data["difficulty"] == "hard"
    assert data["total_points"] == 100
    assert len(data["questions"]) > 0
    # 作答前不露答案
    assert all("answer_key" not in q for q in data["questions"])

    sid = data["id"]
    # 历史列表可见
    resp = client.get("/api/practice", headers=h)
    ids = [s["id"] for s in resp.get_json()["data"]["sessions"]]
    assert sid in ids

    # 全部空答 → GRADER 确定性判 0 分
    answers = [{"question_id": q["id"], "answer": ""} for q in data["questions"]]
    resp = client.post(f"/api/practice/{sid}/submit", json={"answers": answers}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    d = resp.get_json()["data"]
    assert d["score"] == 0.0
    assert d["total"] == len(data["questions"])
    # 提交返回每题正确答案
    assert all("answer_key" in x for x in d["details"])

    # 作答后详情含答案
    resp = client.get(f"/api/practice/{sid}", headers=h)
    qs = resp.get_json()["data"]["questions"]
    assert all("answer_key" in q for q in qs)
    assert resp.get_json()["data"]["session"]["completed"] is True


def test_practice_counts_toward_mastery(client, teacher_headers):
    """自主练习（已作答）计入掌握度 M（任务书定义 A，推翻旧 F3）。"""
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    token = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {token}"}
    data = _generate(client, h, [cid])
    sid = data["id"]
    answers = [{"question_id": q["id"], "answer": ""} for q in data["questions"]]
    client.post(f"/api/practice/{sid}/submit", json={"answers": answers}, headers=h)

    # 全错 → M=0.0，且作答次数计入（即使无 published quiz）
    resp = client.get("/api/progress/mastery", headers=h)
    chap = [c for c in resp.get_json()["data"]["chapters"] if c["chapter_id"] == cid][0]
    assert chap["m"] == 0.0
    assert chap["attempts"] == len(data["questions"])


def test_practice_wrong_flows_to_weak_and_review(client, teacher_headers):
    """练习错题进入薄弱点 + 巩固练习来源（PROG-005/006 保留）。"""
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    token = login(client, "alice", "student123")
    h = {"Authorization": f"Bearer {token}"}
    data = _generate(client, h, [cid])
    sid = data["id"]
    answers = [{"question_id": q["id"], "answer": ""} for q in data["questions"]]
    client.post(f"/api/practice/{sid}/submit", json={"answers": answers}, headers=h)

    # 薄弱点列表出现该章（全错 → M=0 即薄弱）
    resp = client.get("/api/progress/weak-points", headers=h)
    weak = resp.get_json()["data"]["weak_points"]
    assert any(w["chapter_id"] == cid for w in weak)

    # 巩固练习生成包含该章
    resp = client.post("/api/progress/review-items/generate", json={}, headers=h)
    assert resp.status_code == 200, resp.get_json()
    created = resp.get_json()["data"]["created"]
    assert created >= 1
    items = resp.get_json()["data"]["review_items"]
    assert any(i["chapter_id"] == cid for i in items)


def test_practice_isolation(client, teacher_headers):
    """学生 A 不能读/交学生 B 的练习（F9）。"""
    cid = _chapter(client, teacher_headers)
    make_student(client, teacher_headers, "alice")
    make_student(client, teacher_headers, "bob")
    alice = login(client, "alice", "student123")
    bob = login(client, "bob", "student123")
    data = _generate(client, {"Authorization": f"Bearer {alice}"}, [cid])
    sid = data["id"]
    # B 读 A 的练习 → 403
    resp = client.get(f"/api/practice/{sid}", headers={"Authorization": f"Bearer {bob}"})
    assert resp.status_code == 403
    # B 交 A 的练习 → 403
    resp = client.post(f"/api/practice/{sid}/submit", json={"answers": []},
                       headers={"Authorization": f"Bearer {bob}"})
    assert resp.status_code == 403
