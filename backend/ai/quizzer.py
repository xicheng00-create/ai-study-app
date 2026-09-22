"""出题（QUIZZER）：DeepSeek 生成草稿题，失败降级到模板题（L2）。

百分制评分模型（QUIZ-005）：教师测评固定 20 道选择题/是非题，每题 5 分，合计 100 分，
彻底取消问答题（essay）。POINTS 保留 essay=10 仅用于兼容库里旧题数据。

自主练习（REQ-PRACTICE-001）自 v1.16.0 起改为：最多 5 道 choice/bool、基于章节资料、
难度 hard、同学生跨会话不重复；不再强制 20 道/100 分，LLM 真返空时返回空列表（不硬塞通用模板）。
"""
import hashlib
import json
import re

from data.db import get_db

from ai import agents
from ai.prompts import QUIZZER_SYSTEM

# 题型满分（QUIZ-005，选择/是非 5；essay=10 仅保留以兼容库里旧题数据，不再出 essay）
POINTS = {"choice": 5, "bool": 5, "essay": 10}

# 100 分预设组合（QUIZ-005）：固定 20 道 choice/bool，严禁含 essay
PRESETS = {
    "20c": {"choice": 20},
    "20b": {"bool": 20},
}

_TYPE_LABEL = {"choice": "选择题", "bool": "是非题", "essay": "问答题"}


# 出题上限：单次自主练习最多 10 道（正常 5 道）
MAX_PRACTICE_QUESTIONS = 10

MAX_SOURCE_CARDS = 50          # 出题送入模型的知识卡片上限（题源=卡片，v2.7.4）

def default_config() -> dict:
    return dict(PRESETS["20c"])


def config_total(config: dict) -> int:
    """按题型分值计算组合总分（用于校验=100）。"""
    return sum(POINTS[t] * int(config.get(t) or 0) for t in POINTS)


def validate_config(config) -> dict:
    """归一化并校验组合；只接受 choice/bool（essay 已取消），非法返回空 dict。"""
    if not isinstance(config, dict):
        return {}
    cfg = {}
    for t in ("choice", "bool"):
        n = config.get(t)
        if n is None:
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            return {}
        if n < 0:
            return {}
        if n:
            cfg[t] = n
    return cfg


def _spec_text(config: dict) -> str:
    parts = [f"{int(config.get(t) or 0)} 道{_TYPE_LABEL[t]}" for t in ("choice", "bool") if config.get(t)]
    return "共 " + " + ".join(parts) + "（各 5 分，合计 100 分）"


def _dedup(qs: list[dict]) -> list[dict]:
    """按 content 去重，保留首次出现的题（出题不重复）。"""
    seen = set()
    out = []
    for q in qs:
        c = q.get("content", "")
        if c in seen:
            continue
        seen.add(c)
        out.append(q)
    return out


def _enforce_config(qs: list[dict], config: dict) -> list[dict]:
    """按 config 裁剪题目数量，保证组合恰好 100 分且题干不重复。

    不足部分由 generate_questions 向模型补发补足；仍不足就到此为止（不再用模板兜底）。
    """
    out = []
    seen: set[str] = set()
    for t in POINTS:
        n = int(config.get(t) or 0)
        pool = [q for q in qs if q.get("type") == t]
        pi = 0
        for _ in range(n):
            while pi < len(pool) and pool[pi].get("content") in seen:
                pi += 1
            if pi < len(pool):
                item = pool[pi]
                pi += 1
            else:
                # 题库不足即止：不再用通用模板凑数（模板题不来自知识卡片，违反「题源=卡片」铁律）
                break
            seen.add(item.get("content", ""))
            out.append(item)
    return out


def _missing(qs: list[dict], config: dict) -> dict:
    """统计各题型还缺几道（DeepSeek 生成数不足部分）。"""
    missing = {}
    for t in POINTS:
        n = int(config.get(t) or 0)
        have = sum(1 for q in qs if q.get("type") == t)
        if have < n:
            missing[t] = n - have
    return missing


def _retrieve_cards(chapter_ids: list[str], per_sub: int = 3,
                    max_cards: int = MAX_SOURCE_CARDS) -> list[dict]:
    """取章节知识卡片作为**唯一题源**（v2.7.4 教研定调）。

    与旧 `_retrieve_chunks`（资料切片 RAG）的区别：资料原文不再入题，
    杜绝「不基于卡片、直接从资料出题」。按 sub_concept 轮转取卡，避免热门知识点挤掉其他。
    """
    con = get_db()
    rows: list[dict] = []
    for cid in chapter_ids:
        rows.extend(dict(r) for r in con.execute(
            "SELECT id, chapter_id, sub_concept, front, back FROM knowledge_cards"
            " WHERE chapter_id=? ORDER BY sub_concept, created_at", (cid,)).fetchall())
    if not rows:
        return []
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault((r.get("sub_concept") or "").strip() or "未归类", []).append(r)
    out: list[dict] = []
    for round_no in range(max(1, per_sub)):
        for key in sorted(groups):
            bucket = groups[key]
            if round_no < len(bucket) and len(out) < max_cards:
                out.append(bucket[round_no])
        if len(out) >= max_cards:
            break
    return out[:max_cards]


