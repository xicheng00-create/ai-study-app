"""每日打卡与连胜（CHECKIN）：阈值 / distinct / 日界 / 连胜存活 / 幂等。"""
import random
from datetime import timedelta

from ai import knowledge, quizzer
from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED
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


# ---- 阈值：n-1 张不算 / n 张算；同卡重复只计 1（n = config.TASK_CARDS_REQUIRED，不写死） ----

def test_checkin_card_threshold_and_distinct(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers)
    h = _student(client, teacher_headers, "ck_a")
    n = TASK_CARDS_REQUIRED
    cards = _cards(client, h, monkeypatch, cid, n)

    # 复习 n-1 张 distinct（card0 重复一次 → 仍只计 n-1 distinct）
    for c in cards[: n - 1]:
        _review(client, h, c["id"])
    _review(client, h, cards[0]["id"])  # 同卡重复
    d = _today(client, h)
    assert d["done"] is False and d["progress"]["cards"] == n - 1
    assert d["task"]["cards_required"] == n  # 阈值随数据下发（前端不再硬编码）

    # 第 n 张 distinct → 卡片达标（题目仍需 5 题，故 done 仍为 False）
    _review(client, h, cards[n - 1]["id"])
    d = _today(client, h)
    assert d["progress"]["cards"] == n and d["done"] is False


# ---- 回归（2026-09-19 用户实报「4/10 卡却显示今日已完成」）：进度不得倒退 ----

def test_progress_today_never_regresses(client, teacher_headers, monkeypatch):
    """卡片库重建会重置复习记录 → 实时计数掉到达标值以下；当日快照是下限。"""
    uid = make_student(client, teacher_headers, "ck_floor")
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        con.execute(
            "INSERT INTO daily_checkins (id, user_id, checkin_date, cards_done, questions_done,"
            " streak_after, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), uid, timeutil.today_str(), TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED,
             1, models.utcnow()),
        )
        con.commit()
        monkeypatch.setattr(checkin, "counts_today", lambda con, u: {"cards": 0, "questions": 0})
        p = checkin.progress_today(con, uid)
        assert p["cards"] == TASK_CARDS_REQUIRED and p["questions"] == TASK_QUESTIONS_REQUIRED
        # 无当日打卡行时 = 纯实时计数（不凭空抬高）
        monkeypatch.setattr(checkin, "counts_today", lambda con, u: {"cards": 2, "questions": 1})
        p2 = checkin.progress_today(con, "nonexistent-uid")
        assert p2 == {"cards": 2, "questions": 1}


# ---- 阈值：4 题不算 / 5 题算 ----

def test_checkin_question_threshold(client, teacher_headers, monkeypatch):
    cid = _chapter(client, teacher_headers)
    h = _student(client, teacher_headers, "ck_b")
    cards = _cards(client, h, monkeypatch, cid, TASK_CARDS_REQUIRED)
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
    monkeypatch.setattr(checkin, "counts_today",
                        lambda con, u: {"cards": TASK_CARDS_REQUIRED, "questions": TASK_QUESTIONS_REQUIRED})
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


def test_deck_order_follows_course_order(client, teacher_headers, monkeypatch):
    """档① 按课程顺序（chapters.folder/order_no/name）而非 UUID 字典序：id 字典序与 order_no 相反时仍先发 order_no 小的章。"""
    uid = make_student(client, teacher_headers, "deck_order")
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        # id 字典序 "zzz" > "aaa"，但 order_no=1 的章（"zzz"）应排最前
        con.execute(
            "INSERT INTO chapters (id, name, order_no, status, created_at) VALUES (?, ?, ?, 'published', ?)",
            ("zzz-ch-1", "第1节", 1, models.utcnow()),
        )
        con.execute(
            "INSERT INTO chapters (id, name, order_no, status, created_at) VALUES (?, ?, ?, 'published', ?)",
            ("aaa-ch-2", "第2节", 2, models.utcnow()),
        )
        for cid in ("zzz-ch-1", "aaa-ch-2"):
            for i in range(2):
                _insert_card(con, f"{cid}-c{i}", cid, f"{cid}-c{i}")
        con.commit()
        deck = checkin.build_today_deck(con, uid, limit=4, rng=random.Random(42))
        ids = [c["id"] for c in deck["cards"]]
        # 先 order_no=1 章的 2 张，再 order_no=2 章的 2 张
        assert ids[:2] == ["zzz-ch-1-c0", "zzz-ch-1-c1"]
        assert ids[2:4] == ["aaa-ch-2-c0", "aaa-ch-2-c1"]


# ---- 范围自定（v2.6.5 / CHECKIN-013）：学生勾选范围驱动卡组与练习 ----

def test_today_deck_respects_student_scope(client, teacher_headers, monkeypatch):
    """卡组只从勾选章节装配；不带范围=全部已发布；范围内无卡→明确 reason，不偷偷回落全部。"""
    h = _student(client, teacher_headers, "scope_deck")
    c1 = _chapter(client, teacher_headers, "范围甲")
    c2 = _chapter(client, teacher_headers, "范围乙")
    _cards(client, h, monkeypatch, c1, 3)
    _cards(client, h, monkeypatch, c2, 4)

    d = client.get(f"/api/knowledge/today?chapter_ids={c1}", headers=h).get_json()["data"]
    assert d["scope"] == {"chapter_ids": [c1], "scoped": True, "count": 1}
    assert len(d["cards"]) == 3
    assert {c["chapter_id"] for c in d["cards"]} == {c1}

    d2 = client.get("/api/knowledge/today", headers=h).get_json()["data"]
    assert d2["scope"]["scoped"] is False
    assert {c["chapter_id"] for c in d2["cards"]} == {c1, c2}

    c3 = _chapter(client, teacher_headers, "范围丙无卡")
    d3 = client.get(f"/api/knowledge/today?chapter_ids={c3}", headers=h).get_json()["data"]
    assert d3["cards"] == []
    assert d3["empty_reason"] == "no_cards_in_scope"


def test_start_practice_respects_student_scope(client, teacher_headers, monkeypatch):
    """练习出题只在勾选章节内；同范围可续答；未勾选=不锁范围（老行为）。"""
    h = _student(client, teacher_headers, "scope_practice")
    c1 = _chapter(client, teacher_headers, "练甲")
    c2 = _chapter(client, teacher_headers, "练乙")
    _mock_practice(monkeypatch, 5)

    r = client.post("/api/checkin/start-practice", json={"chapter_ids": [c1]}, headers=h)
    assert r.status_code == 200, r.get_json()
    assert not r.get_json()["data"].get("reused")
    sid = r.get_json()["data"]["session_id"]
    with client.application.app_context():
        from data.db import get_db
        con = get_db()
        used = {x["chapter_id"] for x in con.execute(
            "SELECT DISTINCT chapter_id FROM practice_questions WHERE session_id=?", (sid,)).fetchall()}
        scope = str(con.execute("SELECT chapter_ids FROM practice_sessions WHERE id=?",
                                (sid,)).fetchone()["chapter_ids"])
    assert used == {c1}
    assert c1 in scope and c2 not in scope

    r2 = client.post("/api/checkin/start-practice", json={"chapter_ids": [c1]}, headers=h)
    assert r2.get_json()["data"]["reused"] is True

    r3 = client.post("/api/checkin/start-practice", json={}, headers=h)
    assert r3.status_code == 200
