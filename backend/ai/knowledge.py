"""知识卡片生成与发布时共享卡片保障。

历史问题（2026-09-19 整改）：旧实现只把 `_retrieve_chunks` 抽出的约 18 个切片、
每片截断 300 字、总长再砍到 6000 字喂给模型，长资料只能被看到一小部分，
导致卡片「只覆盖大框架、遗漏细碎考点」。现改为**按资料分层的全章投喂**，
并在提示词里明确要求穷尽式、细粒度抽取。
"""
from data import models
from data.db import get_db

from ai import agents
from ai.prompts import KNOWLEDGE_SYSTEM

# 送模型的课件原文预算（字符）
CONTENT_BUDGET = 20000
PER_CHUNK_CHARS = 600
MIN_SHARE = 1200          # 每份资料保底字数，避免长资料挤掉短资料
MIN_CARDS = 40            # 每章期望的最少卡片数


def _chapter_text(chapter_id: str) -> str:
    """该章全部资料的切片正文：按资料分层、每份保底、总预算内尽量多给。"""
    con = get_db()
    groups: list[tuple[str, str]] = []
    for m in con.execute(
        "SELECT id, original_name FROM materials WHERE chapter_id=? AND is_deleted=0"
        " ORDER BY created_at",
        (chapter_id,),
    ).fetchall():
        rows = con.execute(
            "SELECT text FROM chunks WHERE material_id=? ORDER BY chunk_idx", (m["id"],)
        ).fetchall()
        body = "\n".join((r["text"] or "")[:PER_CHUNK_CHARS] for r in rows).strip()
        if body:
            groups.append((m["original_name"], body))
    if not groups:
        return "（本章暂无解析出的资料切片）"

    share = max(MIN_SHARE, CONTENT_BUDGET // len(groups))
    parts: list[str] = []
    used = 0
    for name, body in groups:
        room = share if used < CONTENT_BUDGET else MIN_SHARE
        part = body[:room]
        used += len(part)
        parts.append(f"【资料：{name}】\n{part}")
    return "\n\n".join(parts)


def generate_knowledge_cards(chapter_ids: list[str]) -> list[dict]:
    system = KNOWLEDGE_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        retrieved_chunks="\n\n".join(_chapter_text(cid) for cid in chapter_ids),
        min_cards=MIN_CARDS * max(len(chapter_ids), 1),
    )
    cards = agents.knowledge_generate(system) or []
    seen, out = set(), []
    for card in cards:
        front = str(card.get("front") or "").strip()
        back = str(card.get("back") or "").strip()
        if front and back and front not in seen:
            seen.add(front)
            out.append({"front": front, "back": back,
                        "sub_concept": str(card.get("sub_concept") or "").strip()[:40]})
    return out


def ensure_chapter_cards(chapter_id: str) -> int:
    """已有共享卡直接复用；Agent 故障不影响资料或路径发布。"""
    try:
        con = get_db()
        existing = con.execute(
            "SELECT COUNT(*) AS c FROM knowledge_cards WHERE chapter_id=?", (chapter_id,)
        ).fetchone()["c"]
        if existing:
            return existing
        now = models.utcnow()
        for card in generate_knowledge_cards([chapter_id]):
            con.execute(
                "INSERT OR IGNORE INTO knowledge_cards "
                "(id,chapter_id,sub_concept,front,back,created_at) VALUES (?,?,?,?,?,?)",
                (models.new_id(), chapter_id, card["sub_concept"], card["front"], card["back"], now),
            )
        con.commit()
        return con.execute("SELECT COUNT(*) AS c FROM knowledge_cards WHERE chapter_id=?", (chapter_id,)).fetchone()["c"]
    except Exception:  # noqa: BLE001 - 发布钩子必须降级
        return 0
