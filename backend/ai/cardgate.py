"""知识卡片「重复出卡」止血闸门（v2.9.4 / KNOW-014）。

背景（2026-09-24 实测，勿重复调查）：生成侧长期产出同一考点换措辞的重复卡，
全量去重清出 510 张（5011→4501）。本模块在**写库前**对每一批新卡做逐张判定：
确定性预筛（宁可多召回）→ LLM 确认（mergeable）→ 丢弃信息较少的一张。

对外唯一入口：`filter_new_cards(cards, chapter_id, existing_fronts=None) -> (kept, dropped)`。

判定口径（v2.9.4，来自全量去重管线实测，勿再自创阈值）：
- 预筛只负责「宁可多召回」，**判重交给 LLM**；任一命中即进入 LLM 确认：
  * R1 字符二元组 Jaccard ≥ 0.45（仅中日韩字符；拉丁字符由 R2/R4 单独处理，
        避免跨文种稀释）
  * R2 词元 Jaccard ≥ 0.60（拉丁词 [A-Za-z]{2,} + CJK 2-gram）
  * R3 字袋 Jaccard ≥ 0.70（仅双方 front 归一后长度 ≤ 30 的短问句）
  * R4 共享稀有拉丁 token：双方都含同一长度 ≥2 的拉丁 token，且该 token 在
        本章出现次数 2..40（df 稀有），且双方 front 归一后长度 ≤ 60 —— 不加任何
        相似度门槛（「BRD 的全称…」/「BRD 是什么的缩写…」就是靠这条召回）。
        **下界 2 是必须的**：候选对自身就是 df=2 的最小情形（本章再无第三张卡
        用到该 token），下界写成 3 会把这类卡整类漏掉（2026-09-24 真机实测复现）。
  * R5 前置术语相同：归一后去掉开头「的/了/吗/呢/是」，取前 4 字作为 head；
        head 相同且该 head 在本章 df 2..40（下界同为 2，理由同 R4）
- LLM 确认口径：只有「同一考点的同一件事、答案可无损合并」才 mergeable=true；
  同模板不同主体 / 数字或阈值不同 / 定义 vs 误区 vs 示例 vs 步骤 一律 false。
- LLM 失败/超时 → 一律保留（绝不误删），审计日志记 gate_degraded=true。

范围边界：只过滤**新插入**的卡，不删除库中已有卡（已有卡的合并由离线
`scripts/merge_duplicate_cards.py` 负责）。当新卡命中已有卡且信息更全时，
保留新卡并记审计（供离线合并参考），不在此处删已有卡。
"""
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ai import agents
from ai.cardtext import normalize_label

TZ8 = timezone(timedelta(hours=8))

# —— 预筛阈值（勿再自创）——
R1_BIGRAM_JACCARD = 0.45
R2_TOKEN_JACCARD = 0.60
R3_BAG_JACCARD = 0.70
R3_MAX_LEN = 30
R4_LATIN_DF_MIN, R4_LATIN_DF_MAX = 2, 40
R4_MAX_LEN = 60
R5_HEAD_LEN = 4
R5_DF_MIN, R5_DF_MAX = 2, 40
_STRIP_PREFIX = "的了吗呢是"

_CJK = r"㐀-䶿一-鿿豈-﫿぀-ヿ가-힯"
_CJK_RE = re.compile(f"[{_CJK}]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z]{2,}")


def _now() -> str:
    return datetime.now(TZ8).isoformat(timespec="seconds")


def _cjk_only(s: str) -> str:
    return "".join(_CJK_RE.findall(s or ""))


