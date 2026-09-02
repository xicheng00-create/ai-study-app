"""批改（GRADER）：choice/bool 确定性；essay 走 DeepSeek 三档，失败降级关键词启发式。

百分制评分权双轨（QUIZ-003/009）：客观题系统确定性判分（0 或满分）；
问答题 AI 评 0–10（score 为实际得分点）。
"""

from ai import agents
from ai.prompts import GRADER_SYSTEM

# 题型满分（与 quizzer.POINTS 一致）
POINTS = {"choice": 5, "bool": 5, "essay": 10}


def points_for(qtype: str) -> float:
    return float(POINTS.get(qtype, 10))


def _deterministic(answer_key: str, student_answer: str, points: float) -> dict:
    key = (answer_key or "").strip()
    ans = (student_answer or "").strip()
    correct = key == ans
    return {"correct": 1 if correct else 0, "score": points if correct else 0.0,
            "reason": "正确答案" if correct else "答错"}


def _heuristic_essay(answer_key: str, student_answer: str, points: float) -> dict:
    """无 LLM 时的简答兜底：按关键词重合度给三档（满分/一半/0）。"""
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
        return {"correct": 1, "score": points, "reason": "参考答案过于简短，无法自动判定"}
    hit = sum(1 for t in key_tokens if t in ans)
    ratio = hit / len(key_tokens)
    if ratio >= 0.5:
        return {"correct": 1, "score": points, "reason": "要点基本齐全"}
    if ratio >= 0.25:
        return {"correct": 1, "score": round(points / 2, 1), "reason": "要点部分到位"}
    return {"correct": 0, "score": 0.0, "reason": "要点缺失较多"}


def grade_question(question: dict, student_answer: str) -> dict:
    """批改单题，返回实际得分点（score∈[0,points]）。"""
    qtype = question["type"]
    answer_key = question["answer_key"]
    points = float(question.get("points") or points_for(qtype))
    # 空答案一律判未作答 0 分（不等 LLM，避免 LLM 对空答给分）
    if not (student_answer or "").strip():
        return {"correct": 0, "score": 0.0, "reason": "未作答"}
    if qtype in ("choice", "bool"):
        return _deterministic(answer_key, student_answer, points)
    # essay：优先 GRADER LLM
    system = GRADER_SYSTEM.format(
        type=qtype,
        points=points,
        content=question["content"],
        options=question.get("options", "[]"),
        answer_key=answer_key,
        student_answer=student_answer,
    )
    out = agents.grader_grade(system)
    if out and "score" in out:
        score = max(0.0, min(points, float(out.get("score", 0))))
        correct = 1 if score >= points else 0
        return {"correct": correct, "score": score, "reason": out.get("reason", "")}
    return _heuristic_essay(answer_key, student_answer, points)
