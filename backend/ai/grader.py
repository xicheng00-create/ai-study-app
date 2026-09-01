"""批改（GRADER）：choice/bool 确定性；essay 走 DeepSeek 三档，失败降级关键词启发式。"""

from ai import agents
from ai.prompts import GRADER_SYSTEM


def _deterministic(qtype: str, answer_key: str, student_answer: str) -> dict:
    key = (answer_key or "").strip()
    ans = (student_answer or "").strip()
    if qtype == "bool":
        correct = key == ans
    else:  # choice：答案索引
        correct = key == ans
    return {"correct": 1 if correct else 0, "score": 1.0 if correct else 0.0,
            "reason": "正确答案" if correct else "答错"}


def _heuristic_essay(answer_key: str, student_answer: str) -> dict:
    """无 LLM 时的简答兜底：按关键词重合度给三档。"""
    key = (answer_key or "").lower()
    ans = (student_answer or "").lower()
    if not ans:
        return {"correct": 0, "score": 0.0, "reason": "未作答"}
    # 拆参考答案关键词（中文按 2-gram、英文按词）
    import re
    key_tokens = set(re.findall(r"[a-z0-9]+", key))
    for seg in re.findall(r"[一-鿿]+", key):
        for i in range(len(seg) - 1):
            key_tokens.add(seg[i:i + 2])
    key_tokens = {t for t in key_tokens if len(t) > 1}
    if not key_tokens:
        return {"correct": 1, "score": 0.5, "reason": "参考答案过于简短，无法自动判定"}
    hit = sum(1 for t in key_tokens if t in ans)
    ratio = hit / len(key_tokens)
    if ratio >= 0.5:
        return {"correct": 1, "score": 1.0, "reason": "要点基本齐全"}
    if ratio >= 0.25:
        return {"correct": 0, "score": 0.5, "reason": "要点部分到位"}
    return {"correct": 0, "score": 0.0, "reason": "要点缺失较多"}


def grade_question(question: dict, student_answer: str) -> dict:
    qtype = question["type"]
    answer_key = question["answer_key"]
    if qtype in ("choice", "bool"):
        return _deterministic(qtype, answer_key, student_answer)
    # essay：优先 GRADER LLM
    system = GRADER_SYSTEM.format(
        type=qtype,
        content=question["content"],
        options=question.get("options", "[]"),
        answer_key=answer_key,
        student_answer=student_answer,
    )
    out = agents.grader_grade(system)
    if out and "score" in out:
        score = max(0.0, min(1.0, float(out.get("score", 0))))
        correct = 1 if score >= 0.5 else 0
        return {"correct": correct, "score": score, "reason": out.get("reason", "")}
    return _heuristic_essay(answer_key, student_answer)
