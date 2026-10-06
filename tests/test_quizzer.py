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
    # v2.13.1：允许少于 5 道（今日任务按「还差几道」出题：已答 2 道 → 出 3 道）
    assert len(quizzer.generate_practice_questions(["c"], count=3)) == 3
    assert len(quizzer.generate_practice_questions(["c"], count=1)) == 1
    assert len(quizzer.generate_practice_questions(["c"], count=0)) == 5  # 0 视为未指定 → 默认 5


def _ordered_fake_cards(subs, exclude=None, max_cards=None):
    """构造题源假返回：**按子概念名排序**（同真实 `_retrieve_cards` 的确定性顺序），
    并同样把已练过（exclude）的卡排到后面 —— 这样「调用方有没有传 exclude」会真影响结果。"""
    excl = exclude or set()
    order = sorted(subs, key=lambda s: (s in excl, s))
    cards = [{"id": f"card-{s}", "chapter_id": "ch1", "sub_concept": s,
              "front": f"{s}题干", "back": f"{s}答案"} for s in order]
    return cards[:max_cards] if max_cards else cards


def test_retrieve_cards_drops_practiced_sub_concepts(monkeypatch):
    """取卡本身必须把「已练过子概念」的卡排到题源之外（真实现，非打桩）。

    这是 2026-10-06「只出 1~2 道」的根因断言：老实现按 (sub_concept, created_at) 取前 50 张，
    已练过的子概念字典序最靠前 → 题源里 70% 是已练过的卡。
    """
    rows = [{"id": f"a-{i}", "chapter_id": "ch1", "sub_concept": f"A旧{i}", "front": f"A旧{i}题干",
             "back": "B"} for i in range(5)]
    rows += [{"id": f"b-{i}", "chapter_id": "ch1", "sub_concept": f"B新{i}", "front": f"B新{i}题干",
              "back": "B"} for i in range(60)]

    class _FakeCon:
        def execute(self, sql, params):
            cid = params[0]
            return type("R", (), {"fetchall": lambda _s: [r for r in rows if r["chapter_id"] == cid]})()

    monkeypatch.setattr(quizzer, "get_db", lambda: _FakeCon())
    monkeypatch.setattr(quizzer, "_retrieve_cards", quizzer._real_retrieve_cards)

    used = {f"A旧{i}" for i in range(5)}
    out = quizzer._retrieve_cards(["ch1"], exclude_sub_concepts=used)
    assert out and all(c["sub_concept"] not in used for c in out)   # 已练过的卡不得进题源
    assert quizzer._retrieve_cards(["ch1"])[:1][0]["sub_concept"] == "A旧0"  # 老行为：已练过的排最前


def test_practice_source_card_prefers_unpracticed(monkeypatch):
    """题源必须优先给「未练过」子概念的卡片（2026-10-06 只出 1~2 道的根因：老实现把已练过的卡喂给模型）。"""
    calls = []
    fresh = [f"B新{i}" for i in range(60)]   # 名字靠后 = 老实现里排不进前 50 张
    used = [f"A旧{i}" for i in range(5)]     # 名字靠前 = 老实现里必进题源
    monkeypatch.setattr(quizzer, "_retrieve_cards",
                        lambda cids, per_sub=3, max_cards=50, exclude_sub_concepts=None:
                        _ordered_fake_cards(fresh + used, exclude_sub_concepts, max_cards))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: (
        calls.append(system), [{"type": "choice", "content": f"题{i}", "options": ["A", "B"],
                                "answer": "0", "reason": "", "sub_concept": f"B新{i}"}
                               for i in range(5)])[1])
    out = quizzer.generate_practice_questions(["ch1"], exclude_sub_concepts=set(used), count=5)
    assert len(out) == 5
    # 严格档题源里只有未练过的卡（已练过的卡被挤出 max_cards=50 名之外）
    assert "B新0题干" in calls[0]
    assert "A旧0题干" not in calls[0]


def test_practice_falls_back_when_all_sub_concepts_practiced(monkeypatch):
    """题库跑尽（候选子概念全练过）时走兜底档，仍从卡片出题凑满题数，不再卡在半中央只出 1 道。"""
    subs = [f"子{i}" for i in range(10)]
    calls = []
    monkeypatch.setattr(quizzer, "_retrieve_cards",
                        lambda cids, per_sub=3, max_cards=50, exclude_sub_concepts=None:
                        _ordered_fake_cards(subs, exclude_sub_concepts))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: (
        calls.append(system), [{"type": "choice", "content": f"{len(calls)}批-题{i}",
                                "options": ["A", "B"], "answer": "0", "reason": "",
                                "sub_concept": subs[i]} for i in range(5)])[1])
    out = quizzer.generate_practice_questions(["ch1"], exclude_sub_concepts=set(subs), count=5)
    assert len(out) == 5                      # 严格档全被排除 → 兜底档补满
    assert len(calls) >= 2
    assert "优先避开" in calls[1]             # 兜底档提示词 = 已练过只降级为「优先跳过」


def test_practice_keeps_content_dedup_in_fallback(monkeypatch):
    """兜底档只放宽「子概念」，题干去重仍是硬约束（历史出过的题永不重复）。"""
    subs = ["子0"]
    monkeypatch.setattr(quizzer, "_retrieve_cards",
                        lambda cids, per_sub=3, max_cards=50, exclude_sub_concepts=None:
                        _ordered_fake_cards(subs, exclude_sub_concepts))
    monkeypatch.setattr(agents, "quizzer_generate", lambda system: [
        {"type": "choice", "content": "同一道题干", "options": ["A", "B"], "answer": "0",
         "reason": "", "sub_concept": "子0"}])
    out = quizzer.generate_practice_questions(
        ["ch1"], exclude_contents=["同一道题干"], exclude_sub_concepts={"子0"}, count=5)
    assert out == []

