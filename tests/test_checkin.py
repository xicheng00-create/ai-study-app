"""每日打卡与连胜（CHECKIN）：阈值 / distinct / 日界 / 连胜存活 / 幂等。"""
import random
from datetime import timedelta

from ai import knowledge, quizzer
from conftest import login, make_student
from data import checkin, models, timeutil


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


# ---- 卡组三档装配（CHECKIN-009~012）----

def _insert_card(con, card_id, cid, front):
    con.execute(
        "INSERT INTO knowledge_cards (id, chapter_id, front, back, created_at) VALUES (?, ?, ?, ?, ?)",
        (card_id, cid, front, "b", models.utcnow()),
    )


def _insert_review(con, card_id, uid, *, learn_count=0, status="new", interval_days=1,
                   next_review_at=None, last_review_at=None):
    con.execute(
        "INSERT INTO knowledge_reviews (id, card_id, user_id, learn_count, interval_days,"
        " next_review_at, status, last_review_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (models.new_id(), card_id, uid, learn_count, interval_days,
         next_review_at or models.utcnow(), status, last_review_at, models.utcnow()),
    )


def test_deck_three_tier_priority(client, teacher_headers, monkeypatch):
    """三档优先级：未学（learn_count=0）→ 到期复习 → 低掌握随机补足。"""
    uid = make_student(client, teacher_headers, "deck_tier")
    cid = _chapter(client, teacher_headers)
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        for i in range(3):                                   # 未学（无 review 行）
            _insert_card(con, f"u{i}", cid, f"未学{i}")
        for i in range(3):                                   # 到期复习（learn_count>0，已到期）
            _insert_card(con, f"d{i}", cid, f"到期{i}")
            _insert_review(con, f"d{i}", uid, learn_count=2, status="learning",
                           next_review_at=f"2020-01-0{i + 1}T00:00:00+00:00")
        for i in range(3):                                   # 已学未到期（不进档②）
            _insert_card(con, f"m{i}", cid, f"未到期{i}")
            _insert_review(con, f"m{i}", uid, learn_count=2, status="reviewing",
                           next_review_at="2099-01-01T00:00:00+00:00")
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=5, rng=random.Random(42))
        ids = [c["id"] for c in deck["cards"]]
        assert ids[:3] == ["u0", "u1", "u2"]                  # 未学优先，按课程顺序
        assert ids[3:5] == ["d0", "d1"]                       # 到期复习按到期时间升序补足


def test_deck_unlearned_means_learn_count_zero(client, teacher_headers, monkeypatch):
    """「未学习」口径 = learn_count=0（有 review 行也仍算未学，排最前）。"""
    uid = make_student(client, teacher_headers, "deck_unlearned")
    cid = _chapter(client, teacher_headers)
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        _insert_card(con, "a", cid, "看过一眼")
        _insert_review(con, "a", uid, learn_count=0, status="new", next_review_at=models.utcnow())
        _insert_card(con, "b", cid, "学过未到期")
        _insert_review(con, "b", uid, learn_count=3, status="learning",
                       next_review_at="2099-01-01T00:00:00+00:00")
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=2, rng=random.Random(42))
        assert deck["cards"][0]["id"] == "a" and deck["cards"][0]["learn_count"] == 0
        assert deck["cards"][1]["id"] == "b"


def test_deck_mastered_still_fills(client, teacher_headers, monkeypatch):
    """用户实报 bug 回归：全 mastered / 未到期时仍发满 10 张，永不返回空。"""
    uid = make_student(client, teacher_headers, "deck_mastered")
    cid = _chapter(client, teacher_headers)
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        for i in range(12):
            _insert_card(con, f"m{i}", cid, f"mastered{i}")
            _insert_review(con, f"m{i}", uid, learn_count=5, status="mastered",
                           next_review_at="2099-01-01T00:00:00+00:00")
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=10, rng=random.Random(42))
        assert len(deck["cards"]) == 10
        assert deck["empty_reason"] == ""
        assert deck["short"] is False


def test_deck_same_seed_deterministic(client, teacher_headers, monkeypatch):
    """同 seed 两次调用返回同一 id 序列（测试确定性）。"""
    uid = make_student(client, teacher_headers, "deck_seed")
    cid = _chapter(client, teacher_headers)
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        for i in range(12):
            _insert_card(con, f"s{i}", cid, f"seed{i}")
            _insert_review(con, f"s{i}", uid, learn_count=1, status="mastered",
                           next_review_at="2099-01-01T00:00:00+00:00")
        con.commit()
        a = [c["id"] for c in checkin.build_today_deck(con, uid, limit=10, rng=random.Random(42))["cards"]]
        b = [c["id"] for c in checkin.build_today_deck(con, uid, limit=10, rng=random.Random(42))["cards"]]
        assert a == b


def test_deck_low_mastery_priority(client, teacher_headers, monkeypatch):
    """档③低掌握度优先：learning 填满候选池时 mastered 被挤出（不进入卡组）。"""
    uid = make_student(client, teacher_headers, "deck_low")
    cid = _chapter(client, teacher_headers)
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        for i in range(30):                                   # learning 权重 1，排最前
            _insert_card(con, f"l{i}", cid, f"learning{i}")
            _insert_review(con, f"l{i}", uid, learn_count=1, status="learning",
                           next_review_at="2099-01-01T00:00:00+00:00")
        for i in range(5):                                    # mastered 权重 3，排最后
            _insert_card(con, f"m{i}", cid, f"mastered{i}")
            _insert_review(con, f"m{i}", uid, learn_count=5, status="mastered",
                           next_review_at="2099-01-01T00:00:00+00:00")
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=10, rng=random.Random(42))
        assert all(c["status"] == "learning" for c in deck["cards"])


def test_deck_extra_excludes_today_reviewed(client, teacher_headers, monkeypatch):
    """mode=extra 排除今日已复习的卡，且 short 恒 False、extra 标记置 True。"""
    uid = make_student(client, teacher_headers, "deck_extra")
    cid = _chapter(client, teacher_headers)
    today_iso = timeutil.shanghai_now().isoformat()
    yesterday_iso = (timeutil.shanghai_now() - timedelta(days=1)).isoformat()
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        for card_id, last in (("a", today_iso), ("b", yesterday_iso)):
            _insert_card(con, card_id, cid, f"extra-{card_id}")
            _insert_review(con, card_id, uid, learn_count=1, status="learning",
                           next_review_at="2099-01-01T00:00:00+00:00", last_review_at=last)
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=10, mode="extra", rng=random.Random(42))
        ids = [c["id"] for c in deck["cards"]]
        assert deck["extra"] is True and deck["short"] is False
        assert "a" not in ids and "b" in ids


def test_deck_empty_reason_no_published_cards(client, teacher_headers, monkeypatch):
    """真真空（库中无已发布章节的卡）→ cards 空 + empty_reason=no_published_cards。"""
    uid = make_student(client, teacher_headers, "deck_empty")
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        deck = checkin.build_today_deck(con, uid, limit=10, rng=random.Random(42))
        assert deck["cards"] == []
        assert deck["empty_reason"] == "no_published_cards"
