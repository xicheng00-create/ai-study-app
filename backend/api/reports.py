"""周报 Blueprint（REQ-RPT-001~003）：本人周统计 + AI 学习建议。"""
from datetime import datetime, timedelta, timezone

from ai import agents, mastery
from auth.jwt_utils import jwt_required, role_required
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import ok
from middleware.rate_limit import rate_limit

reports_bp = Blueprint("reports_bp", __name__, url_prefix="/api/reports")


def _monday_iso(now: datetime) -> str:
    monday = now - timedelta(days=now.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _parse_week_start(raw) -> str:
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass
    return _monday_iso(datetime.now(timezone.utc))


def _advice(con, user_id: str, stats: dict, weak_names: list[str]) -> str:
    """AI 建议：走 TUTOR；不可用则模板兜底。"""
    sys = (
        "你是「AI 学习小组」的学习教练。请根据学生本周数据给出 3 条简短中文下周学习建议"
        "（每条一句，用「• 」开头）。数据："
        f"学习天数 {stats['days']}，对话 {stats['conversations']} 次，测评 {stats['quizzes']} 次，"
        f"平均分 {stats['avg_score']}，薄弱章节：{'、'.join(weak_names) if weak_names else '无'}。"
    )
    out = agents.tutor_reply(sys, [])
    if out:
        return out
    if weak_names:
        return (
            f"• 优先巩固薄弱章节：{'、'.join(weak_names)}，可到「进度」页一键生成巩固练习。"
            "\n• 保持当前对话提问节奏，卡住的概念开新对话继续引导。"
            "\n• 每周至少完成一次对应章节测评，用错题检验掌握情况。"
        )
    return "• 本周状态良好，下周可推进新章节学习，并保持间隔复习节奏。"


@reports_bp.route("/weekly", methods=["GET"])
@jwt_required
@role_required("student")
@rate_limit(limit=60)
def weekly():
    """本周概况 + 成绩分析 + AI 建议（RPT-001~003）。"""
    week_start = _parse_week_start(request.args.get("week_start"))
    start = datetime.fromisoformat(week_start)
    end = start + timedelta(days=7)

    con = get_db()
    days_rows = con.execute(
        "SELECT created_at FROM messages WHERE conversation_id IN"
        " (SELECT id FROM conversations WHERE user_id=?)", (g.user_id,)
    ).fetchall()
    att_rows = con.execute(
        "SELECT created_at, score FROM attempts WHERE user_id=?", (g.user_id,)
    ).fetchall()
    days = set()
    conv_days = set()
    for r in days_rows:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        if start <= t < end:
            days.add(t.date().isoformat())
            conv_days.add(t.date().isoformat())
    quiz_days = set()
    scores = []
    for r in att_rows:
        try:
            t = datetime.fromisoformat(r["created_at"])
        except ValueError:
            continue
        if start <= t < end:
            days.add(t.date().isoformat())
            quiz_days.add(t.date().isoformat())
            scores.append(r["score"])

    # 薄弱点（本周数据源可少，取全量掌握度）
    chapters = con.execute("SELECT * FROM chapters ORDER BY folder, order_no").fetchall()
    weak_names = []
    for ch in chapters:
        m = mastery.compute_mastery(con, g.user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_names.append(ch["name"])

    stats = {
        "days": len(days),
        "conversation_days": len(conv_days),
        "quiz_days": len(quiz_days),
        "conversations": len(conv_days),
        "quizzes": len(quiz_days),
        "avg_score": round(sum(scores) / len(scores) * 100, 1) if scores else None,
        "max_score": round(max(scores) * 100, 1) if scores else None,
    }
    advice = _advice(con, g.user_id, stats, weak_names)
    return ok({
        "week_start": week_start,
        "stats": stats,
        "weak_chapters": weak_names,
        "advice": advice,
    })
