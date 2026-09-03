"""自主练习 Blueprint（REQ-PRACTICE-001~003）：学生个人即席生成/作答/批改。

独立数据层 practice_sessions / practice_questions，不进教师发布状态机；
练习错题只作薄弱点/巩固练习依据，不改变测评掌握度 M（防污染 F3）。
"""
import json

from ai import grader, quizzer
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, e_not_found, ok
from middleware.rate_limit import rate_limit

practice_bp = Blueprint("practice_bp", __name__, url_prefix="/api/practice")


def _parse_ids(raw) -> list[str]:
    try:
        val = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def _get_session(con, session_id, user_id):
    return con.execute(
        "SELECT * FROM practice_sessions WHERE id=? AND user_id=?", (session_id, user_id)
    ).fetchone()


def _question_dict(row, with_answer=False) -> dict:
    d = {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "sub_concept": row["sub_concept"],
        "type": row["type"],
        "content": row["content"],
        "options": json.loads(row["options"] or "[]"),
        "points": row["points"],
    }
    # 作答前不露答案：仅已作答（含 teacher 侧无此场景）时返回
    if with_answer or row["answered_at"] is not None:
        d["answer_key"] = row["answer_key"]
        d["correct"] = row["correct"]
        d["score"] = row["score"]
        d["user_answer"] = row["user_answer"]
        d["reason"] = row["reason"]
    return d


def _session_dict(row, con=None) -> dict:
    d = {
        "id": row["id"],
        "chapter_ids": _parse_ids(row["chapter_ids"]),
        "difficulty": row["difficulty"],
        "total_points": row["total_points"],
        "created_at": row["created_at"],
    }
    if con is not None:
        agg = con.execute(
            "SELECT COUNT(*) AS c,"
            " SUM(CASE WHEN answered_at IS NOT NULL THEN 1 ELSE 0 END) AS answered,"
            " SUM(COALESCE(score, 0)) AS earned"
            " FROM practice_questions WHERE session_id=?", (row["id"],)
        ).fetchone()
        d["question_count"] = agg["c"]
        d["answered"] = agg["answered"] or 0
        d["completed"] = bool(agg["c"] and (agg["answered"] or 0) >= agg["c"])
        d["score"] = round((agg["earned"] or 0) / (row["total_points"] or 100) * 100, 1) if d["completed"] else None
    return d


@practice_bp.route("", methods=["GET"])
@jwt_required
@role_required("student")
def list_practice():
    """练习历史（每次生成一个新 session，历史保留）。"""
    con = get_db()
    rows = con.execute(
        "SELECT * FROM practice_sessions WHERE user_id=? ORDER BY created_at DESC", (g.user_id,)
    ).fetchall()
    return ok({"sessions": [_session_dict(r, con) for r in rows]})