def _cards_text(cards: list[dict]) -> str:
    """卡片正文拼成题源文本（含 sub_concept，便于模型按知识点分布出题）。"""
    if not cards:
        return "（该范围暂无知识卡片，不得出题）"
    return "\n".join(
        f"- [{c.get('sub_concept') or '未归类'}] 问：{(c.get('front') or '')[:120]}"
        f" / 答：{(c.get('back') or '')[:220]}"
        for c in cards
    )


def has_cards(chapter_ids: list[str]) -> bool:
    """该范围是否存在知识卡片（无卡则不得出题）。"""
    return bool(_retrieve_cards(chapter_ids, per_sub=1, max_cards=1))


def _content_hash(content: str) -> str:
    """题干规范化 hash（去空格/标点/大小写）：同学生跨会话去重与变体判定基准。"""
    norm = re.sub(r"[\W_]+", "", (content or "")).lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _norm_practice(raw: dict) -> dict:
    """练习题目原始 dict 归一化：确保 type 合法、options/answer 为预期结构。"""
    qtype = raw.get("type", "choice")
    if qtype not in POINTS:
        qtype = "choice"
    options = raw.get("options") or []
    if isinstance(options, str):
        options = [options]
    answer = raw.get("answer", raw.get("answer_key", ""))
    if isinstance(answer, (int, float)):
        answer = str(answer)
    return {
        "type": qtype,
        "content": raw.get("content", ""),
        "options": [str(o) for o in options],
        "answer": str(answer),
        "reason": raw.get("reason", ""),
        "sub_concept": raw.get("sub_concept", ""),
    }


def _cap_to_max(qs: list[dict], exclude_hashes: set | None = None,
                exclude_sub_concepts: set | None = None,
                max_q: int = 5) -> list[dict]:
    """优先不同子概念；可用子概念不足时才补同概念变体。"""
    exclude_hashes = exclude_hashes or set()
    exclude_sub_concepts = exclude_sub_concepts or set()
    seen_hashes: set[str] = set()
    candidates = []
    for q in qs:
        if q.get("type") not in ("choice", "bool"):
            continue
        h = _content_hash(q.get("content", ""))
        sub = (q.get("sub_concept") or "").strip()
        if sub and sub in exclude_sub_concepts:
            continue
        if h and h not in seen_hashes and h not in exclude_hashes:
            seen_hashes.add(h)
            candidates.append(q)
    out, seen_sub = [], set()
    for q in candidates:
        sub = (q.get("sub_concept") or "").strip()
        if sub and sub not in seen_sub:
            out.append(q); seen_sub.add(sub)
            if len(out) >= max_q:
                return out
    for q in candidates:
        if q not in out:
            out.append(q)
            if len(out) >= max_q:
                break
    return out


def _avoid_block(exclude_contents: list[str]) -> str:
    """注入提示词：同学生历史已出题干清单（要求避免重复 + 基于资料衍生变体）。"""
    if not exclude_contents:
        return ""
    lines = "\n".join(f"- {c[:120]}" for c in exclude_contents[:20])
    return (
        "\n\n【同学生历史已出题干（避免重复）】以下题干该学生之前已出过，"
        "不得生成相同题干；可基于章节资料改问法/角度/场景衍生变体（考点同、题干不同不算重复）：\n"
        + lines
    )


def _practice_system(chapter_ids: list[str], sub_concepts: str, cards_txt: str,
                     exclude_contents: list[str] | None = None,
                     exclude_sub_concepts: set | None = None, count: int = 5) -> str:
    spec = (f"出 {count} 道题，每题来自一个【不同】的子概念（知识点）——从知识卡片里挑 {count} 个不同的知识点各出一题；"
            f"只允许选择题（choice）和是非题（bool），难度 hard")
    excl = ""
    if exclude_sub_concepts:
        excl = ("\n\n【必须遵守 · 跨会话知识点不重复】以下子概念该学生【已练过】，本次【禁止】再出这些子概念。"
                "请从卡片中其它子概念里，尽量挑【不同】且【不在清单内】的子概念出题，凑满 " + str(count)
                + " 道：\n- " + "\n- ".join(sorted(exclude_sub_concepts)))
    return QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec,
        source_cards=cards_txt[:14000],
        difficulty="hard",
    ) + _avoid_block(exclude_contents or []) + excl


