"""分组标签归一（`ai.cardtext.normalize_label`）—— 口径条款 CR-2026-0922-SUBCONCEPT-NORMALIZE。

覆盖点：中↔英/数之间补空格、`×` 分隔、不删已有空格（W6/W8）、空白折叠、
已知缩写归一（To C → ToC）、幂等、空值、截断、同义判定键。
"""
from ai.cardtext import group_key, normalize_label


def test_cjk_latin_gets_space():
    assert normalize_label("MCP协议") == "MCP 协议"
    assert normalize_label("Prompt工程") == "Prompt 工程"
    assert normalize_label("最小IA图实操") == "最小 IA 图实操"
    # 两侧都要补：中→英 与 英→中
    assert normalize_label("系统用API") == "系统用 API"


def test_digits_and_cjk():
    assert normalize_label("1页README该写什么") == "1 页 README 该写什么"
    assert normalize_label("第4章") == "第 4 章"


def test_multiply_sign_spacing():
    assert normalize_label("IA×SA×文档") == "IA × SA × 文档"
    assert normalize_label("三者关系：IA×SA×文档") == "三者关系：IA × SA × 文档"
    # 已带空格的写法不被二次改动
    assert normalize_label("IA × SA × 文档") == "IA × SA × 文档"


def test_existing_spaces_are_preserved():
    # 拉丁词之间的空格是语义的一部分，不能抹掉
    assert normalize_label("W6/W8") == "W6/W8"
    assert normalize_label("MCP Server 模块") == "MCP Server 模块"
    assert normalize_label("System Prompt 设计") == "System Prompt 设计"


def test_known_abbreviation_fix():
    # 「To C」与「ToC」是同一缩写的两种写法，统一到 ToC
    assert normalize_label("To C可行模式") == "ToC 可行模式"
    assert normalize_label("ToC可行模式") == "ToC 可行模式"


def test_whitespace_collapse_and_strip():
    assert normalize_label("  RAG   检索增强  ") == "RAG 检索增强"
    assert normalize_label("RAG\u3000检索增强") == "RAG 检索增强"   # 全角空格也算空白


def test_plain_text_untouched():
    assert normalize_label("中文标签") == "中文标签"
    assert normalize_label("ABC") == "ABC"


def test_empty_and_none():
    assert normalize_label("") == ""
    assert normalize_label(None) == ""
    assert normalize_label("   ") == ""


def test_limit():
    assert normalize_label("Transformer 架构与起源", 14) == "Transformer 架构"
    # 截断发生在归一之后，不会把空格留在末尾
    assert normalize_label("模型上下文协议说明", 40) == "模型上下文协议说明"


def test_idempotent():
    samples = ["MCP协议", "To C可行模式", "IA×SA×文档", "1页README该写什么",
               "  RAG   检索增强  ", "W6/W8", "AIOS核心模块", ""]
    for s in samples:
        once = normalize_label(s)
        assert normalize_label(once) == once, s


def test_group_key_ignores_whitespace():
    assert group_key("MCP 协议") == group_key("MCP协议") == "MCP协议"
    assert group_key("IA × SA × 文档") == group_key("IA×SA×文档")
    assert group_key("MCP 协议") != group_key("MCP 服务")
