"""引导式对话编排（CHAT-004/005，F5 输出门控，两层 Fallback）。"""
import json

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
    row = con.execute("SELECT name FROM chapters WHERE id=? LIMIT 1", (chapter_id,)).fetchone()
    return row["name"] if row else "全部资料"


def _last_user_substantive(history: list[dict]) -> str:
    """从对话历史里取最近一条『实质性』用户提问（跳过承接语/当前轮）。

    承接语（如「你帮我展开」「继续」「那第三点呢」「展开讲讲」）单独检索不到资料，
    需要回退到上一轮真正问内容的 user 消息去 RAG 检索。取 history 中（不含末尾）
    最近的 role=user 且长度足够非承接语的消息；无则返回空串。
    """
    SUBSTITUTE = {"你帮我展开", "继续展开", "展开讲讲", "继续", "展开", "那第三点呢",
                  "那第二个呢", "讲详细点", "详细说说", "再说说", "展开说一下", "说详细点"}
    # history 从旧到新；末尾可能是当前轮 user（post_message 已写入），跳过后再向前找
    for msg in reversed(history):
        if msg.get("role") != "user":
            continue
        txt = (msg.get("content") or "").strip()
        if not txt or txt in SUBSTITUTE or len(txt) <= 2:
            continue
        return txt
    return ""


