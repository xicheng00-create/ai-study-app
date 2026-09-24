"""知识卡片「重复出卡」止血闸门（KNOW-014 / v2.9.4）。

LLM 一律用 stub（不真调），验证确定性预筛（宁可多召回）+ LLM 确认后的丢弃/保留，
以及 LLM 失败时的降级（全部保留、不抛错）。
"""
import json

from ai import agents
from ai.cardgate import filter_new_cards


def _log_path(tmp_path):
    return tmp_path / "card_gate.jsonl"


def _read_log(tmp_path):
    p = _log_path(tmp_path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


def _stub(monkeypatch, fn):
    monkeypatch.setattr(agents, "knowledge_dup_check", fn)


def test_drops_brd_dup_pair(monkeypatch, tmp_path):
    """同一考点换措辞（BRD 全称 / BRD 缩写）→ 丢弃信息较少的一张。

    本章只有这两张卡共享 BRD（df=2），必须走 R4 召回下限 → 走到 LLM 确认。
    防回归：必须断言 LLM 确实被调用过（预筛阈值回归成不触发时，仅断言结果会静默通过）。
    """
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    calls = []

    def dup(front_a, back_a, front_b, back_b=None):
        calls.append((front_a, front_b))
        if "BRD" in front_a and "BRD" in front_b:
            return {"mergeable": True, "reason": "同一考点 BRD，答案可无损合并"}
        return {"mergeable": False, "reason": "不同考点"}

    _stub(monkeypatch, dup)
    cards = [
        {"front": "BRD 的全称和用途是什么？",
         "back": "BRD 全称 Business Requirements Document，业务需求文档，用于记录产品需求与目标，含背景、范围、需求清单。"},
        {"front": "BRD 是什么的缩写，指什么",
         "back": "BRD 是 Business Requirements Document 的缩写。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    kept_fronts = {c["front"] for c in kept}
    dropped_fronts = {c["front"] for c in dropped}

    dup_pair = {"BRD 的全称和用途是什么？", "BRD 是什么的缩写，指什么"}
    assert len(kept_fronts & dup_pair) == 1, "重复对必须只剩一张"
    assert len(dropped_fronts & dup_pair) == 1, "重复对必须丢弃一张"

    # 防回归：这对卡必须真的走到 LLM 确认（df=2 时 R4 也要召回）
    assert len(calls) >= 1, "BRD 对必须触发 LLM 确认（R4 下界 2 漏判回归会走到这里失败）"
    assert any(("BRD 的全称" in fa and "BRD 是什么" in fb) or
               ("BRD 的全称" in fb and "BRD 是什么" in fa) for fa, fb in calls), \
        "LLM 确认必须覆盖 BRD 那一对"

    log = _read_log(tmp_path)
    assert any(r.get("event") == "card_dropped" and r.get("rule") for r in log), \
        "被丢卡要写入审计日志并带命中规则"


def test_drops_brd_dup_pair_in_large_corpus(monkeypatch, tmp_path):
    """大批量语料 df 场景：existing_fronts 塞 30 张含其它实体的卡 + 这 2 张 BRD 卡 → 仍判重。

    30 张其它实体把 BRD df 维持在 2（稀有），不得因语料变大而漏判。
    """
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    calls = []

    def dup(front_a, back_a, front_b, back_b=None):
        calls.append((front_a, front_b))
        if "BRD" in front_a and "BRD" in front_b:
            return {"mergeable": True, "reason": "同一考点 BRD，答案可无损合并"}
        return {"mergeable": False, "reason": "不同考点"}

    _stub(monkeypatch, dup)
    existing = [f"实体{i} 的定义是什么" for i in range(30)]
    cards = [
        {"front": "BRD 的全称和用途是什么？", "back": "BRD 全称 Business Requirements Document，业务需求文档。"},
        {"front": "BRD 是什么的缩写，指什么", "back": "BRD 是 Business Requirements Document 的缩写。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=existing)
    assert len(kept) == 1 and len(dropped) == 1
    assert any(("BRD 的全称" in fa and "BRD 是什么" in fb) or
               ("BRD 的全称" in fb and "BRD 是什么" in fa) for fa, fb in calls), \
        "BRD 对在大语料下仍须走到 LLM 确认"


def test_r4_guarded_against_common_token(monkeypatch, tmp_path):
    """反例：existing_fronts 塞 50 张含同一 token 的卡（df>40）→ R4 不再触发（泛词护栏有效）。

    token 已是全章泛词（>40），不再靠「稀有实体锚点」召回；两张新卡无其它相似性 → 全留。
    """
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    calls = []

    def dup(front_a, back_a, front_b, back_b=None):
        calls.append((front_a, front_b))
        return {"mergeable": True, "reason": "不应被调到的 LLM 确认"}

    _stub(monkeypatch, dup)
    existing = [f"API 的第 {i} 个用法是什么" for i in range(50)]
    cards = [
        {"front": "API 的定义是什么", "back": "API 是应用程序编程接口。"},
        {"front": "API 网关的作用", "back": "API 网关负责路由、限流、鉴权。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=existing)
    assert len(kept) == 2 and dropped == [], "df>40 的泛词不得触发 R4 召回"
    assert calls == [], "泛词 token 不应触发 LLM 确认"


def test_drops_tool_calling_dup_pair(monkeypatch, tmp_path):
    """中英同义换措辞（工具调用 / tool calling）→ 走完整「候选 → LLM → 丢弃」路径。"""
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    def dup(front_a, back_a, front_b, back_b=None):
        if "工具调用" in front_a and "工具调用" in front_b:
            return {"mergeable": True, "reason": "同一考点 工具调用，答案可无损合并"}
        return {"mergeable": False, "reason": "不同考点"}

    _stub(monkeypatch, dup)
    cards = [
        {"front": "工具调用是什么？", "back": "工具调用是让大模型通过结构化方式调用外部工具的机制。"},
        {"front": "什么是工具调用（tool calling）？", "back": "工具调用（tool calling）是让模型调用外部工具的能力。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    assert len(kept) == 1 and len(dropped) == 1
    assert {kept[0]["front"], dropped[0]["front"]} == {
        "工具调用是什么？", "什么是工具调用（tool calling）？"}


def test_keeps_same_template_different_subject(monkeypatch, tmp_path):
    """同模板异主体（四家 IDE）→ 预筛召回但 LLM 判 false，保留。"""
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))
    _stub(monkeypatch, lambda fa, ba, fb, bb=None: {"mergeable": False, "reason": "同模板不同主体"})
    cards = [
        {"front": "Cursor 的核心优势是什么？", "back": "a"},
        {"front": "Copilot 的核心优势是什么？", "back": "b"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    assert len(kept) == 2 and dropped == []


def test_keeps_different_numbers(monkeypatch, tmp_path):
    """数字/阈值不同 → LLM 判 false，保留。"""
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))
    _stub(monkeypatch, lambda fa, ba, fb, bb=None: {"mergeable": False, "reason": "数字不同"})
    cards = [
        {"front": "比例 0.5 表示什么", "back": "x"},
        {"front": "比例 0.5-1 表示什么", "back": "y"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    assert len(kept) == 2 and dropped == []


def test_keeps_definition_vs_misconception(monkeypatch, tmp_path):
    """定义 vs 误区（同词 BRD 但侧面不同）→ R4 召回但 LLM 判 false，保留。"""
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))
    _stub(monkeypatch, lambda fa, ba, fb, bb=None: {"mergeable": False, "reason": "定义 vs 误区"})
    # 已有卡把 BRD df 抬到 3，触发 R4 召回
    existing = ["BRD 的定义是什么", "BRD 的评审标准", "BRD 的模板"]
    cards = [
        {"front": "什么是 BRD", "back": "BRD 是业务需求文档。"},
        {"front": "关于 BRD 的常见误区", "back": "误区是认为 BRD 只是文档格式。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=existing)
    assert len(kept) == 2 and dropped == []


def test_llm_failure_keeps_all_and_logs_degraded(monkeypatch, tmp_path):
    """LLM 抛异常/超时 → 一律保留、函数不抛错，审计日志记 gate_degraded。"""
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    _stub(monkeypatch, boom)
    cards = [
        {"front": "BRD 的全称和用途是什么？", "back": "BRD 全称 Business Requirements Document，业务需求文档。"},
        {"front": "BRD 是什么的缩写，指什么", "back": "BRD 是 Business Requirements Document 的缩写。"},
        {"front": "BRD 应该包含哪些章节？", "back": "通常包含背景、目标、范围。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    assert len(kept) == 3 and dropped == []
    assert any(r.get("gate_degraded") for r in _read_log(tmp_path))
