"""进度 Blueprint（REQ-PROG-001~008）：掌握度四态、薄弱点、巩固/间隔复习。

v1.9.0 起并入：AI 每日学习建议（RPT-003 改每日）+ 本周概况/成绩分析（RPT-001/002 迁移）。
"""
import json
from datetime import datetime, timedelta, timezone

from ai import grader, mastery, quizzer, review_sched
from auth.jwt_utils import jwt_required, role_required
from data import models, timeutil
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, ok
from middleware.rate_limit import rate_limit

progress_bp = Blueprint("progress_bp", __name__, url_prefix="/api/progress")


def _all_chapters(con):
    """学生可见章节（仅已发布）：未发布 session 的章节不进入进度/掌握度/薄弱点。
    修复：W1S2 未发布却出现在学生进度里的 bug（发布状态机：章节 status 随 session 同步）。"""
    return con.execute(
        "SELECT * FROM chapters WHERE status='published' ORDER BY folder, order_no, name"
    ).fetchall()


def _now():
    return datetime.now(timezone.utc).isoformat()


def _monday_iso(now: datetime) -> str:
    """本周起点（UTC 周一零点），沿用原周报口径（RPT-001 迁移）。"""
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


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
    """薄弱点列表（附错题依据，PROG-005）：测评薄弱 + 练习错题都纳入。"""
    con = get_db()
    chapters = _all_chapters(con)
    weak = []
    seen = set()
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) != "weak":
            continue
        seen.add(ch["id"])
        weak.append({
            "chapter_id": ch["id"],
            "name": ch["name"],
            "m": m["m"],
            "evidence": _wrong_evidence(con, g.user_id, ch["id"]),
        })
    # 练习错题独立作为薄弱依据（不改变测评掌握度 M，仅补充分支）
    for ch in chapters:
        if ch["id"] in seen:
            continue
        ev = _practice_wrong(con, g.user_id, ch["id"])
        if ev:
            m = mastery.compute_mastery(con, g.user_id, ch["id"])
            weak.append({
                "chapter_id": ch["id"],
                "name": ch["name"],
                "m": m["m"],
                "evidence": ev,
                "from_practice": True,
            })
    return ok({"weak_points": weak})


def _wrong_evidence(con, user_id, chapter_id, limit=5):
    """该章最新 version 错题 + 自主练习错题依据（拒绝凭空定性）。"""
    out = []
    latest = mastery.latest_version_for_chapter(con, chapter_id)
    if latest > 0:
        rows = con.execute(
            "SELECT a.answer, a.score, q.content AS q_content, q.answer_key AS q_answer_key"
            " FROM attempts a JOIN questions q ON q.id=a.question_id"
            " WHERE a.user_id=? AND a.chapter_id=? AND a.quiz_version=? AND a.correct=0"
            " ORDER BY a.created_at DESC LIMIT ?",
            (user_id, chapter_id, latest, limit),
        ).fetchall()
        out.extend([{
            "question": r["q_content"],
            "your_answer": r["answer"],
            "answer_key": r["q_answer_key"],
            "source": "quiz",
        } for r in rows])
    out.extend(_practice_wrong(con, user_id, chapter_id, limit))
    return out[:limit]


