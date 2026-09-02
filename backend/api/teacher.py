"""教师管理后台 Blueprint（REQ-ADMIN-001~003）：聚合走独立路由，不经 @user_scope。"""
from collections import Counter

from ai import mastery
from auth.jwt_utils import jwt_required, role_required
from data.db import get_db
from flask import Blueprint, request
from middleware.errors import e_input, e_not_found, ok
from middleware.input_validation import check_len
from werkzeug.security import generate_password_hash

teacher_bp = Blueprint("teacher_bp", __name__, url_prefix="/api/teacher")


def _student_ids(con):
    rows = con.execute("SELECT id FROM users WHERE role='student' AND is_active=1").fetchall()
    return [r["id"] for r in rows]


def _student_mastery_counts(con, user_id):
    chapters = con.execute("SELECT * FROM chapters ORDER BY folder, order_no").fetchall()
    counts = {"master": 0, "progress": 0, "weak": 0, "na": 0}
    detail = []
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        state = mastery.mastery_state(m["m"], m["attempts"])
        counts[state] += 1
        detail.append({
            "chapter_id": ch["id"], "name": ch["name"],
            "m": m["m"], "state": state, "state_label": mastery.state_label(state),
        })
    return counts, detail


@teacher_bp.route("/overview", methods=["GET"])
@jwt_required
@role_required("teacher")
def overview():
    """全班概览（ADMIN-003 / PROG-004）。"""
    con = get_db()
    students = []
    chapter_weak_counter = Counter()
    for sid in _student_ids(con):
        u = con.execute("SELECT * FROM users WHERE id=?", (sid,)).fetchone()
        counts, detail = _student_mastery_counts(con, sid)
        weak_ch = [d["name"] for d in detail if d["state"] == "weak"]
        for w in weak_ch:
            chapter_weak_counter[w] += 1
        students.append({
            "id": sid,
            "display_name": u["display_name"],
            "grade": u["grade"],
            "counts": counts,
            "weak_chapters": weak_ch,
        })
    common_weak = [name for name, n in chapter_weak_counter.items() if n >= 2]
    return ok({
        "student_count": len(students),
        "students": students,
        "common_weak_chapters": common_weak,
    })


@teacher_bp.route("/students", methods=["GET"])
@jwt_required
@role_required("teacher")
def list_students():
    con = get_db()
    rows = con.execute(
        "SELECT id, username, display_name, grade, is_active, created_at"
        " FROM users WHERE role='student' ORDER BY created_at"
    ).fetchall()
    return ok({"students": [dict(r) for r in rows]})


@teacher_bp.route("/students/<student_id>/progress", methods=["GET"])
@jwt_required
@role_required("teacher")
def student_progress(student_id):
    con = get_db()
    u = con.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if u is None:
        return e_not_found("学生不存在")
    counts, detail = _student_mastery_counts(con, student_id)
    return ok({"student": {"id": student_id, "display_name": u["display_name"]},
               "counts": counts, "chapters": detail})


@teacher_bp.route("/students/<student_id>/quizzes", methods=["GET"])
@jwt_required
@role_required("teacher")
def student_quizzes(student_id):
    con = get_db()
    u = con.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if u is None:
        return e_not_found("学生不存在")
    subs = con.execute(
        "SELECT a.quiz_id, a.quiz_version, a.created_at,"
        " SUM(COALESCE(CASE WHEN a.is_reviewed=1 THEN a.reviewed_score ELSE a.score END, 0)) AS earned,"
        " SUM(q.points) AS possible"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=?"
        " GROUP BY a.quiz_id, a.quiz_version, a.created_at ORDER BY a.created_at DESC",
        (student_id,),
    ).fetchall()
    out = []
    for r in subs:
        quiz = con.execute("SELECT title FROM quizzes WHERE id=?", (r["quiz_id"],)).fetchone()
        det_rows = con.execute(
            "SELECT a.id, a.answer, a.score, a.correct, a.is_reviewed, a.reviewed_score,"
            " a.graded_by, q.content, q.type, q.points, q.answer_key"
            " FROM attempts a JOIN questions q ON q.id=a.question_id"
            " WHERE a.user_id=? AND a.quiz_id=? AND a.quiz_version=? AND a.created_at=?"
            " ORDER BY q.rowid",
            (student_id, r["quiz_id"], r["quiz_version"], r["created_at"]),
        ).fetchall()
        out.append({
            "quiz_id": r["quiz_id"],
            "title": quiz["title"] if quiz else r["quiz_id"],
            "version": r["quiz_version"],
            "score": round(r["earned"] / r["possible"] * 100, 1) if r["possible"] else 0.0,
            "at": r["created_at"],
            "details": [{
                "id": d["id"],
                "content": d["content"],
                "type": d["type"],
                "points": d["points"],
                "answer": d["answer"],
                "answer_key": d["answer_key"],
                "score": d["score"],
                "correct": d["correct"],
                "graded_by": d["graded_by"],
                "is_reviewed": d["is_reviewed"],
                "reviewed_score": d["reviewed_score"],
            } for d in det_rows],
        })
    return ok({"student": {"id": student_id, "display_name": u["display_name"]}, "attempts": out})


@teacher_bp.route("/students/<student_id>/reset-password", methods=["POST"])
@jwt_required
@role_required("teacher")
def reset_password(student_id):
    data = request.get_json(silent=True) or {}
    pw = (data.get("new_password") or "").strip()
    if len(pw) < 6:
        return e_input("新密码至少 6 位")
    err = check_len("password", pw)
    if err:
        return err
    con = get_db()
    u = con.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if u is None:
        return e_not_found("学生不存在")
    con.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(pw), student_id))
    con.commit()
    return ok({"updated": 1})


@teacher_bp.route("/students/<student_id>/status", methods=["POST"])
@jwt_required
@role_required("teacher")
def set_status(student_id):
    """停用/启用（ADMIN-001，is_active 状态机）。"""
    data = request.get_json(silent=True) or {}
    is_active = 1 if data.get("is_active", True) else 0
    con = get_db()
    u = con.execute("SELECT * FROM users WHERE id=? AND role='student'", (student_id,)).fetchone()
    if u is None:
        return e_not_found("学生不存在")
    con.execute("UPDATE users SET is_active=? WHERE id=?", (is_active, student_id))
    con.commit()
    return ok({"is_active": bool(is_active)})
