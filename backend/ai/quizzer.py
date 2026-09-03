"""出题（QUIZZER）：DeepSeek 生成草稿题，失败降级到模板题（L2）。

百分制评分模型（QUIZ-005）：按题型赋分——选择/是非 5 分、问答 10 分；
题目组合须恰好 100 分，由 QUIZZER 按教师所选 config 生成。
"""
import json

from ai import agents, rag
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


# 兜底模板池：按 idx 轮转，避免同一道题重复 N 次（LLM 不可用/补发仍不足时用）
_TEMPLATES = {
    "choice": [
        {
            "content": "巩固练习/间隔复习的主要作用是？",
            "options": ["一次性测评", "间隔复习强化记忆", "替代课堂", "无需复习"],
            "answer": "1",
            "reason": "间隔复习能显著提升长期记忆",
            "sub_concept": "学习方法",
        },
        {
            "content": "苏格拉底式引导的核心原则是？",
            "options": ["直接给答案", "用追问引导学习者自己推导", "跳过提问直接讲结论", "只讲不练"],
            "answer": "1",
            "reason": "苏格拉底式引导强调追问而非直接给答案",
            "sub_concept": "学习方法",
        },
        {
            "content": "遇到不会的知识点，更推荐的做法是？",
            "options": ["直接跳过", "先自主尝试再求助，并记录错题", "照抄答案", "不复盘继续往下学"],
            "answer": "1",
            "reason": "主动尝试加错题记录更利于巩固",
            "sub_concept": "学习方法",
        },
    ],
    "bool": [
        {
            "content": "间隔复习的间隔会随答对而逐渐拉长（1→3→7）。",
            "answer": "正确",
            "reason": "答对顺延间隔、答错重置为 1",
            "sub_concept": "学习方法",
        },
        {
            "content": "苏格拉底式引导鼓励直接告诉学生最终答案。",
            "answer": "错误",
            "reason": "应以追问引导学生自己推导",
            "sub_concept": "学习方法",
        },
        {
            "content": "定期回顾与练习有助于把短期记忆转化为长期记忆。",
            "answer": "正确",
            "reason": "间隔复习是巩固长期记忆的有效手段",
            "sub_concept": "学习方法",
        },
    ],
    "essay": [
        {
            "content": "请用自己的话解释本章节的核心概念，并举一个例子。",
            "answer": "概念定义准确、例子恰当即为要点齐全",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "核心概念",
        },
        {
            "content": "结合本章资料，说明一个关键概念的含义及其适用场景。",
            "answer": "概念表述清晰、场景贴合即为要点齐全",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "核心概念",
        },
        {
            "content": "用自己的话总结本章节最重要的一个知识点，并说明理由。",
            "answer": "要点准确、理由充分即为要点齐全",
            "reason": "模板题（AI 不可用）",
            "sub_concept": "核心概念",
        },
    ],
}


def _template(qtype: str, idx: int) -> dict:
    """兜底模板：按 idx 轮转多样化，避免同一题重复 N 次。"""
    pool = _TEMPLATES[qtype]
    item = pool[idx % len(pool)]
    base = {"type": qtype, "options": item.get("options", [])}
    base.update(item)
    return base


def _enforce_config(qs: list[dict], config: dict) -> list[dict]:
    """按 config 裁剪题目数量，保证组合恰好 100 分。

    不足部分先由 generate_questions 向 DeepSeek 补发补足；仍不足才用模板兜底
    （模板按 idx 轮转，避免同一道题重复 N 次）。
    """
    out = []
    for t in POINTS:
        n = int(config.get(t) or 0)
        pool = [q for q in qs if q.get("type") == t]
        for i in range(n):
            out.append(pool[i] if i < len(pool) else _template(t, i))
    return out


def _missing(qs: list[dict], config: dict) -> dict:
    """统计各题型还缺几道（DeepSeek 生成数不足部分）。"""
    missing = {}
    for t in POINTS:
        n = int(config.get(t) or 0)
        have = sum(1 for q in qs if q.get("type") == t)
        if have < n:
            missing[t] = n - have
    return missing


def _retrieve_chunks(chapter_ids: list[str], query: str) -> list[dict]:
    """出题前检索章节资料正文；query 为空取整章片段，否则按子概念相关度召回。"""
    chunks: list[dict] = []
    seen: set[str] = set()
    for cid in chapter_ids:
        got = rag.retrieve(query, cid, top_k=5)
        if not got and query:
            # 子概念关键词未命中时，退化为整章资料片段（保证有资料喂给 DeepSeek）
            got = rag.retrieve("", cid, top_k=5)
        for c in got:
            if c["chunk_id"] in seen:
                continue
            seen.add(c["chunk_id"])
            chunks.append(c)
    return chunks


def _chunk_text(chunks: list[dict]) -> str:
    if not chunks:
        return "（无相关片段）"
    return "\n".join(f"- {c['text'][:300]}" for c in chunks)


def fallback_questions(chapter_ids: list[str], config: dict | None = None) -> list[dict]:
    """无 API/失败时的模板题（保证覆盖所选章节与 100 分组合）。"""
    cfg = config or default_config()
    return _enforce_config([], cfg)


def generate_questions(chapter_ids: list[str], sub_concepts: str = "", spec: str = "",
                       config: dict | None = None) -> list[dict]:
    cfg = config or default_config()
    spec_text = spec or _spec_text(cfg)
    # 出题前 RAG 检索章节资料正文，注入提示词（题目基于资料难度出题，根因①）
    query = (sub_concepts or "").strip()
    chunk_txt = _chunk_text(_retrieve_chunks(chapter_ids, query))

    system = QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec_text,
        retrieved_chunks=chunk_txt[:4000],
    )
    qs = agents.quizzer_generate(system)
    if not qs:
        return fallback_questions(chapter_ids, cfg)

    # 生成数不足：向 DeepSeek 补发一次补足缺口题型（根因②，不再用同一模板硬塞）
    missing = _missing(qs, cfg)
    if missing:
        fill_spec = "、".join(f"{n} 道{_TYPE_LABEL[t]}" for t, n in missing.items())
        fill_system = QUIZZER_SYSTEM.format(
            chapter_ids=",".join(chapter_ids),
            sub_concepts=sub_concepts or "不限",
            spec=fill_spec,
            retrieved_chunks=chunk_txt[:4000],
        )
        extra = agents.quizzer_generate(fill_system)
        if extra:
            qs = qs + extra
    return _enforce_config(qs, cfg)


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
