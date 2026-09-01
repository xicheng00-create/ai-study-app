"""作答 Blueprint（REQ-QUIZ-002/003/004）：学生作答 + GRADER 批改 + 测评报告。"""

from ai import grader
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, e_not_found, ok
from middleware.rate_limit import rate_limit

attempts_bp = Blueprint("attempts_bp", __name__, url_prefix="/api/quizzes")


def _latest_submission(con, user_id, quiz_id, version):
    """最近一次提交的时间戳（可重做取最近，QUIZ-002）。"""
    row = con.execute(
        "SELECT MAX(created_at) AS t FROM attempts"
        " WHERE user_id=? AND quiz_id=? AND quiz_version=?",
        (user_id, quiz_id, version),
    ).fetchone()
    return row["t"]


@attempts_bp.route("/<quiz_id>/attempts", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def submit_attempt(quiz_id):
    """学生作答并批改，写 attempts（含 quiz_version，F3）。"""
    data = request.get_json(silent=True) or {}
    answers = data.get("answers") or []
    if not isinstance(answers, list) or not answers:
        return e_input("缺少作答")

    con = get_db()
    quiz = con.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if quiz is None:
        return e_not_found("测评不存在")
    if quiz["status"] != "published":
        return e_input("该测评尚未发布，不可作答")

    now = models.utcnow()
    details = []
    correct_cnt = 0
    total_score = 0.0
    total = 0
    for item in answers:
        qid = item.get("question_id")
        ans = str(item.get("answer") or "")
        q = con.execute("SELECT * FROM questions WHERE id=? AND quiz_id=?", (qid, quiz_id)).fetchone()
        if q is None:
            continue
        result = grader.grade_question(
            {
                "type": q["type"],
                "content": q["content"],
                "options": q["options"],
                "answer_key": q["answer_key"],
            },
            ans,
        )
        total += 1
        correct_cnt += result["correct"]
        total_score += result["score"]
        con.execute(
            "INSERT INTO attempts (id, user_id, quiz_id, question_id, chapter_id, quiz_version,"
            " correct, score, answer, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (models.new_id(), g.user_id, quiz_id, qid, q["chapter_id"], quiz["version"],
             result["correct"], result["score"], ans, now),
        )
        details.append({
            "question_id": qid,
            "correct": result["correct"],
            "score": result["score"],
            "reason": result["reason"],
        })
    con.commit()

    score = round(total_score / total * 100, 1) if total else 0.0
    return ok({"score": score, "correct": correct_cnt, "total": total, "details": details})


@attempts_bp.route("/<quiz_id>/report", methods=["GET"])
@jwt_required
@role_required("student")
def quiz_report(quiz_id):
    """测评报告（QUIZ-004）：得分/错题/薄弱点。"""
    con = get_db()
    quiz = con.execute("SELECT * FROM quizzes WHERE id=?", (quiz_id,)).fetchone()
    if quiz is None:
        return e_not_found("测评不存在")
    t = _latest_submission(con, g.user_id, quiz_id, quiz["version"])
    if t is None:
        return ok({"taken": False, "score": None, "wrong": []})
    rows = con.execute(
        "SELECT a.*, q.content AS q_content, q.type AS q_type, q.options AS q_options,"
        " q.answer_key AS q_answer_key, q.sub_concept AS q_sub_concept"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=? AND a.quiz_id=? AND a.quiz_version=? AND a.created_at=?",
        (g.user_id, quiz_id, quiz["version"], t),
    ).fetchall()
    total = len(rows)
    correct = sum(1 for r in rows if r["correct"])
    score = round(sum(r["score"] for r in rows) / total * 100, 1) if total else 0.0
    wrong = []
    for r in rows:
        if not r["correct"]:
            wrong.append({
                "question_id": r["question_id"],
                "content": r["q_content"],
                "your_answer": r["answer"],
                "answer_key": r["q_answer_key"],
                "sub_concept": r["q_sub_concept"],
            })
    return ok({
        "taken": True,
        "score": score,
        "correct": correct,
        "total": total,
        "wrong": wrong,
    })
