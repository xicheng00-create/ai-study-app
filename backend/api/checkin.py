"""每日打卡与连胜 Blueprint（CHECKIN-001~008，学生端）。"""
from ai import mastery
from auth.jwt_utils import jwt_required, role_required
from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED
from data import checkin, timeutil
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_forbidden, e_input, ok
from middleware.rate_limit import rate_limit

checkin_bp = Blueprint("checkin_bp", __name__, url_prefix="/api/checkin")


def _practice_chapters(con, user_id) -> list[str]:
    """今日练习章节：薄弱章节 ∪ 有到期卡的章节 ∪ 已发布章节（去重保序）。"""
    published = con.execute(
        "SELECT id FROM chapters WHERE status='published' ORDER BY folder, order_no, name"
    ).fetchall()
    pub_ids = [r["id"] for r in published]

    weak = []
    for r in published:
        m = mastery.compute_mastery(con, user_id, r["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak.append(r["id"])

    today = timeutil.today_str()
    due = []
    for r in con.execute(
        "SELECT DISTINCT kc.chapter_id AS cid, kr.next_review_at AS due_at"
        " FROM knowledge_cards kc JOIN knowledge_reviews kr ON kr.card_id=kc.id"
        " WHERE kr.user_id=? AND kr.status != 'mastered'",
        (user_id,),
    ).fetchall():
        if r["due_at"] and timeutil.shanghai_date(r["due_at"]) <= today:
            due.append(r["cid"])

    seen, out = set(), []
    for cid in weak + due + pub_ids:
        if cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


@checkin_bp.route("/today", methods=["GET"])
@jwt_required
@role_required("student")
def today():
    """今日任务与连胜状态（每次惰性幂等评估，跨日自愈）。"""
    con = get_db()
    info = checkin.evaluate_and_maybe_complete(con, g.user_id)
    c = checkin.progress_today(con, g.user_id)
    deck = checkin.build_today_deck(con, g.user_id)
    return ok({
        "task": {
            "cards": deck["cards"], "questions": TASK_QUESTIONS_REQUIRED, "short": deck["short"],
            # 阈值随数据下发（单一真相在 config.TASK_*_REQUIRED）：前端不再硬编码 10/5
            "cards_required": TASK_CARDS_REQUIRED, "questions_required": TASK_QUESTIONS_REQUIRED,
        },
        "progress": {"cards": c["cards"], "questions": c["questions"]},
        "done": info["done"],
        "streak": info["streak"],
        "longest": info["longest"],
        "alive": info["alive"],
        "state": info["state"],
        "today": info["today"],
    })


@checkin_bp.route("/class", methods=["GET"])
@jwt_required
@role_required("student")
def class_today():
    """班级「今日打卡」投影（CHECKIN-008）。"""
    con = get_db()
    checkin.evaluate_and_maybe_complete(con, g.user_id)
    return ok(checkin.class_today(con, g.user_id))


@checkin_bp.route("/nudge", methods=["POST"])
@jwt_required
@role_required("student")
def nudge():
    """同学互提醒（NOTIF-006）：同日同对限流 1 次，不能提醒自己。"""
    data = request.get_json(silent=True) or {}
    to_user_id = (data.get("to_user_id") or "").strip()
    if not to_user_id:
        return e_input("缺少 to_user_id")
    if to_user_id == g.user_id:
        return e_input("不能提醒自己")

    con = get_db()
    stu = con.execute(
        "SELECT id, display_name, username FROM users WHERE id=? AND role='student' AND is_active=1",
        (to_user_id,),
    ).fetchone()
    if stu is None:
        return e_forbidden("只能提醒同班同学")

    today = timeutil.today_str()
    dup = con.execute(
        "SELECT created_at FROM notifications WHERE user_id=? AND type='peer_nudge' AND ref_id=?",
        (to_user_id, g.user_id),
    ).fetchall()
    if any(timeutil.shanghai_date(r["created_at"]) == today for r in dup):
        return e_input("今天已经提醒过 TA 了")

    me = con.execute("SELECT display_name, username FROM users WHERE id=?", (g.user_id,)).fetchone()
    sender = (me["display_name"] or me["username"]) if me else ""
    info = checkin.streak_info(con, to_user_id)
    body = (f"别断了 🔥{info['streak']} 天连胜，快来打卡！"
            if info["streak"] > 0 else "快来打卡，别掉队！")

    from services.notify import notify_users

    notify_users(con, [to_user_id], "peer_nudge", f"{sender} 戳了你一下", body,
                 image="", ref_kind="nudge", ref_id=g.user_id)
    return ok({"ok": True})


@checkin_bp.route("/start-practice", methods=["POST"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def start_practice():
    """今日练习自动装配（CHECKIN-006）：当天有未答完 session 优先续答，否则生成 5 道。"""
    con = get_db()

    row = con.execute(
        "SELECT ps.id, COUNT(pq.id) AS remain"
        " FROM practice_sessions ps JOIN practice_questions pq ON pq.session_id=ps.id"
        " WHERE ps.user_id=? AND pq.answered_at IS NULL"
        " GROUP BY ps.id ORDER BY ps.created_at DESC LIMIT 1",
        (g.user_id,),
    ).fetchone()
    if row:
        return ok({"session_id": row["id"], "reused": True, "count": row["remain"]})

    chapter_ids = _practice_chapters(con, g.user_id)
    if not chapter_ids:
        return e_input("暂无可用章节")

    from api.practice import create_practice_session

    result = create_practice_session(con, g.user_id, chapter_ids, count=TASK_QUESTIONS_REQUIRED)
    if not result:
        return e_input("练习生成失败，请稍后重试")
    return ok({"session_id": result["id"], "reused": False, "count": len(result["questions"])})
