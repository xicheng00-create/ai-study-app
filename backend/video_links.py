"""卡片 ↔ 视频「能不能共享」的机械判据（REQ-VID-LINK-01）。

背景（2026-10-27 用户实测）：第 3 章「六大核心设计对象」那张卡，点开视频播的是
「持久化上下文工作台」——两回事。根因是共享链接由 LLM「挑最接近的 5–10 个」产生，
没有任何机械校验；全库 1044 条借链里绝大多数连字面都不沾。

口径（用户原话：共享只允许「同一个区块的知识点」）：
- 同一切片：`source_chunk_id` 相同 → 卡是从同一段资料长出来的，天然同源；
- 同一子概念：`sub_concept` 归一化后相同且非空 → 同一个「区块」。

字面相似度（`dice`）**不作为放行依据**：实测「PMF 的全称和含义是什么？」与
「MVP 的全称和含义是什么？」字面极像却是两个概念，而「职业发展」两条字面分很低却是同一块。
宁可不出共享，也不许张冠李戴：判不出来的卡，让用户自己点「生成视频」。
"""
from __future__ import annotations

import json
import re

MAX_LINKED = 10

_PUNCT = re.compile(r"[\s，。、；：！？,.;:!?（）()「」“”\"'·\-—…/]+")


def norm_text(text: str | None) -> str:
    return _PUNCT.sub("", text or "")


def bigrams(text: str | None) -> set[str]:
    s = norm_text(text)
    if len(s) <= 1:
        return {s} if s else set()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def dice(a: str | None, b: str | None) -> float:
    """字符二元组 Dice 系数，0..1。仅用于诊断排序，不用于放行。"""
    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def video_text(title: str | None, script_json: str | None) -> str:
    parts = [title or ""]
    try:
        script = json.loads(script_json or "{}")
        parts += [str(script.get("concept", "")), str(script.get("skeleton", ""))]
    except (ValueError, TypeError):
        pass
    return " ".join(parts)


def same_sub_concept(a: str | None, b: str | None) -> bool:
    na, nb = norm_text(a), norm_text(b)
    return bool(na) and na == nb


def same_chunk(a: str | None, b: str | None) -> bool:
    return bool(a) and a == b


def is_related(card, core) -> bool:
    """card/core 为含 sub_concept / source_chunk_id 的映射（dict 或 sqlite3.Row）。"""
    return same_chunk(card["source_chunk_id"], core["source_chunk_id"]) or same_sub_concept(
        card["sub_concept"], core["sub_concept"]
    )


def neighbours(con, card) -> list[str]:
    """同章里与本卡同区块的其它卡（同切片或同子概念），确定性、可复现。"""
    rows = con.execute(
        """SELECT id, sub_concept, source_chunk_id
           FROM knowledge_cards WHERE chapter_id=? AND id<>?""",
        (card["chapter_id"], card["id"]),
    ).fetchall()
    picked = [r["id"] for r in rows if is_related(r, card)]
    return picked[:MAX_LINKED]
