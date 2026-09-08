"""AI 学习建议生成公共逻辑（REQ-RPT-003 改每日）。

daily_advice_gen 定时脚本与进度页「生成今日建议」共用，避免统计口径漂移。
"""
from datetime import timedelta


def today_stats(con, user_id: str):
    """当日（UTC+8）活动统计 + 薄弱章名，返回 (stats dict, weak_names list)。"""
    from data import timeutil

    today = timeutil.today_str()
    convs = con.execute(
        "SELECT created_at FROM conversations WHERE user_id=?", (user_id,)
    ).fetchall()
    today_convs = sum(timeutil.shanghai_date(r["created_at"]) == today for r in convs)
    msgs = con.execute(
        "SELECT m.created_at FROM messages m JOIN conversations c ON c.id=m.conversation_id"
        " WHERE c.user_id=? AND m.role='user'", (user_id,)
    ).fetchall()
    today_turns = sum(timeutil.shanghai_date(r["created_at"]) == today for r in msgs)
    practices = con.execute(
        "SELECT created_at FROM practice_sessions WHERE user_id=?", (user_id,)
    ).fetchall()
    today_practice = sum(timeutil.shanghai_date(r["created_at"]) == today for r in practices)
    quiz_subs = con.execute(
        "SELECT DISTINCT quiz_id, quiz_version, created_at FROM attempts WHERE user_id=?", (user_id,)
    ).fetchall()
    today_quizzes = sum(timeutil.shanghai_date(r["created_at"]) == today for r in quiz_subs)

    from ai import mastery
    chapters = con.execute("SELECT * FROM chapters WHERE status='published'").fetchall()
    weak_names = []
    for ch in chapters:
        m = mastery.compute_mastery(con, user_id, ch["id"])
        if mastery.mastery_state(m["m"], m["attempts"]) == "weak":
            weak_names.append(ch["name"])
    return {
        "conversations": today_convs,
        "turns": today_turns,
        "practice": today_practice,
        "quizzes": today_quizzes,
    }, weak_names


