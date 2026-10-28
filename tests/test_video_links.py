"""共享视频链接的判据（REQ-VID-LINK-01）。

背景：2026-10-27 用户实测，第 3 章「六大核心设计对象」那张卡点开播的是
「持久化上下文工作台」那一集——八竿子打不着。根因是借链由 LLM「挑最接近的
5–10 个」产生，没有机械校验。这里钉死允许共享的条件与边界。
"""
import sqlite3

from video_links import neighbours, is_related


def card(front="", sub="", chunk=""):
    return {"front": front, "back": "", "sub_concept": sub, "source_chunk_id": chunk}


def test_same_chunk_is_related():
    """同一段资料长出来的两张卡，允许共享。"""
    assert is_related(card("甲问题", "概念A", "c1"), card("乙问题", "概念B", "c1"))


def test_same_sub_concept_is_related():
    assert is_related(card("甲问题", "职业发展", "c1"), card("乙问题", "职业发展", "c2"))


def test_unrelated_cards_are_not_related():
    """用户实测的那一对：必须判不相关。"""
    a = card("大模型产品经理的核心设计对象从传统的按钮和页面转向哪六大技术与策略维度？", "大模型 PM 设计对象", "c1")
    b = card("课件中「持久化上下文工作台」在AI产品全流程中承担什么作用？", "设计对象与方法论", "c2")
    assert not is_related(a, b)


def test_template_only_match_is_not_related():
    """句式相同但对象不同（PMF vs MVP）：字面再像也不许共享。"""
    assert not is_related(card("PMF 的全称和含义是什么？", "", "a"), card("MVP 的全称和含义是什么？", "", "b"))


def test_empty_evidence_never_links():
    """两个都空：没有证据，不许共享（宁可不出片）。"""
    assert not is_related(card("随便一问", "", ""), card("随便另一问", "", ""))


def test_neighbours_only_same_block():
    """neighbours 只返回同切片/同子概念的卡，且不含自己。"""
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE knowledge_cards(
               id TEXT PRIMARY KEY, chapter_id TEXT, front TEXT, back TEXT,
               sub_concept TEXT, source_chunk_id TEXT)"""
    )
    rows = [
        ("core", "ch1", "六大设计对象是什么？", "", "设计对象", "c1"),
        ("same_chunk", "ch1", "设计对象与传统按钮的区别？", "", "", "c1"),
        ("same_sub", "ch1", "设计对象包括哪些维度？", "", "设计对象", "c9"),
        ("other", "ch1", "持久化上下文工作台是什么？", "", "方法论", "c2"),
    ]
    con.executemany("INSERT INTO knowledge_cards VALUES(?,?,?,?,?,?)", rows)
    core = con.execute("SELECT * FROM knowledge_cards WHERE id='core'").fetchone()
    got = neighbours(con, core)
    assert set(got) == {"same_chunk", "same_sub"}
    assert "other" not in got
    con.close()
