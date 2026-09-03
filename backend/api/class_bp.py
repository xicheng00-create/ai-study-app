"""班级 Blueprint（REQ-CLASS-001~006）：全班排行榜 6 类 + 共性薄弱（教师）。

归属：所有 active 学生（除 username='Hermestest' 测试账号）同属一个班级，仅展示
实名（display_name）。排行榜本就是全班展示，student 只限定同班集合（即除测试号
外的 active 学生），teacher 无需 @user_scope、可看完整排名 + 管理入口（前端跳转）。
"""
from collections import Counter

from ai import mastery
from auth.jwt_utils import jwt_required
from data import timeutil
from data.db import get_db
from flask import Blueprint, g
from middleware.errors import ok

class_bp = Blueprint("class_bp", __name__, url_prefix="/api/class")

# 测试账号绝不出现在班级排行榜
EXCLUDED_USERNAMES = ("Hermestest",)


def _class_students(con):
    """同班学生集合（active 学生，排除测试账号），按实名排序。"""
    rows = con.execute(
        "SELECT id, username, display_name FROM users"
        " WHERE role='student' AND is_active=1"
        " ORDER BY display_name, created_at"
    ).fetchall()
    return [dict(r) for r in rows if r["username"] not in EXCLUDED_USERNAMES]


def _student_map(con):
    return {s["id"]: s for s in _class_students(con)}


def _entry(uid, students, value):
    return {"user_id": uid, "display_name": students[uid]["display_name"], "value": value}


def _sorted_entries(counts: dict, students: dict, reverse=True):
    """按 value 排序；同值按实名稳定排序；缺省（无记录）补 0。"""
    rows = [
        {"user_id": uid, "display_name": students[uid]["display_name"], "value": int(counts.get(uid, 0))}
        for uid in students
    ]
    rows.sort(key=lambda r: (-r["value"], r["display_name"]) if reverse else (r["value"], r["display_name"]))
    return rows


def _quiz_score(con, user_id, quiz):
    """学生在某次测评的最新提交得分率；未参加返回 None。"""
    t = con.execute(
        "SELECT MAX(created_at) AS t FROM attempts"
        " WHERE user_id=? AND quiz_id=? AND quiz_version=?",
        (user_id, quiz["id"], quiz["version"]),
    ).fetchone()
    if not t["t"]:
        return None
    agg = con.execute(
        "SELECT SUM(COALESCE(CASE WHEN a.is_reviewed=1 THEN a.reviewed_score"
        " ELSE a.score END, 0)) AS earned, SUM(q.points) AS possible"
        " FROM attempts a JOIN questions q ON q.id=a.question_id"
        " WHERE a.user_id=? AND a.quiz_id=? AND a.quiz_version=? AND a.created_at=?",
        (user_id, quiz["id"], quiz["version"], t["t"]),
    ).fetchone()
    if not agg["possible"]:
        return None
    return round(agg["earned"] / agg["possible"] * 100, 1)


def _mastery_average(con, user_id):
    """平均 M = 已评估章节 compute_mastery().m 的均值（未评估不计入、不当 0，定义 B）。"""
    chapters = con.execute("SELECT * FROM chapters WHERE status='published'").fetchall()
    ms = []
    mastered = 0
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        if m["m"] is not None:
            ms.append(m["m"])
            if mastery.mastery_state(m["m"], m["attempts"]) == "master":
                mastered += 1
    avg = round(sum(ms) / len(ms), 1) if ms else None
    return avg, mastered


def _weak_names(con, user_id):
    chapters = con.execute("SELECT * FROM chapters WHERE status='published'").fetchall()
    names = []
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            names.append(ch["name"])
    return names


