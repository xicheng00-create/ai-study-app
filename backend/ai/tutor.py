"""引导式对话编排（CHAT-004/005，F5 输出门控，两层 Fallback）。"""
from ai import agents, fallback, mastery, rag, video_link
from ai.prompts import TUTOR_SYSTEM

MAX_TURN = 12


def _user_wants_video(content: str) -> bool:
    """学生是否主动问及视频课（含关键词才召回相关视频，避免每轮轰炸）。
    v1.5.1：普通提问不返回 related_videos，改为优先指向资料（用户反馈）。"""
    kw = ("视频", "视频课", "看视频", "讲解视频", "课程", "up主", "up主", "b站", "bilibili",
          "网课", "教程", "直播", "录像", "视频链接", "有没有课", "课在哪", "怎么学视频")
    return any(k in content.lower() for k in kw)


def _format_related_videos(related):
    """视频推荐块：仅标题/平台/URL，不内联视频内容。"""
    if not related:
        return "（无相关视频课）"
    return "\n".join(
        f"- {v['title']}（{v['platform'] or '外链'}）：{v['url']}" for v in related
    )


def weak_chapter_names(con, user_id: str) -> list[str]:
    """学生当前薄弱章名（人设加载，CHAT-001）。"""
    rows = con.execute(
        "SELECT DISTINCT chapter_id FROM attempts WHERE user_id=?", (user_id,)
    ).fetchall()
    names = []
    for r in rows:
        m = mastery.compute_mastery(con, user_id, r["chapter_id"])
        if m["m"] is not None and m["m"] < mastery.THRESHOLD_PROGRESS:
            ch = con.execute("SELECT name FROM chapters WHERE id=?", (r["chapter_id"],)).fetchone()
            if ch:
                names.append(ch["name"])
    return names


def chapter_name(con, chapter_id: str | None) -> str:
    if not chapter_id:
        return "全部资料"
    row = con.execute("SELECT name FROM chapters WHERE id=?", (chapter_id,)).fetchone()
    return row["name"] if row else "全部资料"


def _history(con, conversation_id: str, turn: int) -> list[dict]:
    rows = con.execute(
        "SELECT role, content FROM messages WHERE conversation_id=?"
        " ORDER BY created_at ASC, rowid ASC LIMIT ?",
        (conversation_id, turn * 2 + 4),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def tutor_orchestrate(con, user_row, conversation, content: str, chapter_id: str | None,
                      concept_tags=None, chapter_ids=None) -> dict:
    """返回 {content, cite, turn, fallback, related_videos}。"""
    user_id = user_row["id"]
    turn = _current_turn(con, conversation["id"])
    weak = weak_chapter_names(con, user_id)
    weak_txt = "、".join(weak) if weak else "暂无"
    # v1.5.0：年级维度已移除，TUTOR 不再注入 grade

    # 视频相关推荐（RAG 纯度：纯 SQL + 标签匹配，与 chunks 召回并行互不干扰）
    # v1.5.1：仅当学生主动问及视频课才召回，普通提问不返回（避免每轮轰炸,优先指向资料）
    video_chapter_ids = chapter_ids or ([chapter_id] if chapter_id else [])
    related = video_link.retrieve_related_videos(video_chapter_ids, concept_tags) if _user_wants_video(content) else []
    related_txt = _format_related_videos(related)

    chunks = rag.retrieve(content, chapter_id, top_k=5)
    chunk_txt = "\n".join(f"- {c['text'][:300]}" for c in chunks) if chunks else "（无相关片段）"

    # 门控 a/b：越界或敏感 → 兜底，不调用 LLM
    if fallback.detect_sensitive(content):
        return {"content": fallback.fallback_reply("sensitive"), "cite": "", "turn": turn,
                "fallback": True, "related_videos": related}
    if fallback.detect_offtopic(content):
        return {"content": fallback.fallback_reply("offtopic"), "cite": "", "turn": turn,
                "fallback": True, "related_videos": related}

    # ≤12 轮护栏：到顶直接给结论 + 推荐练习
    if turn >= MAX_TURN:
        topic = chapter_name(con, chapter_id)
        return {"content": fallback.conclude_reply(topic), "cite": "", "turn": turn,
                "fallback": True, "related_videos": related}

    if not chunks:
        return {"content": fallback.fallback_reply("empty", chapter_name(con, chapter_id)),
                "cite": "", "turn": turn, "fallback": True, "related_videos": related}

    system = TUTOR_SYSTEM.format(
        weak_chapters=weak_txt,
        retrieved_chunks=chunk_txt[:4000],
        related_videos=related_txt,
        turn=turn,
    )
    reply = agents.tutor_reply(system, _history(con, conversation["id"], turn))
    if reply is None:
        return {"content": fallback.fallback_reply("error"), "cite": "", "turn": turn,
                "fallback": True, "related_videos": related}
    # 引用标注：取 top-1 chunk 来源（P2 降维：仅提示有依据）
    cite = ""
    return {"content": reply, "cite": cite, "turn": turn, "fallback": False,
            "related_videos": related}


def _current_turn(con, conversation_id: str) -> int:
    """以 assistant 消息数作为辅导轮次。"""
    row = con.execute(
        "SELECT COUNT(*) AS c FROM messages WHERE conversation_id=? AND role='assistant'",
        (conversation_id,),
    ).fetchone()
    return row["c"]
