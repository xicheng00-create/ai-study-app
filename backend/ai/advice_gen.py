"""AI 学习建议生成公共逻辑（REQ-RPT-003 改每日）。

daily_advice_gen 定时脚本（每天 22:00）与进度页「生成今日建议」共用，
避免统计口径在脚本与 API 两侧重复漂移。
"""


def today_stats(con, user_id: str):
    """当日（UTC+8）活动统计 + 薄弱章名，返回 (stats dict, weak_names list)。

    口径与 scripts/daily_advice_gen.py 原内联逻辑一致。
    """
    from data import timeutil

    today = timeutil.today_str()
    convs = con.execute(
        "SELECT created_at FROM conversations WHERE user_id=?", (user_id,)
    ).fetchall()
    today_convs = sum(1 for r in convs if timeutil.shanghai_date(r["created_at"]) == today)
    msgs = con.execute(
        "SELECT m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id"
        " WHERE c.user_id=? AND m.role='user'", (user_id,)
    ).fetchall()
    today_turns = sum(1 for r in msgs if timeutil.shanghai_date(r["created_at"]) == today)
    practices = con.execute(
        "SELECT created_at FROM practice_sessions WHERE user_id=?", (user_id,)
    ).fetchall()
    today_practice = sum(1 for r in practices if timeutil.shanghai_date(r["created_at"]) == today)
    quiz_subs = con.execute(
        "SELECT DISTINCT quiz_id, quiz_version, created_at FROM attempts WHERE user_id=?", (user_id,)
    ).fetchall()
    today_quizzes = sum(1 for r in quiz_subs if timeutil.shanghai_date(r["created_at"]) == today)

    from ai import mastery
    chapters = con.execute("SELECT * FROM chapters WHERE status='published'").fetchall()
    weak_names = []
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_names.append(ch["name"])
    stats = {
        "conversations": today_convs,
        "turns": today_turns,
        "practice": today_practice,
        "quizzes": today_quizzes,
    }
    return stats, weak_names


def build_advice_text(con, stats: dict, weak_names: list) -> str:
    """AI 建议：走 TUTOR；不可用则模板兜底。"""
    from ai import agents

    sys_prompt = (
        "你是「AI 学习小组」的学习教练。请根据学生今天的数据给出 3 条简短学习建议"
        "（每条一句，用「• 」开头）。数据："
        f"对话 {stats.get('conversations', 0)} 次，练习 {stats.get('practice', 0)} 次，"
        f"测评 {stats.get('quizzes', 0)} 次，薄弱章节：{'、'.join(weak_names) if weak_names else '无'}。"
    )
    out = agents.tutor_reply(sys_prompt, [])
    if out:
        return out
    if weak_names:
        return (
            f"• 优先巩固薄弱章节：{'、'.join(weak_names)}，可到「进度」页一键生成巩固练习。\n"
            "• 保持当前对话提问节奏，卡住的概念开新对话继续引导。\n"
            "• 每天完成一点对应章节练习，用错题检验掌握情况。"
        )
    return "• 今天状态良好，可推进新章节学习，并保持间隔复习节奏。"
