"""知识卡片生成与发布时共享卡片保障。"""
from data import models
from data.db import get_db

from ai import agents, quizzer
from ai.prompts import KNOWLEDGE_SYSTEM


def generate_knowledge_cards(chapter_ids: list[str]) -> list[dict]:
    chunks = quizzer._retrieve_chunks(chapter_ids, "")
    system = KNOWLEDGE_SYSTEM.format(
        chapter_ids=",".join(chapter_ids), retrieved_chunks=quizzer._chunk_text(chunks)[:6000]
    )
    cards = agents.knowledge_generate(system) or []
    seen, out = set(), []
    for card in cards:
        front = str(card.get("front") or "").strip()
        back = str(card.get("back") or "").strip()
        if front and back and front not in seen:
            seen.add(front)
            out.append({"front": front, "back": back,
                        "sub_concept": str(card.get("sub_concept") or "").strip()})
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
