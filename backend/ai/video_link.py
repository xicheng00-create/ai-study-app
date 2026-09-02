"""视频课相关推荐（CHAT-010 / VIDEO-003，RAG 纯度红线）。

纯 SQL + 标签匹配的确定性召回：绝不 import ai.rag、不触达 chunks/embedding。
视频是结构化元数据，仅作「学员自选观看」的外链推荐，不是 RAG 知识源。
"""
import json

from data.db import get_db


def _json_list(raw):
    try:
        val = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def _collect_week_session(con, week_no, session_no, found):
    """按周+节取视频；session_no 为 NULL 的视频视为整周，一并召回。"""
    rows = con.execute(
        "SELECT * FROM video_resources WHERE status='published' AND week_no=?"
        " AND (session_no=? OR session_no IS NULL) ORDER BY order_no, created_at",
        (week_no, session_no),
    ).fetchall()
    for v in rows:
        found[v["id"]] = v


def retrieve_related_videos(chapter_ids=None, concept_tags=None, limit=3):
    """确定性召回相关视频（≤limit 条，按 order_no 升序）。

    ① 由 chapter_ids 反查所属 published session → 取其视频（周+节匹配）。
    ② 由 concept_tags 与视频标签重叠补召回。
    仅返回 status='published'；空召回静默返回 []（视频是锦上添花，非必需）。
    """
    con = get_db()
    chapter_ids = chapter_ids or []
    concept_tags = set(concept_tags or [])
    found = {}

    if chapter_ids:
        session_rows = con.execute(
            "SELECT week_no, session_no, chapter_ids FROM sessions WHERE status='published'"
        ).fetchall()
        for s in session_rows:
            if set(_json_list(s["chapter_ids"])) & set(chapter_ids):
                _collect_week_session(con, s["week_no"], s["session_no"], found)

    if concept_tags:
        vrows = con.execute(
            "SELECT * FROM video_resources WHERE status='published' ORDER BY order_no, created_at"
        ).fetchall()
        for v in vrows:
            if concept_tags & set(_json_list(v["concept_tags"])):
                found[v["id"]] = v

    ordered = sorted(found.values(), key=lambda v: (v["order_no"], v["created_at"]))
    return [
        {"title": v["title"], "url": v["url"], "platform": v["platform"]}
        for v in ordered[:limit]
    ]
