"""进度 Blueprint（REQ-PROG-001~008）：掌握度四态、薄弱点、巩固/间隔复习。"""
import json
from datetime import datetime, timezone

from ai import grader, mastery, quizzer, review_sched
from auth.jwt_utils import jwt_required, role_required
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, ok
from middleware.rate_limit import rate_limit

progress_bp = Blueprint("progress_bp", __name__, url_prefix="/api/progress")


def _all_chapters(con):
    return con.execute("SELECT * FROM chapters ORDER BY folder, order_no, name").fetchall()


def _now():
    return datetime.now(timezone.utc).isoformat()


@progress_bp.route("/mastery", methods=["GET"])
@jwt_required
@role_required("student")
def my_mastery():
    """本人按章四态（PROG-001）。"""
    con = get_db()
    chapters = _all_chapters(con)
    out = []
    counts = {"master": 0, "progress": 0, "weak": 0, "na": 0}
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        state = mastery.mastery_state(m["m"], m["attempts"])
        counts[state] += 1
        out.append({
            "chapter_id": ch["id"],
            "name": ch["name"],
            "folder": ch["folder"],
            "m": m["m"],
            "attempts": m["attempts"],
            "state": state,
            "state_label": mastery.state_label(state),
        })
    return ok({"chapters": out, "counts": counts})


@progress_bp.route("/weak-points", methods=["GET"])
@jwt_required
@role_required("student")
def weak_points():
    """薄弱点列表（附错题依据，PROG-005）。"""
    con = get_db()
    chapters = _all_chapters(con)
    weak = []
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) != "weak":
            continue
        evidence = _wrong_evidence(con, g.user_id, ch["id"])
        weak.append({
            "chapter_id": ch["id"],
            "name": ch["name"],
            "m": m["m"],
            "evidence": evidence,
        })
    return ok({"weak_points": weak})


def _wrong_evidence(con, user_id, chapter_id, limit=5):
    """该章最新 version 下的错题依据（拒绝凭空定性）。"""
    latest = mastery.latest_version_for_chapter(con, chapter_id)
    if latest <= 0:
        return []
    rows = con.execute(
        "SELECT a.answer, a.score, q.content AS q_content, q.answer_key AS q_answer_key"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=? AND a.chapter_id=? AND a.quiz_version=? AND a.correct=0"
        " ORDER BY a.created_at DESC LIMIT ?",
        (user_id, chapter_id, latest, limit),
    ).fetchall()
    return [{
        "question": r["q_content"],
        "your_answer": r["answer"],
        "answer_key": r["q_answer_key"],
    } for r in rows]


def _review_dict(row, due: bool) -> dict:
    return {
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "interval_days": row["interval_days"],
        "next_review_at": row["next_review_at"],
        "status": row["status"],
        "due": due,
    }


@progress_bp.route("/review-items", methods=["GET"])
@jwt_required
@role_required("student")
def list_review_items():
    con = get_db()
    rows = con.execute(
        "SELECT * FROM review_items WHERE user_id=? ORDER BY"
        " (status='pending') DESC, next_review_at ASC", (g.user_id,)
    ).fetchall()
    now = _now()
    items = [_review_dict(r, r["status"] == "pending" and r["next_review_at"] <= now) for r in rows]
    return ok({"review_items": items})


