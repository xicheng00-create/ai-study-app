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

    第三张「BRD 章节」卡用于把本章 BRD df 抬到 3（R4 稀有拉丁 token 召回下限）。
    """
    monkeypatch.setenv("CARD_GATE_LOG", str(_log_path(tmp_path)))

    def dup(front_a, back_a, front_b, back_b=None):
        if "章节" in front_a or "章节" in front_b:
            return {"mergeable": False, "reason": "侧面不同"}
        if "BRD" in front_a and "BRD" in front_b:
            return {"mergeable": True, "reason": "同一考点 BRD，答案可无损合并"}
        return {"mergeable": False, "reason": "不同考点"}

    _stub(monkeypatch, dup)
    cards = [
        {"front": "BRD 的全称和用途是什么？",
         "back": "BRD 全称 Business Requirements Document，业务需求文档，用于记录产品需求与目标，含背景、范围、需求清单。"},
        {"front": "BRD 是什么的缩写，指什么",
         "back": "BRD 是 Business Requirements Document 的缩写。"},
        {"front": "BRD 应该包含哪些章节？", "back": "通常包含背景、目标、范围、需求清单等章节。"},
    ]
    kept, dropped = filter_new_cards(cards, "ch1", existing_fronts=[])
    kept_fronts = {c["front"] for c in kept}
    dropped_fronts = {c["front"] for c in dropped}

    dup_pair = {"BRD 的全称和用途是什么？", "BRD 是什么的缩写，指什么"}
    assert len(kept_fronts & dup_pair) == 1, "重复对必须只剩一张"
    assert len(dropped_fronts & dup_pair) == 1, "重复对必须丢弃一张"
    assert "BRD 应该包含哪些章节？" in kept_fronts

    log = _read_log(tmp_path)
    assert any(r.get("event") == "card_dropped" and r.get("rule") for r in log), \
        "被丢卡要写入审计日志并带命中规则"


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
