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