def _bigrams(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _set_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _bag_jaccard(a: str, b: str) -> float:
    ca, cb = Counter(a), Counter(b)
    inter = sum((ca & cb).values())
    union = sum((ca | cb).values())
    return inter / union if union else 0.0


def _latin_tokens(s: str) -> set:
    return set(_LATIN_TOKEN_RE.findall(s or ""))


def _head(norm: str) -> str:
    """R5 前置术语：去开头「的/了/吗/呢/是」，取前 4 个中日韩字符。"""
    s = (norm or "").strip()
    while s and s[0] in _STRIP_PREFIX:
        s = s[1:]
    cjk = _cjk_only(s)
    return cjk[:R5_HEAD_LEN] if len(cjk) >= R5_HEAD_LEN else ""


def _features(norm_front: str) -> dict:
    cjk = _cjk_only(norm_front)
    return {
        "norm": norm_front,
        "cjk": cjk,
        "bigrams": _bigrams(cjk),
        "tokens": _latin_tokens(norm_front) | _bigrams(cjk),
        "latin": _latin_tokens(norm_front),
        "head": _head(norm_front),
        "len": len(norm_front),
    }


def _corpus_df(norms: list[str]) -> tuple[Counter, Counter]:
    """本章 df：稀有拉丁 token 出现次数、前置术语 head 出现次数（按去重后的卡计）。"""
    latin_df: Counter = Counter()
    head_df: Counter = Counter()
    for n in norms:
        for tok in _latin_tokens(n):
            latin_df[tok] += 1
        head = _head(n)
        if head:
            head_df[head] += 1
    return latin_df, head_df


def _rule_hit(a: dict, b: dict, latin_df: Counter, head_df: Counter) -> str | None:
    if _set_jaccard(a["bigrams"], b["bigrams"]) >= R1_BIGRAM_JACCARD:
        return "R1"
    if _set_jaccard(a["tokens"], b["tokens"]) >= R2_TOKEN_JACCARD:
        return "R2"
    if a["len"] <= R3_MAX_LEN and b["len"] <= R3_MAX_LEN \
            and _bag_jaccard(a["cjk"], b["cjk"]) >= R3_BAG_JACCARD:
        return "R3"
    if a["len"] <= R4_MAX_LEN and b["len"] <= R4_MAX_LEN:
        for tok in (a["latin"] & b["latin"]):
            if R4_LATIN_DF_MIN <= latin_df.get(tok, 0) <= R4_LATIN_DF_MAX:
                return "R4"
    if a["head"] and a["head"] == b["head"] \
            and R5_DF_MIN <= head_df.get(a["head"], 0) <= R5_DF_MAX:
        return "R5"
    return None


def _info_score(front: str, back: str) -> tuple[int, int]:
    """信息量：字母数字字符数 → back 长度；值越大越「全」。"""
    alnum = len(re.findall(r"[A-Za-z0-9]", f"{front or ''}{back or ''}"))
    return (alnum, len(back or ""))


def _audit(record: dict) -> None:
    """把被丢卡 / 降级事件追加到 instance/logs/card_gate.jsonl；任何异常吞掉。"""
    try:
        path = os.environ.get("CARD_GATE_LOG") or str(
            Path(__file__).resolve().parents[2] / "instance" / "logs" / "card_gate.jsonl")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _load_existing_fronts(chapter_id: str) -> list[str]:
    """existing_fronts 缺省时从库读同章已有卡正面；无 Flask 上下文则回退空。"""
    try:
        from data.db import get_db
        con = get_db()
        return [r["front"] for r in con.execute(
            "SELECT front FROM knowledge_cards WHERE chapter_id=?", (chapter_id,)).fetchall()]
    except Exception:
        return []


def filter_new_cards(cards: list[dict], chapter_id: str, existing_fronts=None) -> tuple[list, list]:
    """逐张过滤新卡，返回 (kept, dropped)。绝不抛错：LLM 失败降级为全部保留。"""
    if existing_fronts is None:
        existing_fronts = _load_existing_fronts(chapter_id)

    batch = []
    for c in cards or []:
        c = dict(c or {})
        c["front"] = str(c.get("front") or "").strip()
        c["back"] = str(c.get("back") or "").strip()
        batch.append(c)

    # 本章 df：已有卡 + 本批全部卡（插入前口径）
    corpus_norms = [normalize_label(f) for f in existing_fronts] + \
                   [normalize_label(c["front"]) for c in batch]
    latin_df, head_df = _corpus_df(corpus_norms)

    # 匹配池：已有卡在前、本批已保留卡在后
    existing_pool = [{"front": f, "back": "", "_feat": _features(normalize_label(f))}
                     for f in existing_fronts]
    kept: list[dict] = []
    dropped: list[dict] = []

    def _entry(c: dict, feat: dict) -> dict:
        e = dict(c)
        e["_feat"] = feat
        return e

    for c in batch:
        if not c["front"] or not c["back"]:
            dropped.append(c)  # 空卡：不落库，不计审计
            continue
        feat = _features(normalize_label(c["front"]))

        match = None
        match_is_existing = False
        rule = None
        for is_existing, p in [(True, e) for e in existing_pool] + [(False, k) for k in kept]:
            r = _rule_hit(feat, p["_feat"], latin_df, head_df)
            if r:
                match, match_is_existing, rule = p, is_existing, r
                break

        if match is None:
            kept.append(_entry(c, feat))
            continue

        # 待定 → LLM 确认（失败/超时一律保留）
        verdict = None
        try:
            verdict = agents.knowledge_dup_check(
                c["front"], c["back"], match["front"], match["back"] or None)
        except Exception:
            verdict = None
        if verdict is None:
            _audit({"event": "gate_degraded", "gate_degraded": True, "chapter_id": chapter_id,
                    "front": c["front"], "matched_front": match["front"], "rule": rule,
                    "reason": "LLM 失败或超时，一律保留", "created_at": _now()})
            kept.append(_entry(c, feat))
            continue

        if not verdict.get("mergeable"):
            kept.append(_entry(c, feat))
            continue

        # mergeable=true → 丢弃信息较少的那张，保留更全的
        if match_is_existing:
            # 命中已有库卡：闸门只过滤新卡，不删已有卡 → 一律丢弃新卡（止血）
            dropped.append(c)
            _audit({"event": "card_dropped", "chapter_id": chapter_id,
                    "front": c["front"], "back": c["back"], "matched_front": match["front"],
                    "rule": rule, "reason": verdict.get("reason", ""),
                    "created_at": _now()})
            continue

        # 命中本批已保留卡：比较信息量，保留更全的那张
        new_score = _info_score(c["front"], c["back"])
        match_score = _info_score(match["front"], match["back"])
        if new_score > match_score:
            # 新卡更全 → 替换：丢旧批卡、保留新卡
            kept.remove(match)
            kept.append(_entry(c, feat))
            dropped.append({k: v for k, v in match.items() if k != "_feat"})
            _audit({"event": "card_dropped", "chapter_id": chapter_id,
                    "front": match["front"], "back": match["back"],
                    "rule": rule, "reason": verdict.get("reason", ""),
                    "created_at": _now()})
        else:
            dropped.append(c)
            _audit({"event": "card_dropped", "chapter_id": chapter_id,
                    "front": c["front"], "back": c["back"],
                    "rule": rule, "reason": verdict.get("reason", ""),
                    "created_at": _now()})

    out_kept = [{k: v for k, v in x.items() if k != "_feat"} for x in kept]
    return out_kept, dropped
