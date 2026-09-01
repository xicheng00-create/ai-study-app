"""出题（QUIZZER）：DeepSeek 生成草稿题，失败降级到模板题（L2）。"""
import json

from ai import agents
from ai.prompts import QUIZZER_SYSTEM


def fallback_questions(chapter_ids: list[str]) -> list[dict]:
    """无 API/失败时的模板题（至少覆盖所选章节，含 answer_key）。"""
    qs = []
    for _cid in chapter_ids:
        qs.append({
            "type": "essay",
            "content": "请用自己的话解释本章节的核心概念，并举一个例子。",
            "options": [],
            "answer": "概念定义准确、例子恰当即为要点齐全",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "核心概念",
        })
    if qs:
        qs.append({
            "type": "choice",
            "content": "巩固练习的作用是？",
            "options": ["一次性测评", "间隔复习强化记忆", "替代课堂", "无需复习"],
            "answer": "1",
            "reason": "间隔复习能显著提升长期记忆",
            "sub_concept": "学习方法",
        })
    return qs


def generate_questions(chapter_ids: list[str], sub_concepts: str = "", spec: str = "") -> list[dict]:
    system = QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec or "3 道题（至少 1 道简答）",
    )
    qs = agents.quizzer_generate(system)
    return qs if qs else fallback_questions(chapter_ids)


def norm_question(raw: dict, chapter_id: str) -> dict:
    """规范化为入库结构（type/content/options/answer_key）。"""
    qtype = raw.get("type", "choice")
    if qtype not in ("choice", "bool", "essay"):
        qtype = "choice"
    options = raw.get("options") or []
    if isinstance(options, str):
        options = [options]
    answer = raw.get("answer", raw.get("answer_key", ""))
    if isinstance(answer, (int, float)):
        answer = str(answer)
    return {
        "type": qtype,
        "content": raw.get("content", ""),
        "options": json.dumps([str(o) for o in options], ensure_ascii=False),
        "answer_key": str(answer),
        "sub_concept": raw.get("sub_concept", ""),
        "reason": raw.get("reason", ""),
    }