def recent_learning_context(con, user_id: str) -> dict:
    """汇总近 7 天真实活动、掌握度与错题知识点，供建议按人展开。"""
    from data import timeutil

    from ai import mastery

    since = (timeutil.shanghai_now().date() - timedelta(days=6)).isoformat()
    chapters = con.execute(
        "SELECT id, name FROM chapters WHERE status='published'"
    ).fetchall()
    names = {r["id"]: r["name"] for r in chapters}
    counts = {}

    def add_activity(chapter_id, created_at):
        if chapter_id in names and timeutil.shanghai_date(created_at) >= since:
            counts[chapter_id] = counts.get(chapter_id, 0) + 1

    rows = con.execute(
        "SELECT c.chapter_id, m.created_at FROM messages m JOIN conversations c"
        " ON c.id=m.conversation_id WHERE c.user_id=? AND m.role='user'", (user_id,)
    ).fetchall()
    for row in rows:
        add_activity(row["chapter_id"], row["created_at"])
    rows = con.execute(
        "SELECT pq.chapter_id, COALESCE(pq.answered_at, ps.created_at) AS created_at"
        " FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=?", (user_id,)
    ).fetchall()
    for row in rows:
        add_activity(row["chapter_id"], row["created_at"])
    rows = con.execute(
        "SELECT chapter_id, created_at FROM attempts WHERE user_id=?", (user_id,)
    ).fetchall()
    for row in rows:
        add_activity(row["chapter_id"], row["created_at"])

    focus = []
    for chapter_id, count in sorted(counts.items(), key=lambda item: (-item[1], names[item[0]])):
        result = mastery.compute_mastery(con, user_id, chapter_id)
        state = mastery.mastery_state(result["m"], result["attempts"])
        focus.append({
            "name": names[chapter_id], "activities": count,
            "mastery": mastery.state_label(state),
        })

    wrong = []
    rows = con.execute(
        "SELECT q.sub_concept, q.content, a.created_at FROM attempts a"
        " JOIN questions q ON q.id=a.question_id WHERE a.user_id=? AND a.correct=0",
        (user_id,),
    ).fetchall()
    rows += con.execute(
        "SELECT pq.sub_concept, pq.content, pq.answered_at AS created_at"
        " FROM practice_questions pq JOIN practice_sessions ps ON ps.id=pq.session_id"
        " WHERE ps.user_id=? AND pq.answered_at IS NOT NULL"
        " AND (pq.correct=0 OR pq.score<pq.points)", (user_id,),
    ).fetchall()
    for row in rows:
        if timeutil.shanghai_date(row["created_at"]) >= since:
            concept = (row["sub_concept"] or row["content"] or "").strip()
            if concept and concept not in wrong:
                wrong.append(concept[:60])

    quizzes = con.execute(
        "SELECT chapter_id, created_at FROM attempts WHERE user_id=? ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    recent_quizzes = [r for r in quizzes if timeutil.shanghai_date(r["created_at"]) >= since]
    latest_quiz = recent_quizzes[0] if recent_quizzes else None
    return {
        "chapters": focus,
        "weak_concepts": wrong[:5],
        "has_recent_quiz": latest_quiz is not None,
        "latest_quiz_date": timeutil.shanghai_date(latest_quiz["created_at"]) if latest_quiz else "",
        "latest_quiz_chapter": names.get(latest_quiz["chapter_id"], "") if latest_quiz else "",
    }


def _fallback_advice(stats: dict, context: dict) -> str:
    """无 LLM 时仍根据近期学习事实生成三条建议。"""
    chapters = context["chapters"]
    focus = chapters[0] if chapters else None
    focus_text = (f"{focus['name']}（近 7 天活动 {focus['activities']} 次，掌握度{focus['mastery']}）"
                  if focus else "最近尚无章节活动")
    weak = "、".join(context["weak_concepts"][:2]) or "本周错题"
    quiz = (f"最近一次测评在 {context['latest_quiz_date']}，覆盖{context['latest_quiz_chapter']}；"
            if context["has_recent_quiz"] else "最近 7 天尚未测评；")
    return (
        f"• 围绕近期重点 {focus_text} 继续学习，把今天的对话和练习聚焦在同一章节。\n"
        f"• 针对错题知识点「{weak}」完成一组巩固练习，并在答后复盘错误原因。\n"
        f"• {quiz}结合当前掌握度安排下一步：薄弱先补基础，进行中继续用练习检验。"
    )


def build_advice_text(con, user_id: str, stats: dict, weak_names: list) -> str:
    """AI 建议：结合今天与近 7 天上下文；不可用时按事实模板兜底。"""
    from ai import agents

    context = recent_learning_context(con, user_id)
    chapters = "；".join(
        f"{item['name']}（活动{item['activities']}次，掌握度{item['mastery']}）"
        for item in context["chapters"]
    ) or "无"
    weak = "、".join(context["weak_concepts"]) or "无"
    quiz = (f"近 7 天做过测评：{context['latest_quiz_date']}，章节：{context['latest_quiz_chapter']}"
            if context["has_recent_quiz"] else "近 7 天未做测评")
    sys_prompt = (
        "你是「AI 学习小组」的学习教练。结合今天数据、最近 7 天重点、各章掌握度和薄弱知识点，"
        "给出 3 条因人而异且针对具体内容的学习建议，每条一句、必须用「• 」开头。"
        "若最近 7 天做过测评，必须引用该事实，不可写『测评还没做』；仅在确实未做时才提示测评。"
        f"今天：对话 {stats.get('conversations', 0)} 次，练习 {stats.get('practice', 0)} 次，"
        f"测评 {stats.get('quizzes', 0)} 次，薄弱章节：{'、'.join(weak_names) or '无'}。"
        f"近期章节：{chapters}。薄弱知识点：{weak}。测评：{quiz}。"
    )
    out = agents.tutor_reply(sys_prompt, [])
    return out if out else _fallback_advice(stats, context)
