"""出题（QUIZZER）单元测试：RAG 注入 + 模板兜底不再重复同一道题 + 取消 essay + 练习最多 5 道。"""
from ai import agents, quizzer, rag


def test_enforce_config_no_duplicate_template():
    """数量不足时模板兜底应多样化：仅 choice/bool、无 essay、content 无重复。"""
    out = quizzer._enforce_config([], {"choice": 10, "bool": 10})
    assert len(out) == 20
    assert all(q["type"] in ("choice", "bool") for q in out)
    contents = [q["content"] for q in out]
    assert len(set(contents)) == 20


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


def test_generate_practice_questions_max_5_no_essay_no_dup(monkeypatch):
    """练习最多 5 道 choice/bool、无 essay、题干无重复（不再强制 20/100）。"""
    def fake_retrieve(query, chapter_id, top_k=5):
        return []

    def fake_generate(system):
        return [{
            "type": "choice", "content": f"题{i}", "options": ["A", "B", "C", "D"],
            "answer": "0", "reason": "", "sub_concept": "",
        } for i in range(20)]

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    out = quizzer.generate_practice_questions(["ch1"])
    assert 0 < len(out) <= quizzer.MAX_PRACTICE_QUESTIONS
    assert all(q["type"] in ("choice", "bool") for q in out)
    assert len({q["content"] for q in out}) == len(out)


def test_generate_questions_dedup_content(monkeypatch):
    """generate_questions 返回集按 content 去重，无重复题干。"""
    def fake_retrieve(query, chapter_id, top_k=5):
        return []

    def fake_generate(system):
        return [
            {"type": "choice", "content": "重复题", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
            {"type": "choice", "content": "重复题", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
            {"type": "choice", "content": "题2", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
            {"type": "choice", "content": "题3", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
            {"type": "choice", "content": "题4", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
            {"type": "choice", "content": "题5", "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""},
        ]

    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    out = quizzer.generate_questions(["ch1"], config={"choice": 5})
    assert len(out) == 5
    assert len({q["content"] for q in out}) == 5


def test_retrieve_chunks_samples_every_material(monkeypatch):
    """长 md 不能再被 material 排序靠前的 PDF 挤出上下文。"""
    def fake_retrieve(query, chapter_id, top_k=5):
        return [{"chunk_id": f"pdf-{i}", "material_id": "pdf", "chunk_idx": i, "text": "pdf"}
                for i in range(3)] + [{"chunk_id": f"md-{i}", "material_id": "md", "chunk_idx": i, "text": "md"}
                for i in range(82)]
    monkeypatch.setattr(rag, "retrieve", fake_retrieve)
    out = quizzer._retrieve_chunks(["ch1"], "")
    assert {c["material_id"] for c in out} == {"pdf", "md"}
    assert any(c["chunk_id"] == "md-81" for c in out)


def test_cap_to_max_prefers_distinct_sub_concepts():
    qs = [{"type": "choice", "content": f"q{i}", "sub_concept": sub}
          for i, sub in enumerate(["a", "a", "b", "c", "d", "e"])]
    out = quizzer._cap_to_max(qs, max_q=5)
    assert [q["sub_concept"] for q in out] == ["a", "b", "c", "d", "e"]


def test_cap_to_max_excludes_history_sub_concepts():
    qs = [{"type": "choice", "content": f"q{i}", "sub_concept": sub}
          for i, sub in enumerate(["old", "new-a", "new-b"])]
    assert [q["sub_concept"] for q in quizzer._cap_to_max(qs, { }, {"old"}, 5)] == ["new-a", "new-b"]


def test_generate_practice_count_boundaries(monkeypatch):
    monkeypatch.setattr(rag, "retrieve", lambda *args, **kwargs: [])
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": f"题{i}", "options": [], "answer": "0", "sub_concept": str(i)}
        for i in range(12)])
    assert len(quizzer.generate_practice_questions(["c"], count=99)) == 10
    assert len(quizzer.generate_practice_questions(["c"], count="bad")) == 5