def generate_practice_questions(chapter_ids: list[str], sub_concepts: str = "",
                                exclude_contents: list[str] | None = None,
                                exclude_sub_concepts: set | None = None, count: int = 5) -> list[dict]:
    """自主练习出题（difficulty=hard，最多 5 道 choice/bool，**题源=知识卡片**，同学生跨会话不重复）。

    v2.7.4 起不再检索资料切片：卡片是该范围内唯一可考内容。
    无卡片或模型出不出题时返回空列表，由调用方提示，不再硬塞通用模板。
    """
    try:
        count = max(5, min(int(count or 5), MAX_PRACTICE_QUESTIONS))
    except (TypeError, ValueError):
        count = 5
    cards = _retrieve_cards(chapter_ids)
    if not cards:
        return []  # 无卡片＝无可考内容：不调模型、不出题
    cards_txt = _cards_text(cards)
    exclude_contents = exclude_contents or []
    exclude_hashes = {_content_hash(c) for c in exclude_contents}

    exclude_sub_concepts = exclude_sub_concepts or set()
    system = _practice_system(chapter_ids, sub_concepts, cards_txt, exclude_contents, exclude_sub_concepts, count)
    qs = [_norm_practice(q) for q in (agents.quizzer_generate(system) or [])]
    if not qs:
        return []
    cap = _cap_to_max(qs, exclude_hashes=exclude_hashes,
                      exclude_sub_concepts=exclude_sub_concepts, max_q=count)
    # LLM 常聚在热门子概念；排除已练后需重试逼它挖更多【不同】子概念，凑满 count。
    for _ in range(2):
        if len(cap) >= count:
            break
        retry = _practice_system(chapter_ids, sub_concepts, cards_txt, exclude_contents,
                                 exclude_sub_concepts, count)
        extra = [_norm_practice(q) for q in (agents.quizzer_generate(retry) or [])]
        cap = _cap_to_max(cap + extra, exclude_hashes=exclude_hashes,
                          exclude_sub_concepts=exclude_sub_concepts, max_q=count)
    return cap


def generate_questions(chapter_ids: list[str], sub_concepts: str = "", spec: str = "",
                       config: dict | None = None, difficulty: str = "normal") -> list[dict]:
    """测评出题：题源=知识卡片（v2.7.4 起不再检索资料切片）。

    该范围无卡片、或模型据卡片出不出题时一律返回 []（由调用方给出明确提示），
    不再用通用模板兜底——模板题不来自卡片，违反「题源=卡片」铁律。
    """
    cfg = config or default_config()
    spec_text = spec or _spec_text(cfg)
    cards = _retrieve_cards(chapter_ids)
    if not cards:
        return []  # 无卡片＝无可考内容：不调模型、不出题
    cards_txt = _cards_text(cards)

    system = QUIZZER_SYSTEM.format(
        chapter_ids=",".join(chapter_ids),
        sub_concepts=sub_concepts or "不限",
        spec=spec_text,
        source_cards=cards_txt[:14000],
        difficulty=difficulty,
    )
    qs = agents.quizzer_generate(system)
    if not qs:
        return []

    # 生成数不足：向 DeepSeek 补发一次补足缺口题型（仍限定卡片题源）
    missing = _missing(qs, cfg)
    if missing:
        fill_spec = "、".join(f"{n} 道{_TYPE_LABEL[t]}" for t, n in missing.items())
        fill_system = QUIZZER_SYSTEM.format(
            chapter_ids=",".join(chapter_ids),
            sub_concepts=sub_concepts or "不限",
            spec=fill_spec,
            source_cards=cards_txt[:14000],
            difficulty=difficulty,
        )
        extra = agents.quizzer_generate(fill_system)
        if extra:
            qs = qs + extra
    return _dedup(_enforce_config(qs, cfg))


def norm_question(raw: dict, chapter_id: str) -> dict:
    """规范化为入库结构（type/content/options/answer_key/points）。"""
    qtype = raw.get("type", "choice")
    if qtype not in ("choice", "bool", "essay"):
        qtype = "choice"
    options = raw.get("options") or []
    if isinstance(options, str):
        options = [options]
    answer = raw.get("answer", raw.get("answer_key", ""))
    if isinstance(answer, (int, float)):
        answer = str(answer)
    return {
        "type": qtype,
        "content": raw.get("content", ""),
        "options": json.dumps([str(o) for o in options], ensure_ascii=False),
        "answer_key": str(answer),
        "sub_concept": raw.get("sub_concept", ""),
        "reason": raw.get("reason", ""),
        "points": POINTS[qtype],
    }
