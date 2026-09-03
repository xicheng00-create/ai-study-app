"""关键词/章节轻量检索（RAG 降维替代 ChromaDB，Design Spec §八 降维）。

retrieve(query, chapter_id) → 对 chunks 按 query 分词重合度打分，
chapter_id 过滤，取 top-k=5；无命中返回空列表（触发兜底）。
"""
import re

from data.db import get_db

# 中文按字/英文按词切分：中文取 2-gram 关键词，英文取单词
_STOPWORDS = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "吗", "呢", "什么",
              "怎么", "为什么", "如何", "请", "个", "这", "那", "和", "与", "或"}


def _tokens(text: str) -> set[str]:
    text = (text or "").lower()
    words = set(re.findall(r"[a-z0-9]+", text))
    # 中文 2-gram（补充单字大词）
    cjk = re.findall(r"[一-鿿]+", text)
    for seg in cjk:
        if len(seg) == 1:
            words.add(seg)
        else:
            for i in range(len(seg) - 1):
                words.add(seg[i:i + 2])
    return {w for w in words if w and w not in _STOPWORDS and len(w) > 1}


def retrieve(query: str, chapter_id: str | None, top_k: int = 5) -> list[dict]:
    """返回 [{chunk_id, text, material_id, chapter_id, score}]。

    query 为空时不做关键词过滤，直接返回该章节资料片段（供出题等无 query 场景喂原文）。
    """
    con = get_db()
    q_tokens = _tokens(query)

    if chapter_id:
        rows = con.execute(
            "SELECT id, material_id, chapter_id, text FROM chunks WHERE chapter_id = ?"
            " ORDER BY material_id, chunk_idx",
            (chapter_id,),
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT id, material_id, chapter_id, text FROM chunks ORDER BY material_id, chunk_idx"
        ).fetchall()

    if not q_tokens:
        # 无 query：直接返回章节资料片段（供 QUIZZER 出题喂原文）
        return [
            {
                "chunk_id": r["id"],
                "material_id": r["material_id"],
                "chapter_id": r["chapter_id"],
                "text": r["text"][:800],
                "score": 0.0,
            }
            for r in rows[:top_k]
        ]

    scored = []
    for row in rows:
        c_tokens = _tokens(row["text"])
        if not c_tokens:
            continue
        overlap = q_tokens & c_tokens
        if overlap:
            # 重合度打分（简单 Jaccard），并按 query 命中比例加权
            score = len(overlap) / len(q_tokens)
            scored.append(
                {
                    "chunk_id": row["id"],
                    "material_id": row["material_id"],
                    "chapter_id": row["chapter_id"],
                    "text": row["text"][:800],
                    "score": round(score, 4),
                }
            )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]
