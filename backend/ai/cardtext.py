"""分组标签文本规范化（共享口径，v2.8.1 / CR-2026-0922-SUBCONCEPT-NORMALIZE）。

问题：`knowledge_cards.sub_concept` 由大模型自由生成，同一个知识点被写成
「MCP 协议」与「MCP协议」两种写法（差异仅空格）→ 前端按标签分组时同一知识点
显示成两个组，组数虚增、看起来重复。

口径（对后续一律适用）：
1. **`knowledge_cards.sub_concept` 在入库前一律过 `normalize_label()`** —— 覆盖路径见各调用点：
   - 在线生成：`backend/ai/knowledge.py::generate_knowledge_cards`
   - 离线生成：`scripts/rebuild_cards.py`（正片/补卡/孤儿补卡三条插入路径）
   - 存量收敛：`scripts/normalize_subconcepts.py`
   注：`card_topics.topic`（学生端分组头，v2.7.0 起）**不纳入本口径** —— 它由
   `scripts/group_cards.py` 每章**一次性生成**，章内天然同构、无分裂；若把归一规则
   套上去，会无收益地改写线上学生正在看的 413 个主题名（2026-09-22 实测）。
   将来若发现 topic 出现分裂，再把该列并入 TARGETS。
2. 规则：去首尾空白 → 内部连续空白折叠为单个半角空格 → **中日韩字符与
   拉丁字母/数字之间补一个半角空格**（含 `×` 与两侧的分隔）。
   不删除已有空格（避免破坏 `W6/W8`、`IA × SA` 之类既有写法）。
3. 违规处置：任何绕过本函数的插入路径视为「口径旁路」，审计发现即按缺陷处理
   （`tests/test_cardtext.py` 覆盖函数本身；`scripts/normalize_subconcepts.py`
   可随时把库内残留收敛回来并打印前后组数）。

本函数幂等：`normalize_label(x) == normalize_label(normalize_label(x))`。
"""
import re

# 中日韩统一表意文字（含扩展 A）+ 兼容表意 + 日文假名 + 谚文
_CJK = "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af"
_LATIN = "A-Za-z0-9"

# 已知「同一缩写的两种分词」——随发现扩充，仅限 token 级、明确无歧义的写法。
# 例：「To C可行模式」与「ToC可行模式」是同一个标签的两种写法（ToC = To Consumer）。
_TOKEN_FIXES = (("To C", "ToC"),)

_WS = re.compile(r"\s+")
_CJK_LATIN = re.compile(f"([{_CJK}])([{_LATIN}])")
_LATIN_CJK = re.compile(f"([{_LATIN}])([{_CJK}])")
_CJK_SYM = re.compile(f"([{_CJK}{_LATIN}])(×)")
_SYM_CJK = re.compile(f"(×)([{_CJK}{_LATIN}])")


def normalize_label(raw, limit: int = 40) -> str:
    """把分组标签归一成唯一写法；空值返回空串。limit 为截断上限（默认 40）。"""
    if not raw:
        return ""
    text = _WS.sub(" ", str(raw)).strip()
    for bad, good in _TOKEN_FIXES:
        text = text.replace(bad, good)
    # 中↔英/数 两侧各补一个空格（已有空格时正则不匹配，不会产生双空格）
    text = _CJK_LATIN.sub(r"\1 \2", text)
    text = _LATIN_CJK.sub(r"\1 \2", text)
    # `×` 与两侧中英数之间同样留空格（「IA×SA」→「IA × SA」）
    text = _CJK_SYM.sub(r"\1 \2", text)
    text = _SYM_CJK.sub(r"\1 \2", text)
    return _WS.sub(" ", text).strip()[:limit]


# 便于抽样核对：函数对同一输入稳定，故同义组判定 = 去掉空白后相等。
def group_key(raw: str) -> str:
    """同义判定键：去掉全部空白（用于统计库内残留的同义分裂组）。"""
    return _WS.sub("", str(raw or ""))