@practice_bp.route("/generate", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def generate_practice():
    """选章 → AI 出题（difficulty=hard、自主题量、合计 100）→ 建会话（不露答案）。"""
    data = request.get_json(silent=True) or {}
    chapter_ids = data.get("chapter_ids") or []
    if (not isinstance(chapter_ids, list) or not chapter_ids
            or any(not isinstance(c, str) or not c.strip() for c in chapter_ids)):
        return e_input("请至少选择一章")
    chapter_ids = [c.strip() for c in chapter_ids]

    con = get_db()
    for cid in chapter_ids:
        row = con.execute(
            "SELECT id FROM chapters WHERE id=? AND status='published'", (cid,)
        ).fetchone()
        if row is None:
            return e_not_found(f"章节不存在或未发布：{cid}")

    raw_qs = quizzer.generate_practice_questions(chapter_ids, sub_concepts=data.get("sub_concepts", ""))
    total = sum(quizzer.POINTS[q["type"]] for q in raw_qs)
    if total != 100:
        return e_input(f"练习出题失败：合计 {total} 分，无法生成 100 分练习")

    session_id = models.new_id()
    now = models.utcnow()
    config = {t: sum(1 for q in raw_qs if q["type"] == t) for t in quizzer.POINTS}
    con.execute(
        "INSERT INTO practice_sessions (id, user_id, chapter_ids, difficulty, total_points,"
        " config_json, created_at) VALUES (?, ?, ?, 'hard', 100, ?, ?)",
        (session_id, g.user_id, json.dumps(chapter_ids, ensure_ascii=False),
         json.dumps(config, ensure_ascii=False), now),
    )
    for i, raw in enumerate(raw_qs):
        cid = chapter_ids[i % len(chapter_ids)]
        q = quizzer.norm_question(raw, cid)
        con.execute(
            "INSERT INTO practice_questions (id, session_id, chapter_id, sub_concept, type,"
            " content, options, answer_key, points, correct, user_answer, score, reason, answered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '', NULL, '', NULL)",
            (models.new_id(), session_id, cid, q["sub_concept"], q["type"], q["content"],
             q["options"], q["answer_key"], q["points"]),
        )
    con.commit()

    rows = con.execute(
        "SELECT * FROM practice_questions WHERE session_id=? ORDER BY rowid", (session_id,)
    ).fetchall()
    return ok({
        "id": session_id,
        "chapter_ids": chapter_ids,
        "total_points": 100,
        "difficulty": "hard",
        "config": config,
        "questions": [_question_dict(r) for r in rows],
    })


@practice_bp.route("/<session_id>/submit", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def submit_practice(session_id):
    """作答并批改（复用 GRADER）：写 correct/score/user_answer，返回每题得分+答案。"""
    con = get_db()
    # 先校验资源归属（F9），再校验入参
    session = _get_session(con, session_id, g.user_id)
    if session is None:
        return e_forbidden("只能访问本人练习")

    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or []
    if not isinstance(answers, list) or not answers:
        return e_input("缺少作答")

    now = models.utcnow()
    details = []
    correct_cnt = 0
    earned = 0.0
    possible = 0.0
    total = 0
    for item in answers:
        qid = item.get("question_id")
        ans = str(item.get("answer") or "")
        q = con.execute(
            "SELECT * FROM practice_questions WHERE id=? AND session_id=?", (qid, session_id)
        ).fetchone()
        if q is None:
            continue
        result = grader.grade_question(
            {
                "type": q["type"],
                "content": q["content"],
                "options": q["options"],
                "answer_key": q["answer_key"],
                "points": q["points"],
            },
            ans,
        )
        total += 1
        correct_cnt += result["correct"]
        earned += result["score"]
        possible += float(q["points"]) if q["points"] else 0.0
        con.execute(
            "UPDATE practice_questions SET correct=?, user_answer=?, score=?, reason=?, answered_at=?"
            " WHERE id=?",
            (result["correct"], ans, result["score"], result["reason"], now, qid),
        )
        details.append({
            "question_id": qid,
            "correct": result["correct"],
            "score": result["score"],
            "points": float(q["points"]) if q["points"] else 0.0,
            "answer_key": q["answer_key"],
            "reason": result["reason"],
        })
    con.commit()

    score = round(earned / possible * 100, 1) if possible else 0.0
    return ok({
        "score": score,
        "correct": correct_cnt,
        "total": total,
        "earned": round(earned, 1),
        "total_points": round(possible, 1),
        "details": details,
    })


@practice_bp.route("/<session_id>", methods=["GET"])
@jwt_required
@role_required("student")
def get_practice(session_id):
    """练习详情（已答题含答案，作答后查看）。"""
    con = get_db()
    session = _get_session(con, session_id, g.user_id)
    if session is None:
        return e_forbidden("只能访问本人练习")
    rows = con.execute(
        "SELECT * FROM practice_questions WHERE session_id=? ORDER BY rowid", (session_id,)
    ).fetchall()
    return ok({"session": _session_dict(session, con), "questions": [_question_dict(r) for r in rows]})