@progress_bp.route("/review-items/generate", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def generate_review():
    """一键生成巩固练习：薄弱章 → review_items(interval=1)（PROG-006）。"""
    con = get_db()
    chapters = _all_chapters(con)
    weak_ids = []
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_ids.append(ch["id"])
    if not weak_ids:
        return ok({"created": 0, "review_items": []})

    created = []
    for cid in weak_ids:
        qs = quizzer.generate_questions([cid])
        raw = qs[0] if qs else quizzer.fallback_questions([cid])[0]
        q = quizzer.norm_question(raw, cid)
        payload = json.dumps({
            "content": q["content"], "type": q["type"],
            "options": q["options"], "answer_key": q["answer_key"],
        }, ensure_ascii=False)
        uid = models.new_id()
        con.execute(
            "INSERT INTO review_items (id, user_id, chapter_id, question_id, payload,"
            " next_review_at, interval_days, status, created_at)"
            " VALUES (?, ?, ?, NULL, ?, ?, 1, 'pending', ?)",
            (uid, g.user_id, cid, payload, review_sched.next_review_at_iso(1), models.utcnow()),
        )
        created.append({"id": uid, "chapter_id": cid, "interval_days": 1})
    con.commit()
    return ok({"created": len(created), "review_items": created})


@progress_bp.route("/review-items/<item_id>", methods=["GET"])
@jwt_required
@role_required("student")
def get_review_item(item_id):
    """取复习题（仅本人，含题目内容）。"""
    con = get_db()
    row = con.execute(
        "SELECT * FROM review_items WHERE id=? AND user_id=?", (item_id, g.user_id)
    ).fetchone()
    if row is None:
        return e_forbidden("只能访问本人复习计划")
    payload = json.loads(row["payload"] or "{}")
    return ok({
        "id": row["id"],
        "chapter_id": row["chapter_id"],
        "interval_days": row["interval_days"],
        "status": row["status"],
        "question": payload,
    })


@progress_bp.route("/review-items/<item_id>/complete", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def complete_review(item_id):
    """作答并批改：答对 interval*3，答错重置 1；排入下一次复习（PROG-006）。"""
    data = request.get_json(silent=True) or {}
    answer = str(data.get("answer") or "")
    if not answer:
        return e_input("缺少作答")

    con = get_db()
    row = con.execute(
        "SELECT * FROM review_items WHERE id=? AND user_id=?", (item_id, g.user_id)
    ).fetchone()
    if row is None:
        return e_forbidden("只能访问本人复习计划")
    payload = json.loads(row["payload"] or "{}")
    result = grader.grade_question({
        "type": payload.get("type", "essay"),
        "content": payload.get("content", ""),
        "options": json.dumps(payload.get("options", [])),
        "answer_key": payload.get("answer_key", ""),
    }, answer)

    correct = bool(result["correct"])
    new_interval = review_sched.next_interval(correct, row["interval_days"])
    now = models.utcnow()
    # 当前项完成；生成下一次复习（同一题，间隔顺延/重置）
    con.execute("UPDATE review_items SET status='done' WHERE id=?", (item_id,))
    con.execute(
        "INSERT INTO review_items (id, user_id, chapter_id, question_id, payload,"
        " next_review_at, interval_days, status, created_at)"
        " VALUES (?, ?, ?, NULL, ?, ?, ?, 'pending', ?)",
        (models.new_id(), g.user_id, row["chapter_id"], row["payload"],
         review_sched.next_review_at_iso(new_interval), new_interval, now),
    )
    con.commit()
    return ok({
        "correct": result["correct"],
        "score": result["score"],
        "reason": result["reason"],
        "next_interval_days": new_interval,
    })


@progress_bp.route("/trend", methods=["GET"])
@jwt_required
@role_required("student")
def trend():
    """成绩趋势折线（PROG-003）：按提交时间聚合每次测评得分。"""
    con = get_db()
    rows = con.execute(
        "SELECT quiz_id, quiz_version, created_at, AVG(score) AS s"
        " FROM attempts WHERE user_id=?"
        " GROUP BY quiz_id, quiz_version, created_at ORDER BY created_at ASC",
        (g.user_id,),
    ).fetchall()
    out = []
    for r in rows:
        quiz = con.execute("SELECT title FROM quizzes WHERE id=?", (r["quiz_id"],)).fetchone()
        out.append({
            "label": (quiz["title"] if quiz else r["quiz_id"])[:16],
            "score": round(r["s"] * 100, 1),
            "at": r["created_at"],
        })
    return ok({"trend": out})