@class_bp.route("/leaderboard", methods=["GET"])
@jwt_required
def leaderboard():
    """全班排行榜 6 类（REQ-CLASS-001~006），student / teacher 均可访问。"""
    con = get_db()
    students = _student_map(con)
    is_teacher = g.role == "teacher"

    # 1) 累计对话轮次：累计 user 消息数
    turn_rows = con.execute(
        "SELECT c.user_id, COUNT(m.id) AS cnt"
        " FROM conversations c JOIN messages m ON m.conversation_id=c.id AND m.role='user'"
        " GROUP BY c.user_id"
    ).fetchall()
    total_turns = {r["user_id"]: r["cnt"] for r in turn_rows}

    # 2) 累计练习次数：practice_sessions 数
    practice_rows = con.execute(
        "SELECT user_id, COUNT(*) AS cnt FROM practice_sessions GROUP BY user_id"
    ).fetchall()
    total_practice = {r["user_id"]: r["cnt"] for r in practice_rows}

    # 3/4) 今日（UTC+8）对话轮次 / 对话会话数
    today = timeutil.today_str()
    today_turns = Counter()
    today_convs = Counter()
    for r in con.execute(
        "SELECT c.user_id, m.created_at FROM conversations c"
        " JOIN messages m ON m.conversation_id=c.id AND m.role='user'"
    ).fetchall():
        if timeutil.shanghai_date(r["created_at"]) == today:
            today_turns[r["user_id"]] += 1
    for r in con.execute("SELECT user_id, created_at FROM conversations").fetchall():
        if timeutil.shanghai_date(r["created_at"]) == today:
            today_convs[r["user_id"]] += 1

    # 5) 每次测评分数榜：列出全体学生分数与排名，未参加标注「未参加」
    quizzes = con.execute(
        "SELECT * FROM quizzes WHERE status='published' ORDER BY published_at DESC"
    ).fetchall()
    quiz_boards = {}
    quiz_list = []
    for quiz in quizzes:
        quiz_list.append({
            "quiz_id": quiz["id"],
            "title": quiz["title"],
            "version": quiz["version"],
            "published_at": quiz["published_at"],
        })
        entries = []
        for uid in students:
            score = _quiz_score(con, uid, quiz)
            entries.append({
                "user_id": uid,
                "display_name": students[uid]["display_name"],
                "score": score,
                "absent": score is None,
            })
        # 参加者按分数降序排名；未参加排后（rank=None）
        ranked = sorted(entries, key=lambda e: (e["absent"], -(e["score"] or 0), e["display_name"]))
        rank = 0
        for e in ranked:
            if not e["absent"]:
                rank += 1
                e["rank"] = rank
            else:
                e["rank"] = None
        quiz_boards[quiz["id"]] = ranked

    # 6) 掌握度排行：平均 M 排序（可附「已掌握 X 章」）
    mastery_rows = []
    for uid in students:
        avg_m, mastered = _mastery_average(con, uid)
        mastery_rows.append({
            "user_id": uid,
            "display_name": students[uid]["display_name"],
            "avg_m": avg_m,
            "mastered_count": mastered,
        })
    mastery_rows.sort(key=lambda r: (r["avg_m"] is None, -(r["avg_m"] or 0), r["display_name"]))

    # 教师视角：共性薄弱章节（≥2 人）
    common_weak = []
    if is_teacher:
        counter = Counter()
        for uid in students:
            for name in set(_weak_names(con, uid)):
                counter[name] += 1
        common_weak = [name for name, n in counter.items() if n >= 2]

    return ok({
        "is_teacher": is_teacher,
        "me_user_id": g.user_id,
        "students": [{"user_id": s["id"], "display_name": s["display_name"]} for s in _class_students(con)],
        "total_turns": _sorted_entries(total_turns, students),
        "total_practice": _sorted_entries(total_practice, students),
        "today_turns": _sorted_entries(dict(today_turns), students),
        "today_conversations": _sorted_entries(dict(today_convs), students),
        "mastery": mastery_rows,
        "quizzes": quiz_list,
        "quiz_boards": quiz_boards,
        "common_weak_chapters": common_weak,
    })