def _history(con, conversation_id: str, turn: int) -> list[dict]:
    rows = con.execute(
        "SELECT role, content FROM messages WHERE conversation_id=?"
        " ORDER BY created_at ASC, rowid ASC LIMIT ?",
        (conversation_id, turn * 2 + 4),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def _choice_label(val, opts):
    """choice：索引字符串 -> '字母.选项文本'；bool/文本/越界回退原值。"""
    try:
        idx = int(val)
        if 0 <= idx < len(opts):
            return f"{chr(65 + idx)}.{opts[idx]}"
    except (TypeError, ValueError):
        pass
    return val


def _format_wrong_ctx(wrong_ctx) -> str:
    """将已作答错题压缩为 TUTOR 可用上下文（含完整选项 + 字母标注，供输出结构化解析）。"""
    if not wrong_ctx:
        return "（本次未提供错题）"
    if not isinstance(wrong_ctx, list):
        wrong_ctx = [wrong_ctx]
    rows = []
    for i, item in enumerate(wrong_ctx[:20], 1):
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        opts = item.get("options") or []
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except (json.JSONDecodeError, ValueError, TypeError):
                opts = []
        opts = [str(o) for o in opts]
        typ = item.get("type")
        opt_txt = "｜".join(f"{chr(65 + j)}.{o}" for j, o in enumerate(opts)) if opts else ""
        your_txt = _choice_label(item.get('your_answer'), opts) if (typ == "choice" and opts) else str(item.get('your_answer') or "未作答")
        key_txt = _choice_label(item.get('answer_key'), opts) if (typ == "choice" and opts) else str(item.get('answer_key') or "未提供")
        line = f"- 第{i}题：{content}"
        if opt_txt:
            line += f"\n  选项：{opt_txt}"
        line += f"\n  学生选：{your_txt}"
        line += f"\n  正确：{key_txt}"
        if item.get("sub_concept"):
            line += f"\n  考点：{item['sub_concept']}"
        rows.append(line)
    return "\n".join(rows) or "（本次未提供有效错题）"


def _retrieve_multi(con, content: str, chapter_id, chapter_ids, top_k=5) -> list:
    """多选集 RAG 检索（v2.0.0）：学习主菜单多选章后，TUTOR 在所选章资料内检索。

    scope = chapter_ids(去空) + 归属 chapter_id(未在列则插首)；每章 retrieve top_k 后合并去重。
    单章/无选集 → 维持原单章行为。
    """
    scope = [c for c in (chapter_ids or []) if c]
    if chapter_id and chapter_id not in scope:
        scope.insert(0, chapter_id)
    if len(scope) <= 1:
        return rag.retrieve(content, chapter_id, top_k=top_k)
    merged, seen = [], set()
    for cid in scope:
        for ch in rag.retrieve(content, cid, top_k=top_k):
            if ch["chunk_id"] not in seen:
                seen.add(ch["chunk_id"])
                merged.append(ch)
    return merged[: top_k * 3]


def tutor_orchestrate(con, user_row, conversation, content: str, chapter_id: str | None,
                      concept_tags=None, chapter_ids=None, wrong_ctx=None,
                      tutor_mode: str = "direct", kc_ctx=None) -> dict:
    """返回 {content, cite, turn, fallback, related_videos}。

    tutor_mode：普通提问（无错题）的辅导模式，`direct` 直接讲解 / `guide` 苏格拉底引导。
    带错题（wrong_ctx 非空）时强制直接解析，不受 tutor_mode 影响。
    kc_ctx（v2.1.0）：知识卡片「去问 TUTOR」携带的 {front,back,sub_concept,chapter_id}，
    卡片答案作为可靠上下文注入 system，并强制直接模式做发散讲解。
    """
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

    # 多轮历史：提前取出（含刚写入的当前用户消息），供检索回退 + gate 判断 + LLM 承接
    history = _history(con, conversation["id"], turn)
    # 检索当前消息（多选集 → 逐章检索合并，跨章资料都能答）；承接语单独检索会空，回退用上一轮实质提问
    chunks = _retrieve_multi(con, content, chapter_id, chapter_ids)
    if not chunks:
        last_q = _last_user_substantive(history)
        if last_q and last_q != content:
            chunks = _retrieve_multi(con, last_q, chapter_id, chapter_ids)
    if chunks:
        # 多章来源时给每条片段标注【章名】，避免 LLM 混淆资料归属
        src_chapters = sorted({c["chapter_id"] for c in chunks})
        multi = len(src_chapters) > 1
        chunk_txt = "\n".join(
            f"- {('【' + chapter_name(con, c['chapter_id']) + '】') if multi else ''}{c['text'][:300]}"
            for c in chunks
        )
    else:
        chunk_txt = "（无相关片段）"

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

    # 检索不到且无错题、且无任何历史上下文（首问即空）→ 才兜底。
    # 有历史上下文时放行让 LLM 承接（学生可能用承接语继续，不能因单轮检索空就打断上下文）。
    # 知识卡片提问（kc_ctx）不受此限：卡片答案本身就是可靠上下文，可脱离资料单独发散。
    if not chunks and not wrong_ctx and not kc_ctx and not history:
        return {"content": fallback.fallback_reply("empty", chapter_name(con, chapter_id)),
                "cite": "", "turn": turn, "fallback": True, "related_videos": related}

    # 错题辅导/知识卡片发散强制直接讲解；普通提问按学生开关选择模式（非法值回退直接讲解）
    mode = "direct" if (wrong_ctx or kc_ctx) else (tutor_mode if tutor_mode in ("guide", "direct") else "direct")
    mode_label = "直接讲解" if mode == "direct" else "引导式"

    # 知识卡片上下文（v2.1.0）：front/back 注入 system，供 TUTOR 发散讲解
    kc_txt = "（无）"
    if kc_ctx:
        kc_txt = (
            f"知识点：{str(kc_ctx.get('front') or '')[:800]}\n"
            f"卡片答案要点：{str(kc_ctx.get('back') or '')[:2000]}\n"
            f"来源章节：{chapter_name(con, str(kc_ctx.get('chapter_id') or chapter_id or ''))}"
        )

    system = TUTOR_SYSTEM.format(
        weak_chapters=weak_txt,
        retrieved_chunks=chunk_txt[:4000],
        knowledge_card=kc_txt,
        related_videos=related_txt,
        wrong_ctx=_format_wrong_ctx(wrong_ctx),
        tutor_mode=mode_label,
        turn=turn,
    )
    reply = agents.tutor_reply(system, history)
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
