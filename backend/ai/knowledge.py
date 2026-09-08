"""知识卡片生成：复用练习的全章多样化资料抽样。"""
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
