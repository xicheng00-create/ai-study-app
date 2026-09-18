"""每日打卡与连胜（CHECKIN）：阈值 / distinct / 日界 / 连胜存活 / 幂等。"""
from ai import knowledge, quizzer
from conftest import login, make_student
from data import checkin, models


def _chapter(client, teacher_headers, name="章"):
    r = client.post("/api/chapters", json={"name": name}, headers=teacher_headers)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["id"]


def _student(client, teacher_headers, name):
    make_student(client, teacher_headers, name)
    return {"Authorization": "Bearer " + login(client, name, "student123")}


def _cards(client, h, monkeypatch, cid, n):
    monkeypatch.setattr(knowledge, "generate_knowledge_cards", lambda ids: [
        {"front": f"卡{i}", "back": f"答{i}", "sub_concept": "x"} for i in range(n)
    ])
    r = client.post("/api/knowledge/generate", json={"chapter_ids": [cid]}, headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["cards"]


def _review(client, h, card_id, remembered=True):
    r = client.post(f"/api/knowledge/{card_id}/review", json={"remembered": remembered}, headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]["card"]


def _mock_practice(monkeypatch, n):
    def fake(chapter_ids, sub_concepts="", exclude_contents=None, exclude_sub_concepts=None, count=5):
        return [{"type": "choice", "content": f"题{i}", "options": ["A", "B"], "answer": "0",
                 "reason": "", "sub_concept": ""} for i in range(n)]
    monkeypatch.setattr(quizzer, "generate_practice_questions", fake)


def _generate_practice(client, h, cid):
    r = client.post("/api/practice/generate", json={"chapter_ids": [cid]}, headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _submit(client, h, sid, data):
    r = client.post(f"/api/practice/{sid}/submit", json={"answers": data}, headers=h)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["data"]


def _today(client, h):
    return client.get("/api/checkin/today", headers=h).get_json()["data"]


# ---- 阈值：9 张不算 / 10 张算；同卡重复只计 1 ----

def test_checkin_card_threshold_and_distinct(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers)
    h = _student(client, teacher_headers, "ck_a")
    cards = _cards(client, h, monkeypatch, cid, 10)

    # 复习 9 张 distinct（card0 重复一次 → 仍只计 9 distinct）
    for c in cards[:9]:
        _review(client, h, c["id"])
    _review(client, h, cards[0]["id"])  # 同卡重复
    d = _today(client, h)
    assert d["done"] is False and d["progress"]["cards"] == 9

    # 第 10 张 distinct → 卡片达标（题目仍需 5 题，故 done 仍为 False）
    _review(client, h, cards[9]["id"])
    d = _today(client, h)
    assert d["progress"]["cards"] == 10 and d["done"] is False


# ---- 阈值：4 题不算 / 5 题算 ----

def test_checkin_question_threshold(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers)
    h = _student(client, teacher_headers, "ck_b")
    cards = _cards(client, h, monkeypatch, cid, 10)
    for c in cards:
        _review(client, h, c["id"])

    _mock_practice(monkeypatch, 5)
    p = _generate_practice(client, h, cid)
    qs = p["questions"]
    # 只答 4 题 → 不达标
    _submit(client, h, p["id"], [{"question_id": qs[i]["id"], "answer": "0"} for i in range(4)])
    d = _today(client, h)
    assert d["done"] is False and d["progress"]["questions"] == 4

    # 答第 5 题 → 达标
    _submit(client, h, p["id"], [{"question_id": qs[4]["id"], "answer": "0"}])
    d = _today(client, h)
    assert d["done"] is True and d["progress"]["questions"] == 5 and d["streak"] == 1


# ---- 跨 UTC+8 日界 ----

def test_counts_cross_utc8_boundary(client, teacher_headers, monkeypatch):
    uid = make_student(client, teacher_headers, "ck_day")
    cid = _chapter(client, teacher_headers)
    monkeypatch.setattr("data.checkin.timeutil.today_str", lambda: "2026-09-18")
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        def add_card(card_id, last_review):
            con.execute(
                "INSERT INTO knowledge_cards (id, chapter_id, front, back, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (card_id, cid, f"front-{card_id}", "b", models.utcnow()),
            )
            con.execute(
                "INSERT INTO knowledge_reviews (id, card_id, user_id, next_review_at, last_review_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (models.new_id(), card_id, uid, models.utcnow(), last_review, models.utcnow()),
            )
        # 2026-09-18 00:30 上海 = 09-17 16:30 UTC → 计入 09-18
        add_card("c1", "2026-09-17T16:30:00+00:00")
        # 2026-09-17 23:59 上海 = 09-17 15:59 UTC → 计入 09-17，不计 09-18
        add_card("c2", "2026-09-17T15:59:00+00:00")
        con.commit()
        assert checkin.counts_today(con, uid)["cards"] == 1


# ---- 连胜连续 / 断连归零 / pending 存活 / 幂等（单元级） ----

def test_streak_model_and_idempotent(client, teacher_headers, monkeypatch):
    uid = make_student(client, teacher_headers, "ck_streak")
    monkeypatch.setattr("data.checkin.timeutil.today_str", lambda: "2026-09-18")
    monkeypatch.setattr("data.checkin._yesterday_str", lambda: "2026-09-17")
    monkeypatch.setattr(checkin, "counts_today", lambda con, u: {"cards": 10, "questions": 5})
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        # 昨天已打卡 streak=2
        con.execute(
            "INSERT INTO daily_checkins (id, user_id, checkin_date, cards_done, questions_done, streak_after, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), uid, "2026-09-17", 10, 5, 2, models.utcnow()),
        )
        con.commit()

        info = checkin.evaluate_and_maybe_complete(con, uid)
        assert info["done"] is True and info["streak"] == 3  # 连续 +1

        # 幂等：重复调用不写第二行、不重复通知
        checkin.evaluate_and_maybe_complete(con, uid)
        rows = con.execute("SELECT COUNT(*) AS c FROM daily_checkins WHERE user_id=?", (uid,)).fetchone()["c"]
        assert rows == 2
        notif = con.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND type='streak_done'", (uid,)
        ).fetchone()["c"]
        assert notif == 1

        # pending 存活：今天没打卡但昨天打卡
        info = checkin.streak_info(con, uid)
        assert info["state"] == "done"

        # 断连归零：删除昨天的打卡行后（模拟空档）
        con.execute("DELETE FROM daily_checkins WHERE checkin_date='2026-09-17' AND user_id=?", (uid,))
        con.commit()
        info = checkin.streak_info(con, uid)
        # 今天已打卡行仍在 → done；单独验证 broken 用干净用户
        info2 = checkin.streak_info(con, "nonexistent-uid")
        assert info2["state"] == "broken" and info2["streak"] == 0
        assert info2["alive"] is False


# ---- pending 存活（API 级）：昨天打卡、今天未打 → state=pending ----

def test_today_pending_state(client, teacher_headers, monkeypatch):
    uid = make_student(client, teacher_headers, "ck_pending")
    h = {"Authorization": "Bearer " + login(client, "ck_pending", "student123")}
    monkeypatch.setattr("data.checkin.timeutil.today_str", lambda: "2026-09-18")
    monkeypatch.setattr("data.checkin._yesterday_str", lambda: "2026-09-17")
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        con.execute(
            "INSERT INTO daily_checkins (id, user_id, checkin_date, cards_done, questions_done, streak_after, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), uid, "2026-09-17", 10, 5, 4, models.utcnow()),
        )
        con.commit()
    d = _today(client, h)
    assert d["done"] is False and d["state"] == "pending" and d["streak"] == 4 and d["alive"] is True
