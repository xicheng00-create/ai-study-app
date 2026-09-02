"""出题（QUIZZER）：DeepSeek 生成草稿题，失败降级到模板题（L2）。

百分制评分模型（QUIZ-005）：按题型赋分——选择/是非 5 分、问答 10 分；
题目组合须恰好 100 分，由 QUIZZER 按教师所选 config 生成。
"""
import json

from ai import agents
from ai.prompts import QUIZZER_SYSTEM

# 题型满分（QUIZ-005，选择/是非 5、问答 10）
POINTS = {"choice": 5, "bool": 5, "essay": 10}

# 100 分预设组合（QUIZ-005）
PRESETS = {
    "10c5e": {"choice": 10, "essay": 5},
    "8c6e": {"choice": 8, "essay": 6},
    "20c": {"choice": 20},
}

_TYPE_LABEL = {"choice": "选择题", "bool": "是非题", "essay": "问答题"}


def default_config() -> dict:
    return dict(PRESETS["10c5e"])


def config_total(config: dict) -> int:
    """按题型分值计算组合总分（用于校验=100）。"""
    return sum(POINTS[t] * int(config.get(t) or 0) for t in POINTS)


def validate_config(config) -> dict:
    """归一化并校验组合；非法返回空 dict（调用方回错误）。"""
    if not isinstance(config, dict):
        return {}
    cfg = {}
    for t in POINTS:
        n = config.get(t)
        if n is None:
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {}
        if n < 0:
            return {}
        if n:
            cfg[t] = n
    return cfg


def _spec_text(config: dict) -> str:
    parts = [f"{int(config.get(t) or 0)} 道{_TYPE_LABEL[t]}" for t in POINTS if config.get(t)]
    return "共 " + " + ".join(parts) + "（选择/是非各 5 分，问答 10 分，合计 100 分）"


def _template(qtype: str, idx: int) -> dict:
    """单题模板（LLM 不可用 / 补齐数量时用）。"""
    if qtype == "essay":
        return {
            "type": "essay",
            "content": "请用自己的话解释本章节的核心概念，并举一个例子。",
            "options": [],
            "answer": "概念定义准确、例子恰当即为要点齐全",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "核心概念",
        }
    if qtype == "bool":
        return {
            "type": "bool",
            "content": "间隔复习的间隔会随答对而逐渐拉长（1→3→7）。",
            "options": [],
            "answer": "正确",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "学习方法",
        }
    opts = ["一次性测评", "间隔复习强化记忆", "替代课堂", "无需复习"]
    return {
        "type": "choice",
        "content": "巩固练习/间隔复习的主要作用是？",
        "options": opts,
        "answer": "1",
        "reason": "间隔复习能显著提升长期记忆",
        "sub_concept": "学习方法",
    }


def _enforce_config(qs: list[dict], config: dict) -> list[dict]:
    """按 config 补齐/裁剪题目数量，保证组合恰好 100 分。"""
    out = []
    for t in POINTS:
        n = int(config.get(t) or 0)
        pool = [q for q in qs if q.get("type") == t]
        for i in range(n):
            out.append(pool[i] if i < len(pool) else _template(t, i))
    return out


def fallback_questions(chapter_ids: list[str], config: dict | None = None) -> list[dict]:
    """无 API/失败时的模板题（保证覆盖所选章节与 100 分组合）。"""
    cfg = config or default_config()
    return _enforce_config([], cfg)


def generate_questions(chapter_ids: list[str], sub_concepts: str = "", spec: str = "",
                       config: dict | None = None) -> list[dict]:
    cfg = config or default_config()
    system = QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec or _spec_text(cfg),
    )
    qs = agents.quizzer_generate(system)
    return _enforce_config(qs, cfg) if qs else fallback_questions(chapter_ids, cfg)


def norm_question(raw: dict, chapter_id: str) -> dict:
    """规范化为入库结构（type/content/options/answer_key/points）。"""
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
        "points": POINTS[qtype],
    }
