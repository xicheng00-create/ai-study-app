"""出题（QUIZZER）单元测试：RAG 注入 + 模板兜底不再重复同一道题。"""
from ai import agents, quizzer, rag


def test_enforce_config_no_duplicate_template():
    """数量不足时模板兜底应多样化，不再同一道题重复 N 次。"""
    out = quizzer._enforce_config([], {"choice": 5, "bool": 3, "essay": 2})
    choice_contents = [q["content"] for q in out if q["type"] == "choice"]
    bool_contents = [q["content"] for q in out if q["type"] == "bool"]
    essay_contents = [q["content"] for q in out if q["type"] == "essay"]
    assert len(choice_contents) == 5
    assert len(bool_contents) == 3
    assert len(essay_contents) == 2
    assert len(set(choice_contents)) > 1
    assert len(set(bool_contents)) > 1
    assert len(set(essay_contents)) > 1


def test_generate_questions_injects_rag_chunks(monkeypatch):
    """RAG 检索结果应被注入出题提示词。"""
    captured = {}

    def fake_retrieve(query, chapter_id, top_k=5):
        return [{
            "chunk_id": "c1", "material_id": "m1", "chapter_id": chapter_id,
            "text": "资料片段：大模型是基于 Transformer 的神经网络", "score": 1.0,
        }]

    def fake_generate(system):
        captured["system"] = system
        return [{
            "type": "choice", "content": "题干", "options": ["A", "B"], "answer": "0",
            "reason": "", "sub_concept": "",
        }]

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    quizzer.generate_questions(["ch1"], sub_concepts="大模型", config={"choice": 1})
    assert "资料片段：大模型是基于 Transformer 的神经网络" in captured["system"]


def test_generate_questions_retries_when_short(monkeypatch):
    """DeepSeek 生成数不足时，应补发一次请求补足，而非硬塞模板。"""
    calls = []

    def fake_retrieve(query, chapter_id, top_k=5):
        return []

    def fake_generate(system):
        calls.append(system)
        if len(calls) == 1:
            return [{
                "type": "choice", "content": "q1", "options": ["A", "B"], "answer": "0",
                "reason": "", "sub_concept": "",
            }]
        return [{
            "type": "choice", "content": f"q{i}", "options": ["A", "B"], "answer": "0",
            "reason": "", "sub_concept": "",
        } for i in range(2, 6)]

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    out = quizzer.generate_questions(["ch1"], config={"choice": 5})
    assert len(out) == 5
    assert len(calls) == 2
