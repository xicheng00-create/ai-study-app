"""掌握度 M 与四态测试（PROG-007/008，F3）。"""
import json
from datetime import datetime, timedelta, timezone

from ai import mastery
from data import models


def _db(client):
    return client.application.app_context()


def _seed_user(con, username="stu"):
    uid = models.new_id()
    con.execute(
        "INSERT INTO users (id, username, password_hash, role, display_name, grade, is_active, created_at)"
        " VALUES (?, ?, 'x', 'student', ?, '', 1, ?)",
        (uid, username, username, models.utcnow()),
    )
    return uid


def _seed_chapter(con, name="感知机"):
    cid = models.new_id()
    con.execute("INSERT INTO chapters (id, folder, name, order_no, created_by, created_at)"
                " VALUES (?, '模块一', ?, 0, NULL, ?)", (cid, name, models.utcnow()))
    return cid


def _seed_quiz(con, chapter_ids, version=1, status="published"):
    qid = models.new_id()
    con.execute(
        "INSERT INTO quizzes (id, title, chapter_ids, version, teacher_id, status, created_at, published_at)"
        " VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
        (qid, f"q v{version}", json.dumps(chapter_ids, ensure_ascii=False), version,
         status, models.utcnow(), models.utcnow()),
    )
    # 建一道真实题目（attempts 外键需要；选择题满分 5 分）
    for cid in chapter_ids:
        con.execute(
            "INSERT INTO questions (id, quiz_id, chapter_id, sub_concept, type, content,"
            " options, answer_key, points, created_at)"
            " VALUES (?, ?, ?, '', 'choice', '题', '[]', '0', 5, ?)",
            (models.new_id(), qid, cid, models.utcnow()),
        )
    return qid


def _seed_attempt(con, user_id, chapter_id, quiz_version, score, days_ago=0):
    created = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    # 找到对应 quiz + question 的真实 id
    quiz = con.execute(
        "SELECT id FROM quizzes WHERE chapter_ids LIKE ? AND version=?",
        (f'%"{chapter_id}"%', quiz_version),
    ).fetchone()
    qst = con.execute("SELECT id FROM questions WHERE quiz_id=?", (quiz["id"],)).fetchone()
    con.execute(
        "INSERT INTO attempts (id, user_id, quiz_id, question_id, chapter_id, quiz_version,"
        " correct, score, answer, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
        (models.new_id(), user_id, quiz["id"], qst["id"], chapter_id, quiz_version,
         1 if score >= 5 else 0, score, created),
    )


def _seed_practice(con, user_id, chapter_id, score, days_ago=0):
    """建一条已作答的自主练习（选择题满分 5 分）。"""
    answered = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    sid = models.new_id()
    con.execute(
        "INSERT INTO practice_sessions (id, user_id, chapter_ids, difficulty, total_points,"
        " config_json, created_at) VALUES (?, ?, ?, 'hard', 100, '{}', ?)",
        (sid, user_id, json.dumps([chapter_id], ensure_ascii=False), models.utcnow()),
    )
    con.execute(
        "INSERT INTO practice_questions (id, session_id, chapter_id, sub_concept, type, content,"
        " options, answer_key, points, correct, user_answer, score, reason, answered_at)"
        " VALUES (?, ?, ?, '', 'choice', '题', '[]', '0', 5, ?, '', ?, '', ?)",
        (models.new_id(), sid, chapter_id, 1 if score >= 5 else 0, score, answered),
    )
    return sid


def test_four_states_mapping():
    assert mastery.mastery_state(None, 0) == "na"
    assert mastery.mastery_state(30, 3) == "weak"
    assert mastery.mastery_state(60, 3) == "progress"
    assert mastery.mastery_state(90, 1) == "progress"  # 高分但证据不足
    assert mastery.mastery_state(90, 2) == "master"


def test_compute_mastery_weighted(client):
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'alice')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=5.0, days_ago=0)
        _seed_attempt(con, uid, cid, 1, score=0.0, days_ago=28)
        m = mastery.compute_mastery(con, uid, cid)
        # 权重 1 与 0.5^4=0.0625 → M≈94.1
        assert m["m"] is not None and m["m"] > 80
        assert mastery.mastery_state(m["m"], m["attempts"]) == "master"


def test_compute_mastery_no_attempt_is_na(client):
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        _seed_quiz(con, [cid], version=1)
        m = mastery.compute_mastery(con, models.new_id(), cid)
        assert m["m"] is None
        assert mastery.mastery_state(m["m"], 0) == "na"


