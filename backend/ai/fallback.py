"""固定引导语池（两层 Fallback 的 L2，Design Spec §7.2）。

DeepSeek 超时/报错、召回为空、越界时降级到此，绝不给编造答案。
"""
from ai.prompts import SENSITIVE_WORDS


def detect_sensitive(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in SENSITIVE_WORDS)


def detect_offtopic(text: str) -> bool:
    """粗略越界检测：请求做题/答案/非学习闲聊。"""
    low = (text or "").lower()
    quiz_hints = ("出题", "做题", "给我题", "测验", "考试题", "答案是什么", "直接告诉我答案")
    return any(h in low for h in quiz_hints)


def fallback_reply(kind: str, chapter_name: str = "") -> str:
    """kind ∈ {empty, error, sensitive, offtopic}。"""
    if kind == "empty":
        return (
            "我还没有在这份资料里找到和这个问题直接相关的内容，"
            "可以换个更具体的说法，或先切换到对应章节再问～"
        )
    if kind == "error":
        return "资料正在加载中，请稍后再试。我会尽量基于已解析的章节内容继续陪你推导。"
    if kind == "sensitive":
        return "这个话题和学习无关，我们回到资料内容上来吧。你可以继续问课程里的概念。"
    if kind == "offtopic":
        return "我更适合陪你一步步推导概念。如果要做题，请到「测评」页完成老师发布的题目；要复习薄弱点，可以到「进度」页一键生成巩固练习。"
    return "我们继续：先说说你自己对这个问题是怎么想的？"


def conclude_reply(topic: str) -> str:
    """≤12 轮护栏触发：给结论 + 推荐练习（CHAT-005）。"""
    return (
        f"本轮辅导已达 12 轮。关于「{topic}」，建议你先完成对应章节的测评来验证掌握情况，"
        "把错题作为下一步复习重点；卡住的概念可以开新对话继续引导。"
    )
