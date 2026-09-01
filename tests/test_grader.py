"""批改三档测试（QUIZ-003 / GRADER）。"""
import json

from ai import grader


def _q(qtype, answer_key, content="题目", options=None):
    return {
        "type": qtype,
        "content": content,
        "options": json.dumps(options or []),
        "answer_key": answer_key,
    }


def test_choice_deterministic():
    q = _q("choice", "1", options=["A", "B", "C"])
    assert grader.grade_question(q, "1")["correct"] == 1
    assert grader.grade_question(q, "0")["correct"] == 0
    assert grader.grade_question(q, "1")["score"] == 1.0


def test_bool_deterministic():
    q = _q("bool", "正确")
    assert grader.grade_question(q, "正确")["correct"] == 1
    assert grader.grade_question(q, "错误")["correct"] == 0


def test_essay_three_tiers():
    # 参考答案关键词：反向传播、链式法则、梯度
    q = _q("essay", "反向传播通过链式法则逐层计算梯度")
    good = grader.grade_question(q, "反向传播用链式法则计算每一层的梯度")
    assert good["score"] >= 0.5
    partial = grader.grade_question(q, "反向传播计算梯度")
    assert partial["score"] == 0.5
    bad = grader.grade_question(q, "我不知道，随便答")
    assert bad["score"] == 0.0


def test_essay_empty_answer():
    q = _q("essay", "反向传播通过链式法则逐层计算梯度")
    r = grader.grade_question(q, "")
    assert r["score"] == 0.0
