"""出题（QUIZZER）单元测试：题源=知识卡片（v2.7.4 教研定调）+ 取消 essay + 练习上限。

v2.7.4 变更：出题不再检索资料切片（rag.chunks），也不再使用通用模板兜底；
卡片是该范围唯一可考内容，无卡片或模型返空即返回空列表。
"""
from ai import agents, quizzer


def _fake_cards(rows):
    """构造 _retrieve_cards 的假返回（避免依赖真实 DB）。"""
    return [{"id": f"card-{i}", "chapter_id": r[0], "sub_concept": r[1],
             "front": r[2], "back": r[3]} for i, r in enumerate(rows)]


def test_enforce_config_no_template_fallback():
    """题库不足即止：不再用通用模板凑数（模板题不来自卡片）。"""
    assert quizzer._enforce_config([], {"choice": 10, "bool": 10}) == []
    qs = [{"type": "choice", "content": "q1", "sub_concept": ""}]
    out = quizzer._enforce_config(qs, {"choice": 3, "bool": 2})
    assert out == qs


def test_generate_questions_injects_cards_only(monkeypatch):
    """出题提示词只含知识卡片正文，且明确「卡片之外不得出题」。"""
    captured = {}
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda cids, per_sub=3, max_cards=50: _fake_cards(
        [("ch1", "概念辨析", "RAG 与微调的区别是什么？", "RAG 不改权重、靠外挂检索")]))

    def fake_generate(system):
        captured["system"] = system
        return [{"type": "choice", "content": "题干", "options": ["A", "B"], "answer": "0",
                 "reason": "", "sub_concept": ""}]

    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    quizzer.generate_questions(["ch1"], sub_concepts="RAG", config={"choice": 1})
    assert "RAG 不改权重、靠外挂检索" in captured["system"]
    assert "唯一题源：知识卡片" in captured["system"]
    assert "资料依据" not in captured["system"]


def test_generate_questions_empty_when_no_cards(monkeypatch):
    """该范围没有卡片时不得出题（返回空，由调用方提示）。"""
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda *a, **k: [])
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": "不该出现", "options": [], "answer": "0"}])
    assert quizzer.generate_questions(["ch1"], config={"choice": 5}) == []
    assert quizzer.generate_practice_questions(["ch1"]) == []
    assert quizzer.has_cards(["ch1"]) is False


def test_generate_questions_retries_when_short(monkeypatch):
    """模型生成数不足时补发一次请求补足，而非硬塞模板。"""
    calls = []
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda *a, **k: _fake_cards(
        [("ch1", "子概念A", "问题A", "答案A")]))

    def fake_generate(system):
        calls.append(system)
        if len(calls) == 1:
            return [{"type": "choice", "content": "q1", "options": ["A", "B"], "answer": "0",
                     "reason": "", "sub_concept": ""}]
        return [{"type": "choice", "content": f"q{i}", "options": ["A", "B"], "answer": "0",
                 "reason": "", "sub_concept": ""} for i in range(2, 6)]

    monkeypatch.setattr(agents, "quizzer_generate", fake_generate)
    out = quizzer.generate_questions(["ch1"], config={"choice": 5})
    assert len(out) == 5
    assert len(calls) == 2


def test_generate_practice_questions_max_5_no_essay_no_dup(monkeypatch):
    """练习最多 5 道 choice/bool、无 essay、题干无重复（不再强制 20/100）。"""
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda *a, **k: _fake_cards(
        [("ch1", f"子概念{i}", f"问题{i}", f"答案{i}") for i in range(20)]))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": f"题{i}", "options": ["A", "B", "C", "D"],
         "answer": "0", "reason": "", "sub_concept": f"子概念{i}"} for i in range(20)])
    out = quizzer.generate_practice_questions(["ch1"])
    assert 0 < len(out) <= quizzer.MAX_PRACTICE_QUESTIONS
    assert all(q["type"] in ("choice", "bool") for q in out)
    assert len({q["content"] for q in out}) == len(out)


def test_generate_questions_dedup_content(monkeypatch):
    """generate_questions 返回集按 content 去重，无重复题干。"""
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda *a, **k: _fake_cards(
        [("ch1", "子概念A", "问题A", "答案A")]))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": c, "options": ["A", "B"], "answer": "0", "reason": "", "sub_concept": ""}
        for c in ["重复题", "重复题", "题2", "题3", "题4", "题5"]])
    out = quizzer.generate_questions(["ch1"], config={"choice": 5})
    assert len(out) == 5
    assert len({q["content"] for q in out}) == 5


def test_retrieve_cards_round_robin_every_sub_concept(monkeypatch):
    """取卡按 sub_concept 轮转：热门知识点不能把冷门知识点挤出题源。"""
    rows = [{"id": f"hot-{i}", "chapter_id": "ch1", "sub_concept": "热门", "front": f"F{i}", "back": f"B{i}"}
            for i in range(30)]
    rows += [{"id": "cold-1", "chapter_id": "ch1", "sub_concept": "冷门", "front": "F", "back": "B"}]

    class _FakeCon:
        def execute(self, sql, params):
            cid = params[0]
            return type("R", (), {"fetchall": lambda _s: [r for r in rows if r["chapter_id"] == cid]})()

    monkeypatch.setattr(quizzer, "get_db", lambda: _FakeCon())
    # 本用例验取卡本身：还原真实 _retrieve_cards（conftest 默认打了桩）
    monkeypatch.setattr(quizzer, "_retrieve_cards", quizzer._real_retrieve_cards)
    out = quizzer._retrieve_cards(["ch1"], per_sub=2, max_cards=10)
    assert {c["sub_concept"] for c in out} == {"热门", "冷门"}
    assert len(out) == 3  # 冷门 1 张 + 热门 2 张（按 sub_concept 轮转取满 per_sub 轮）
    # 另一个章节无卡 → 整体为空
    assert quizzer._retrieve_cards(["ch-missing"]) == []


def test_cards_text_marks_empty_scope():
    assert "不得出题" in quizzer._cards_text([])
    assert "答案A" in quizzer._cards_text(
        [{"sub_concept": "子概念A", "front": "问题A", "back": "答案A"}])


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
    monkeypatch.setattr(quizzer, "_retrieve_cards", lambda *a, **k: _fake_cards(
        [("c", f"子{i}", f"问{i}", f"答{i}") for i in range(12)]))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": f"题{i}", "options": [], "answer": "0", "sub_concept": str(i)}
        for i in range(12)])
    assert len(quizzer.generate_practice_questions(["c"], count=99)) == 10
    assert len(quizzer.generate_practice_questions(["c"], count="bad")) == 5