def _practice_wrong(con, user_id, chapter_id, limit=5):
    """该章自主练习错题（correct=0 或部分得分），作为薄弱依据之一。"""
    rows = con.execute(
        "SELECT pq.user_answer, pq.score, pq.content, pq.answer_key, pq.sub_concept"
        " FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=? AND pq.chapter_id=? AND pq.answered_at IS NOT NULL"
        " AND (pq.correct=0 OR pq.score < pq.points)"
        " ORDER BY pq.answered_at DESC LIMIT ?",
        (user_id, chapter_id, limit),
    ).fetchall()
    return [{
        "question": r["content"],
        "your_answer": r["user_answer"],
        "answer_key": r["answer_key"],
        "sub_concept": r["sub_concept"],
        "source": "practice",
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
    """一键生成巩固练习：薄弱章 + 练习错题章 → review_items(interval=1)（PROG-006）。"""
    con = get_db()
    chapters = _all_chapters(con)
    weak_ids = []
    focus = {}  # chapter_id -> 练习错题子概念（供巩固出题聚焦）
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_ids.append(ch["id"])
        ev = _practice_wrong(con, g.user_id, ch["id"])
        if ev:
            if ch["id"] not in weak_ids:
                weak_ids.append(ch["id"])
            subs = [e["sub_concept"] for e in ev if e.get("sub_concept")]
            if subs:
                focus[ch["id"]] = ",".join(subs)
    if not weak_ids:
        return ok({"created": 0, "review_items": []})

    created = []
    for cid in weak_ids:
        # 有练习错题子概念时，聚焦该知识点出题，巩固更精准
        qs = quizzer.generate_questions([cid], sub_concepts=focus.get(cid, ""))
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
    qtype = payload.get("type", "essay")
    result = grader.grade_question({
        "type": qtype,
        "content": payload.get("content", ""),
        "options": json.dumps(payload.get("options", [])),
        "answer_key": payload.get("answer_key", ""),
        "points": grader.points_for(qtype),
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
        "SELECT a.quiz_id, a.quiz_version, a.created_at,"
        " SUM(COALESCE(CASE WHEN a.is_reviewed=1 THEN a.reviewed_score ELSE a.score END, 0)) AS earned,"
        " SUM(q.points) AS possible"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=?"
        " GROUP BY a.quiz_id, a.quiz_version, a.created_at ORDER BY a.created_at ASC",
        (g.user_id,),
    ).fetchall()
    out = []
    for r in rows:
        quiz = con.execute("SELECT title FROM quizzes WHERE id=?", (r["quiz_id"],)).fetchone()
        score = round(r["earned"] / r["possible"] * 100, 1) if r["possible"] else 0.0
        out.append({
            "label": (quiz["title"] if quiz else r["quiz_id"])[:16],
            "score": score,
            "at": r["created_at"],
        })
    return ok({"trend": out})


@progress_bp.route("/advice", methods=["GET"])
@jwt_required
@role_required("student")
def advice():
    """AI 学习建议（RPT-003 改每日）：优先取今天（UTC+8），否则最近一条。"""
    con = get_db()
    today = timeutil.today_str()
    row = con.execute(
        "SELECT * FROM daily_advice WHERE user_id=? AND advice_date=?",
        (g.user_id, today),
    ).fetchone()
    if row is None:
        row = con.execute(
            "SELECT * FROM daily_advice WHERE user_id=? ORDER BY advice_date DESC LIMIT 1",
            (g.user_id,),
        ).fetchone()
    if row is None:
        return ok({"has_advice": False})
    return ok({
        "has_advice": True,
        "advice_date": row["advice_date"],
        "stats": json.loads(row["stats"] or "{}"),
        "advice": row["advice"],
        "created_at": row["created_at"],
    })


def _weekly_stats(con, user_id):
    """本周概况 + 成绩分析（RPT-001/002 迁移到进度页，口径沿用原周报）。"""
    start = datetime.fromisoformat(_monday_iso(datetime.now(timezone.utc)))
    end = start + timedelta(days=7)

    msg_rows = con.execute(
        "SELECT created_at FROM messages WHERE conversation_id IN"
        " (SELECT id FROM conversations WHERE user_id=?)", (user_id,)
    ).fetchall()
    att_subs = con.execute(
        "SELECT a.created_at,"
        " SUM(COALESCE(CASE WHEN a.is_reviewed=1 THEN a.reviewed_score ELSE a.score END, 0)) AS earned,"
        " SUM(q.points) AS possible"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=?"
        " GROUP BY a.quiz_id, a.quiz_version, a.created_at",
        (user_id,),
    ).fetchall()

    days, conv_days, quiz_days, scores = set(), set(), set(), []
    for r in msg_rows:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        if start <= t < end:
            days.add(t.date().isoformat())
            conv_days.add(t.date().isoformat())
    for r in att_subs:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        if start <= t < end:
            days.add(t.date().isoformat())
            quiz_days.add(t.date().isoformat())
            if r["possible"]:
                scores.append(r["earned"] / r["possible"] * 100)

    chapters = con.execute("SELECT * FROM chapters ORDER BY folder, order_no").fetchall()
    weak_names = []
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_names.append(ch["name"])

    return {
        "stats": {
            "days": len(days),
            "conversation_days": len(conv_days),
            "quiz_days": len(quiz_days),
            "conversations": len(conv_days),
            "quizzes": len(quiz_days),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else None,
            "max_score": round(max(scores), 1) if scores else None,
        },
        "weak_chapters": weak_names,
    }


@progress_bp.route("/weekly-stats", methods=["GET"])
@jwt_required
@role_required("student")
def weekly_stats():
    """本周概况 + 成绩分析（RPT-001/002，供进度页展示）。"""
    con = get_db()
    return ok(_weekly_stats(con, g.user_id))