def test_f3_latest_version_only(client):
    """重出题后旧 version 成绩不污染掌握度（F3）。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'bob')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=0.0, days_ago=1)
        # 重出 v2，最新 version=2，全对
        _seed_quiz(con, [cid], version=2)
        _seed_attempt(con, uid, cid, 2, score=5.0, days_ago=0)
        assert mastery.latest_version_for_chapter(con, cid) == 2
        m = mastery.compute_mastery(con, uid, cid)
        assert m["m"] == 100.0


def test_practice_only_computes_mastery(client):
    """某章只有练习无测评，M 仍可由练习计算（不因 latest<=0 返回 None，定义 A）。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'alice')
        _seed_practice(con, uid, cid, score=5.0)
        m = mastery.compute_mastery(con, uid, cid)
        assert m["m"] == 100.0
        assert m["attempts"] == 1
        assert m["latest_version"] == 0


def test_compute_mastery_combines_quiz_and_practice(client):
    """测评与练习同权重聚合（定义 A）。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'carol')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=5.0, days_ago=0)
        _seed_practice(con, uid, cid, score=0.0, days_ago=0)
        m = mastery.compute_mastery(con, uid, cid)
        # 测评 5/5 + 练习 0/5 → M=50%，作答次数=2
        assert m["m"] == 50.0
        assert m["attempts"] == 2


def _seed_card(con, user_id, chapter_id, status="mastered", days_ago=0):
    """建共享知识卡 + 学生复习状态行（v2.0.0 知识卡计入 M）。"""
    cid = models.new_id()
    con.execute("INSERT INTO knowledge_cards (id, chapter_id, sub_concept, front, back, created_at)"
                " VALUES (?, ?, '', 'front', 'back', ?)", (cid, chapter_id, models.utcnow()))
    last = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    con.execute(
        "INSERT INTO knowledge_reviews (id, card_id, user_id, learn_count, interval_days,"
        " next_review_at, status, last_review_at, created_at)"
        " VALUES (?, ?, ?, 3, 7, ?, ?, ?, ?)",
        (models.new_id(), cid, user_id, last, status, last, models.utcnow()),
    )
    return cid


def test_mastered_cards_contribute_to_mastery(client):
    """测评全错 + 1 张 mastered 卡 → M=50%（卡 5 分满分计入，拉高且 attempts 计数）。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'dave')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=0.0, days_ago=0)   # 0/5
        _seed_card(con, uid, cid, status="mastered", days_ago=0)  # 5/5
        m = mastery.compute_mastery(con, uid, cid)
        assert m["m"] == 50.0
        assert m["attempts"] == 2
        assert mastery.mastery_state(m["m"], m["attempts"]) == "progress"  # 无卡时 0% 为 weak


def test_mastered_card_age_decay(client):
    """卡按 last_review_at 衰减：28 天前掌握的卡权重 0.5^4=0.0625。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'erin')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=5.0, days_ago=28)  # 老成绩也衰减
        _seed_card(con, uid, cid, status="mastered", days_ago=28)
        m = mastery.compute_mastery(con, uid, cid)
        # 5w + 5w(同为 28 天前) → M=100 但用衰减权重检验 attempts 照计
        assert m["m"] == 100.0
        assert m["attempts"] == 2


def test_learning_cards_do_not_penalize_mastery(client):
    """非 mastered 卡不进分子也不进分母：全对测评 + learning 卡 → M 仍 100；只有 learning 卡无作答 → na。"""
    from data.db import get_db
    with _db(client):
        con = get_db()
        cid = _seed_chapter(con)
        uid = _seed_user(con, 'frank')
        _seed_quiz(con, [cid], version=1)
        _seed_attempt(con, uid, cid, 1, score=5.0, days_ago=0)
        _seed_card(con, uid, cid, status="learning", days_ago=0)
        m = mastery.compute_mastery(con, uid, cid)
        assert m["m"] == 100.0
        assert m["attempts"] == 1
        # 只有未掌握卡、无任何作答 → 维持 na，不因卡产生虚假掌握度
        cid2 = _seed_chapter(con, name="线性回归")
        uid2 = _seed_user(con, 'grace')
        _seed_card(con, uid2, cid2, status="learning", days_ago=0)
        m2 = mastery.compute_mastery(con, uid2, cid2)
        assert m2["m"] is None and m2["attempts"] == 0
        assert mastery.mastery_state(m2["m"], m2["attempts"]) == "na"
