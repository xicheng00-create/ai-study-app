#!/usr/bin/env python3
"""知识卡片重做：按切片逐片细粒度抽取，做到考点全覆盖、卡片↔切片严格绑定。

设计要点（针对「覆盖率不足 / 精细度不够」的根因）：
1. 切片分批而不是整章一次性投喂 —— 旧实现只喂 ~17 个切片、每片截断 300 字，
   模型物理上看不到全章内容；本脚本把该章**全部切片**按顺序分成若干「片组」，
   逐组抽取，保证每一段原文都被读过。
2. 片组边界尊重课件小标题 —— 课件（教案）的切片按 `#/##/###` 标题切分，
   于是每个片组天然对应一个课件小节，卡片 sub_concept 落在小节上。
3. 每张卡片记录 source_chunk_id —— 卡片与「AI 智能对话切片」一一绑定，可回溯原文。
4. 细粒度要求写进提示词：一个考点一张卡，数字/步骤/术语/易混概念必须单列。
5. 复习状态继承：仅按 front 归一化精确匹配继承，不做主题级猜测，避免误判已掌握。

用法：
    python3 scripts/rebuild_cards.py --all
    python3 scripts/rebuild_cards.py --chapter 2d91a36d
    python3 scripts/rebuild_cards.py --all --dry-run      # 只生成不改库
"""
import argparse
import concurrent.futures as futures
import json
import os
import re
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
DB = BASE / "instance" / "aistudy.sqlite3"
OUTDIR = BASE / "backups" / "cards-rebuild"

# 片组参数
BATCH_CHUNKS = 5          # 一份普通资料每 5 个切片成一组
MAX_PIECES = 64           # 每章最多片组数（教案小节优先）
PER_PIECE_CAP = 16        # 单片组卡片数上限（防止模型跑飞）
MAX_CHUNK_CHARS = 700     # 单片送模型的最大字数
WORKERS = 4
TIMEOUT = 180

# 全课程共用素材：只在处理这些资料时启用「只抽本 Session 内容」的强护栏。
# 其余资料属于本 Session 专属，应穷尽抽取——护栏过度使用会把本课考点误判成其它周次而丢弃
# （2026-09-19 实测：W1S2 的行业报告被过滤掉「人形机器人/AI 医疗融资/虚拟电厂」等随堂测考点）。
SHARED_MATERIALS = ("行业黑话", "术语表", "黑话大全")


def load_env(path: Path) -> dict:
    env = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("DEEPSEEK_")})
    return env


ENV = load_env(BASE / ".env")

SYSTEM_TMPL = """你是「AI 学习小组」的资深教研老师，负责把课件原文拆成**应试级**知识卡片。
严格输出 JSON，不要任何多余文字。

【本 Session 学习目标】{goal}
【本 Session 概念标签】{tags}
【本片组的课件来源】{source}
【片组内容】
{content}

输出格式：
{{"cards":[{{"front":"考点（问句或知识点名）","back":"确切答案 + 一句解析 + 一句示例","sub_concept":"该考点所属小节/主题"}}]}}

硬性要求：
1. {relevance_rule}
2. **穷尽本片组里属于本 Session 的全部可考点**，包括：概念定义、数字与指标（原样保留数字）、
   流程步骤（逐步列出）、术语英文名、技术选型理由、易混概念的区别、常见误区与纠正、案例结论。
3. **一个考点一张卡片**。禁止把多个知识点合并成一张「大框架」卡片；
   禁止写「主要包含以下几方面」这类笼统概括。
4. 凡是能出选择题的细节（数字、专有名词、模块名、顺序、比例、阈值、年份、倍数）都必须单独成卡。
5. sub_concept 用 4-12 字的小节/主题名；同一小节下的多张卡片共用同一 sub_concept。
6. back 必须是确切答案，不允许「参考课件」这类空话；资料没写的绝不编造。
7. 本片组预计 {n} 张卡片左右。
"""

# 强护栏只用于「全课程共用素材」；本 Session 专属资料必须穷尽抽取，
# 否则模型会把本课考点（如行业报告里的具体数字）误判成其它周次而丢弃。
RULE_STRICT = """**本片组来自全课程共用素材**（内含多个周次的词条）。只抽取属于本 Session 的内容：
   凡是明显服务于**其它周次**、不在上面学习目标/概念标签范围内的知识点，一律跳过、不要出卡。"""
RULE_NORMAL = """本片组是**本 Session 专属资料**，其中的知识点默认都属于本 Session，必须穷尽抽取，
   不得以「不是本课重点」为由跳过任何一条可考点。"""


def norm_front(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "")).lower()


def _log_usage(model: str, usage, feature: str = "") -> None:
    """把一次成功的 LLM 调用追加到 app-usage JSONL，供 Token 账单看板精确归因。

    背景（2026-09-20）：本脚本与 audit_alignment.py 直连 DeepSeek 官方 API 且
    不写任何用量日志，导致 09-18/09-19 账单里 26% 的请求落进「无逐次记录」桶
    （对账哨兵报警）。这里补上逐次记账，与 backend/ai/usage_log.py 同格式。
    任何异常都吞掉，绝不影响主流程。
    """
    try:
        from datetime import datetime, timedelta, timezone
        path = (ENV.get("LLM_USAGE_LOG") or os.environ.get("LLM_USAGE_LOG")
                or os.path.expanduser("~/.hermes/app-usage/aistudy.jsonl"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        u = usage or {}
        rec = {
            "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "model": str(model or "unknown"),
            "feature": str(feature or os.path.basename(sys.argv[0] or "") or "offline-script"),
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "prompt_cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def call_llm_json(system: str) -> dict:
    """请求模型并解析出 JSON 对象（容错），供卡片抽取与审计复用。"""
    import requests
    key = ENV.get("DEEPSEEK_API_KEY", "")
    base = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = ENV.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "system", "content": system}],
              "temperature": 0.4},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    _log_usage(model, data.get("usage"))
    return parse_json_obj(data["choices"][0]["message"]["content"])


def call_llm(system: str) -> list[dict]:
    return call_llm_json(system).get("cards") or []


def parse_json_obj(text: str) -> dict:
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        data = json.loads(t)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        s, e = t.find("{"), t.rfind("}")
        if s >= 0 and e > s:
            try:
                data = json.loads(t[s:e + 1])
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def parse_cards(text: str) -> list[dict]:
    return [c for c in (parse_json_obj(text).get("cards") or []) if isinstance(c, dict)]


HEAD_RE = re.compile(r"^\s{0,3}#{1,4}\s+\S")
# 标题行按行匹配（切片是定长窗口，标题常落在切片中部而非开头）
HEAD_LINE_RE = re.compile(r"(?m)^\s{0,3}#{1,4}\s+(.+?)\s*$")


def split_lesson(chunks: list) -> list[dict]:
    """把教案（课件.md）按小节标题拆成片组。

    切片是定长窗口，标题几乎不会正好落在切片开头；若整份教案当成一个片组投喂，
    模型一次只能输出有限张卡片，最重要的教案反而被截断。这里先把切片拼回全文、
    按 `#` 标题定位小节区间，再取与之相交的切片，从而得到「小节 ↔ 切片」的精确片组。
    """
    if not chunks:
        return []
    spans: list[tuple[int, int]] = []
    pos = 0
    for c in chunks:
        text = c["text"] or ""
        spans.append((pos, pos + len(text)))
        pos += len(text) + 1
    full = "\n".join(c["text"] or "" for c in chunks)

    heads = [(m.start(), m.group(1).strip()) for m in HEAD_LINE_RE.finditer(full)]
    if not heads:
        return [_mk("教案", chunks)]
    if heads[0][0] > 0:  # 前言归入第一个小节
        heads.insert(0, (0, "教案·导语"))
    bounds = [h[0] for h in heads] + [len(full)]

    out: list[dict] = []
    for i, (start, title) in enumerate(heads):
        end = bounds[i + 1]
        if end - start < 60:          # 过短的小节（如纯标题行）直接跳过
            continue
        picked = [c for (cs, ce), c in zip(spans, chunks) if cs < end and ce > start]
        if picked:
            out.append(_mk(f"教案·{title}", picked))
    return out or [_mk("教案", chunks)]


def session_ctx(con, chapter_id: str) -> tuple[str, str]:
    """取该章所属 Session 的学习目标与概念标签，用于「只抽本 Session 内容」护栏。"""
    row = con.execute(
        "SELECT goal, concept_tags FROM sessions WHERE chapter_ids LIKE ?", (f"%{chapter_id}%",)
    ).fetchone()
    if row is None:
        return "（未登记学习目标）", "（无）"
    try:
        tags = json.loads(row["concept_tags"] or "[]")
    except json.JSONDecodeError:
        tags = []
    return (row["goal"] or "（未登记学习目标）"), ("、".join(tags) or "（无）")


def build_pieces(con, chapter_id: str) -> list[dict]:
    """把该章全部切片切成片组：课件（教案）按标题分节，其余资料按序分批。"""
    mats = con.execute(
        "SELECT id, original_name, created_at, parse_status FROM materials"
        " WHERE chapter_id=? AND is_deleted=0 ORDER BY created_at", (chapter_id,)
    ).fetchall()
    lesson_pieces: list[dict] = []
    other_pieces: list[dict] = []
    for m in mats:
        chunks = con.execute(
            "SELECT id, chunk_idx, text FROM chunks WHERE material_id=? ORDER BY chunk_idx",
            (m["id"],),
        ).fetchall()
        if not chunks:
            continue
        is_lesson = "课件（教案）" in m["original_name"]
        if is_lesson:
            lesson_pieces.extend(split_lesson(chunks))
        else:
            for i in range(0, len(chunks), BATCH_CHUNKS):
                grp = chunks[i:i + BATCH_CHUNKS]
                if grp:
                    other_pieces.append(_mk(m["original_name"], grp))
    pieces = lesson_pieces + other_pieces
    # 片组过小时合并到前一组，避免碎片化调用
    merged: list[dict] = []
    for p in pieces:
        total = sum(len(c["text"] or "") for c in p["chunks"])
        if merged and total < 400:
            merged[-1]["chunks"].extend(p["chunks"])
            merged[-1]["source"] = merged[-1]["source"] if merged[-1]["source"] == p["source"] \
                else f"{merged[-1]['source']}、{p['source']}"
        else:
            merged.append(p)
    return merged[:MAX_PIECES]


def _mk(source: str, chunks: list) -> dict:
    return {"source": source, "chunks": list(chunks)}


def gen_for_piece(job: tuple[dict, str, str]) -> tuple[dict, list[dict], str | None]:
    piece, goal, tags = job
    body = "\n---\n".join((c["text"] or "")[:MAX_CHUNK_CHARS] for c in piece["chunks"])
    n = max(4, min(14, len(body) // 500))
    shared = any(k in piece["source"] for k in SHARED_MATERIALS)
    rule = RULE_STRICT if shared else RULE_NORMAL
    fallback_sub = re.sub(r"^教案·", "", piece["source"])[:12] or "本节考点"
    try:
        cards = call_llm(SYSTEM_TMPL.format(source=piece["source"], content=body, goal=goal,
                                           tags=tags, n=n, relevance_rule=rule))
        out = []
        for c in cards[:PER_PIECE_CAP]:
            c["sub_concept"] = str(c.get("sub_concept") or "").strip()[:40] or fallback_sub
            out.append(c)
        return piece, out, None
    except Exception as e:  # noqa: BLE001
        return piece, [], str(e)


def _tokens(s: str) -> set:
    return set(re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,4}", s or ""))


def _digits(s: str) -> set:
    return set(re.findall(r"\d+", s or ""))


def is_near_dup(a_front: str, a_tokens: set, b_front: str, b_tokens: set) -> bool:
    """近似重复判定：词元 Jaccard ≥0.85 **且数字集合相同**。

    数字保护必不可少——「SWE-bench Verified 冠军」与「SWE-bench Pro 冠军」、
    「Phi-4」与「Command R7B」这类卡片词元高度重叠但考点完全不同，不能被合并。
    """
    if not a_tokens or not b_tokens:
        return False
    if _digits(a_front) != _digits(b_front):
        return False
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens) >= 0.85


def dedupe(cards: list[dict]) -> list[dict]:
    seen, kept = set(), []
    for c in cards:
        front = str(c.get("front") or "").strip()
        back = str(c.get("back") or "").strip()
        if not front or not back:
            continue
        key = norm_front(front)
        if len(key) < 4 or key in seen:
            continue
        toks = _tokens(front)
        if any(is_near_dup(front, toks, k["front"], k["_toks"]) for k in kept):
            continue
        seen.add(key)
        kept.append({"front": front, "back": back, "_toks": toks,
                     "sub_concept": str(c.get("sub_concept") or "").strip()[:40],
                     "source_chunk_id": c.get("source_chunk_id")})
    for c in kept:
        c.pop("_toks", None)
    return kept


def rebuild_chapter(con, chapter_id: str, name: str, dry: bool) -> dict:
    pieces = build_pieces(con, chapter_id)
    goal, tags = session_ctx(con, chapter_id)
    print(f"\n[{name}] 片组 {len(pieces)} 个，开始逐片抽取 ...", flush=True)
    raw: list[dict] = []
    jobs = [(p, goal, tags) for p in pieces]
    with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (piece, cards, err) in enumerate(
                ex.map(gen_for_piece, jobs), start=1):
            if err:
                print(f"   [{i}/{len(pieces)}] {piece['source'][:20]} 失败: {err}", flush=True)
                continue
            for c in cards:
                c["source_chunk_id"] = piece["chunks"][0]["id"]
            raw.extend(cards)
            print(f"   [{i}/{len(pieces)}] {piece['source'][:22]:<24} +{len(cards):2d} 卡", flush=True)

    cards = dedupe(raw)
    stats = {"chapter": name, "chapter_id": chapter_id, "pieces": len(pieces),
             "raw": len(raw), "cards": len(cards),
             "sub_concepts": len({c["sub_concept"] for c in cards if c["sub_concept"]})}

    OUTDIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (OUTDIR / f"{chapter_id[:8]}-{stamp}.json").write_text(
        json.dumps(stats | {"cards": cards}, ensure_ascii=False, indent=2), encoding="utf-8")

    if dry:
        return stats

    # 复习状态继承：仅按 front 归一化精确匹配（不做主题级猜测，避免误判已掌握）
    old = con.execute(
        "SELECT id, front FROM knowledge_cards WHERE chapter_id=?", (chapter_id,)).fetchall()
    old_ids = [r["id"] for r in old]
    front_by_old = {r["id"]: r["front"] for r in old}
    revs_by_norm: dict[str, list] = {}
    revs_total = 0
    if old_ids:
        ph = ",".join("?" * len(old_ids))
        revs = con.execute(
            f"SELECT card_id, user_id, learn_count, interval_days, next_review_at, status, last_review_at"
            f" FROM knowledge_reviews WHERE card_id IN ({ph})", old_ids).fetchall()
        revs_total = len(revs)
        for r in revs:
            revs_by_norm.setdefault(norm_front(front_by_old.get(r["card_id"], "")), []).append(r)

    # FK 级联默认关闭，必须显式清理旧卡的复习记录，避免留下孤儿行
    if old_ids:
        ph = ",".join("?" * len(old_ids))
        con.execute(f"DELETE FROM knowledge_reviews WHERE card_id IN ({ph})", old_ids)
    con.execute("DELETE FROM knowledge_cards WHERE chapter_id=?", (chapter_id,))

    now = datetime.now(timezone.utc).isoformat()
    new_id_by_norm: dict[str, str] = {}
    for c in cards:
        cid = str(uuid.uuid4())
        new_id_by_norm.setdefault(norm_front(c["front"]), cid)
        con.execute(
            "INSERT OR IGNORE INTO knowledge_cards"
            " (id, chapter_id, sub_concept, front, back, source_chunk_id, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (cid, chapter_id, c["sub_concept"], c["front"], c["back"], c["source_chunk_id"], now),
        )
    carried = 0
    for nk, nid in new_id_by_norm.items():
        for r in revs_by_norm.get(nk, []):
            con.execute(
                "INSERT OR IGNORE INTO knowledge_reviews"
                " (id, card_id, user_id, learn_count, interval_days, next_review_at, status,"
                "  last_review_at, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), nid, r["user_id"], r["learn_count"], r["interval_days"],
                 r["next_review_at"], r["status"], r["last_review_at"], now),
            )
            carried += 1
    con.commit()
    stats["carried_reviews"] = carried
    stats["old_cards"] = len(old)
    stats["old_reviews"] = revs_total
    return stats


def dedupe_db(con) -> dict:
    """对库中已有卡片做近似去重：保留最早一张，复习态尽量迁移到保留卡。"""
    removed = moved = 0
    for ch in con.execute("SELECT id, name FROM chapters ORDER BY folder, order_no").fetchall():
        rows = con.execute(
            "SELECT id, front FROM knowledge_cards WHERE chapter_id=? ORDER BY rowid",
            (ch["id"],)).fetchall()
        kept: list[tuple[str, set, str]] = []
        drop: list[tuple[str, str]] = []
        for r in rows:
            front = r["front"] or ""
            toks = _tokens(front)
            hit = next((k for k in kept if is_near_dup(front, toks, k[0], k[1])), None)
            if hit:
                drop.append((r["id"], hit[2]))
            else:
                kept.append((front, toks, r["id"]))
        for old_id, new_id in drop:
            for rev in con.execute("SELECT * FROM knowledge_reviews WHERE card_id=?", (old_id,)).fetchall():
                exists = con.execute(
                    "SELECT 1 FROM knowledge_reviews WHERE card_id=? AND user_id=?",
                    (new_id, rev["user_id"])).fetchone()
                if exists:
                    con.execute("DELETE FROM knowledge_reviews WHERE id=?", (rev["id"],))
                else:
                    con.execute("UPDATE knowledge_reviews SET card_id=? WHERE id=?", (new_id, rev["id"]))
                    moved += 1
            con.execute("DELETE FROM knowledge_cards WHERE id=?", (old_id,))
            removed += 1
        print(f"  {ch['name']}: {len(rows)} → {len(kept)} 张（近似去重 {len(drop)}，复习态迁移 {moved}）")
    con.commit()
    return {"removed": removed, "moved": moved}


def _gap_tokens(s: str) -> list[str]:
    toks = re.findall(r"[A-Za-z]{3,}|[\u4e00-\u9fff]{2,4}", s or "")
    seen, out = set(), []
    for t in sorted(toks, key=len, reverse=True):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


GAP_TMPL = """你是「AI 学习小组」的资深教研老师。下面给出若干**随堂测试/教案中已出现、但现有知识卡片没有覆盖**的考点，
以及从本 Session 课件原文中检索到的相关片段。

请针对这些考点，从原文片段里找出依据，**逐条补出知识卡片**。
严格输出 JSON，不要任何多余文字。

【本 Session】{chapter}
【已有卡片数】{n}（这些卡已覆盖的考点不必重复出卡）

【待补考点 + 检索到的原文片段】
{blocks}

输出格式：
{{"cards":[{{"front":"考点（问句或知识点名）","back":"确切答案 + 一句解析","sub_concept":"所属主题","for":"它覆盖的那条待补考点原文"}}]}}

硬性要求：
1. **只写原文片段里有依据的内容**。若某条待补考点在片段里找不到任何依据，就不要为它出卡
   （宁缺勿造——编造答案是严重错误）。
2. 一个考点一张卡；能出选择题的细节（数字、专有名词、顺序、比例、阈值、年份）必须原样保留。
3. sub_concept 用 4-12 字的小节/主题名。
"""


def fill_gaps(con, report: Path) -> dict:
    """按审计报告里的未覆盖考点，从课件原文检索依据并补卡。

    这是「100% 覆盖考点」的最后一环：只补**审计确认未覆盖**的考点，
    并要求模型「原文找不到依据就不出卡」，避免为了凑覆盖而编造。
    """
    data = json.loads(report.read_text())
    added_total = 0
    report_rows = []
    for row in data.get("chapters", []):
        missed = [m for m in (row.get("missed") or []) if m]
        ch = con.execute("SELECT id FROM chapters WHERE name=?", (row["chapter"],)).fetchone()
        if not ch or not missed:
            continue
        cid = ch["id"]
        n = con.execute("SELECT count(*) FROM knowledge_cards WHERE chapter_id=?", (cid,)).fetchone()[0]
        blocks, bind = [], {}
        for t in missed:
            toks = _gap_tokens(t)[:6]
            if toks:
                where = " OR ".join(["text LIKE ?"] * len(toks))
                rows = con.execute(
                    f"SELECT id, text FROM chunks WHERE chapter_id=? AND ({where}) LIMIT 6",
                    (cid, *[f"%{k}%" for k in toks])).fetchall()
            else:
                rows = []
            bind[t] = rows[0]["id"] if rows else None
            src = "\n".join(f"    · {(r['text'] or '')[:500]}" for r in rows) or "    （课件原文中检索不到相关片段）"
            blocks.append(f"◎ 待补考点：{t}\n  原文片段：\n{src}")
        prompt = GAP_TMPL.format(chapter=row["chapter"], n=n, blocks="\n\n".join(blocks))
        try:
            got = call_llm(prompt)
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 补漏失败 {row['chapter']}: {e}")
            continue
        existing = {norm_front(r["front"]) for r in con.execute(
            "SELECT front FROM knowledge_cards WHERE chapter_id=?", (cid,))}
        added = 0
        new_ids: list[str] = []
        for c in got[:40]:
            front = str(c.get("front") or "").strip()
            back = str(c.get("back") or "").strip()
            if not front or not back or norm_front(front) in existing:
                continue
            new_id = str(uuid.uuid4())
            con.execute(
                "INSERT INTO knowledge_cards (id, chapter_id, sub_concept, front, back, source_chunk_id, created_at)"
                " VALUES (?,?,?,?,?,?,datetime('now'))",
                (new_id, cid, str(c.get("sub_concept") or "考点补漏")[:40], front, back, None))
            new_ids.append(new_id)
            existing.add(norm_front(front))
            added += 1
        # 绑片不能取「关键词 LIKE 命中的第一条」（会绑到含「AI」等泛词的无关切片），
        # 一律按卡片正反面与切片正文的词元重合度取最吻合者。
        _bind_by_content(con, new_ids)
        con.commit()
        added_total += added
        report_rows.append({"chapter": row["chapter"], "missed": len(missed), "added": added,
                            "no_source": [t for t, sid in bind.items() if sid is None]})
    return {"added": added_total, "chapters": report_rows}


def _overlap(a: set, b: set) -> int:
    return len(a & b)


def _bind_by_content(con, card_ids: list[str]) -> int:
    """按「卡片正面+背面」与切片正文的词元重合度，把卡片绑到最吻合的切片。"""
    reb = 0
    for cid in card_ids:
        r = con.execute("SELECT chapter_id, front, back, source_chunk_id FROM knowledge_cards WHERE id=?",
                        (cid,)).fetchone()
        if not r:
            continue
        want = _tokens(f"{r['front']} {r['back'] or ''}")
        best, best_n = None, 1  # 至少重合 2 个词元才改绑，避免噪声
        for c in con.execute("SELECT id, text FROM chunks WHERE chapter_id=?", (r["chapter_id"],)):
            score = _overlap(want, _tokens(c["text"] or ""))
            if score > best_n:
                best, best_n = c["id"], score
        if best and best != r["source_chunk_id"]:
            con.execute("UPDATE knowledge_cards SET source_chunk_id=? WHERE id=?", (best, cid))
            reb += 1
    return reb


# ---- 无卡切片补卡（orphan chunks）：切片↔卡片一一对应的最后一环 ----
ORPHAN_MIN_CHARS = 80     # 太短的切片无实质内容，不补卡
ORPHAN_CAP = 6            # 单切片卡片数上限
ORPHAN_MAX_CHARS = 1400   # 单切片送模型的最大字数


def _clean(text: str) -> str:
    """剔除水印/邮箱/重复片段，**保留同一条切片里的实质内容**。

    ⚠️ 血泪教训（2026-09-19）：早期版本只要切片里出现「教学监督邮箱：feedback@…」
    就整条丢弃，结果 W2S1 有 55 条切片被误杀——它们其实是「水印 + 真考点」混排
    （如「从优化工具效率转向重构创作模式」「移动互联网的逻辑陷阱」）。
    **水印是按词删的，不是按切片删的。**
    """
    t = text or ""
    # ① 先按行删 Markdown 表格分隔行 / 框线行（⚠️必须在压平换行之前，
    #    只删「分隔行」，表格数据行必须保留——血泪教训 2026-09-19：不删这些，
    #    下面的重复检测会把「厂商对比表 / 技术概念清单表」整条判成噪声丢掉，
    #    而那正是最典型的细碎考点）
    t = re.sub(r"(?m)^\s*\|?\s*:?-{2,}[\s:|-]*$", " ", t)
    t = re.sub(r"(?m)^[\s─━═│┌┐└┘├┤┬┴┼]+$", " ", t)
    # ② 行内噪声：邮箱 / 分隔线 / 页码 / 框线 / 长横线 / 圆点
    t = re.sub(r"(教学监督邮箱[:：]?\s*)?[A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", " ", t)
    t = re.sub(r"={3,}[^=]{0,80}?={3,}", " ", t)
    t = re.sub(r"\[第\d+页\]", " ", t)
    t = re.sub(r"[─━│┌┐└┘├┤┬┴┼═]+", " ", t)
    t = re.sub(r"[-—–=]{4,}", " ", t)
    t = re.sub(r"[•·▪●○]{2,}", " ", t)
    t = " ".join(t.split())
    # ③ 同一短语被清洗后仍反复出现 N 次（水印型）→ 只留一次
    #    阈值取 ≥6 次且重复单元 ≥16 字：太松会误杀代码片段
    #    （2026-09-19：「current_state.」在 Redis 会话代码里出现 4 次，曾被误判为水印）
    for unit in (16, 24, 32):
        out, i = [], 0
        while i < len(t):
            seg = t[i:i + unit]
            j = i + unit
            n = 1
            while t[j:j + unit] == seg:
                j += unit
                n += 1
            out.append(seg)
            i = j
        t = "".join(out)
    return " ".join(t.split())


def _max_repeat(t: str) -> int:
    """清洗后文本里 12 字片段的最大出现次数（判真噪声用）。"""
    seg = t[:1400]
    cnt: dict[str, int] = {}
    for i in range(0, max(1, len(seg) - 12), 6):
        s = seg[i:i + 12]
        cnt[s] = cnt.get(s, 0) + 1
    return max(cnt.values()) if cnt else 0


def _boiler(text: str) -> bool:
    """判断切片**清洗后**是否已无实质内容（真噪声才丢）。

    只在两种情况下丢：① 有效正文不足 ORPHAN_MIN_CHARS；② 清洗后仍是同一片段反复重复。
    """
    t = _clean(text)
    if len(t) < ORPHAN_MIN_CHARS:
        return True
    return _max_repeat(t) >= 6


def orphan_chunks(con, chapter_id: str) -> list:
    """本章「没有任何卡片指向」的切片（已剔除噪声）。"""
    rows = con.execute(
        "SELECT c.id, c.chunk_idx, c.text, m.original_name AS src"
        " FROM chunks c LEFT JOIN materials m ON m.id = c.material_id"
        " WHERE c.chapter_id=?"
        "   AND NOT EXISTS (SELECT 1 FROM knowledge_cards k WHERE k.source_chunk_id = c.id)"
        " ORDER BY c.chunk_idx", (chapter_id,)).fetchall()
    return [r for r in rows if not _boiler(r["text"])]


def gen_for_orphan(job: tuple) -> tuple:
    """单切片补卡：1 切片 = 1 次调用，绑定关系**由构造保证精确**（无需事后猜片）。"""
    goal, tags, row = job
    body = _clean(row["text"])[:ORPHAN_MAX_CHARS]
    n = max(2, min(5, len(body) // 350))
    src = row["src"] or "补充切片"
    shared = any(k in src for k in SHARED_MATERIALS)
    rule = (RULE_STRICT if shared else RULE_NORMAL) + \
        " 本片组是**尚未建档的补充切片**，务必穷尽其中全部可考点。"
    fallback_sub = re.sub(r"\.[a-z]+$", "", src)[:12] or "补充考点"
    try:
        cards = call_llm(SYSTEM_TMPL.format(source=f"{src} · 补充切片", content=body, goal=goal,
                                            tags=tags, n=n, relevance_rule=rule))
        out = []
        for c in cards[:ORPHAN_CAP]:
            c["sub_concept"] = str(c.get("sub_concept") or "").strip()[:40] or fallback_sub
            out.append(c)
        return row, out, None
    except Exception as e:  # noqa: BLE001
        return row, [], str(e)


def fill_orphans(con, chapter: str | None, dry: bool, limit: int) -> dict:
    """给「无卡切片」逐条补卡，实现切片↔卡片一一对应。

    与 fill_gaps 的区别：fill_gaps 是「按考点关键词反查原文」；本函数是
    「把每一片尚未建档的课件原文都过一遍」，因此能覆盖长资料里被片组粒度漏掉的碎片内容
    （2026-09-19 实测 483 片里 339 片无卡，含术语表/价格表/厂商对比/流程步骤等实质考点）。
    绑定采用「谁生成的、就绑给谁」，不做内容重合度反查。
    """
    chapters = con.execute("SELECT id, name FROM chapters ORDER BY folder, order_no").fetchall()
    if chapter:
        chapters = [c for c in chapters if c["id"].startswith(chapter) or c["name"] == chapter]
    out = []
    for ch in chapters:
        cid = ch["id"]
        goal, tags = session_ctx(con, cid)
        pool = orphan_chunks(con, cid)
        if limit:
            pool = pool[:limit]
        idx = [(r["front"], _tokens(f"{r['front']} {r['back'] or ''}"))
               for r in con.execute("SELECT front, back FROM knowledge_cards WHERE chapter_id=?", (cid,))]
        seen = {norm_front(f) for f, _ in idx}
        print(f"\n[{ch['name']}] 无卡切片 {len(pool)} 条待补卡", flush=True)
        added = 0
        jobs = [(goal, tags, r) for r in pool]
        with futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
            for i, (row, cards, err) in enumerate(ex.map(gen_for_orphan, jobs), start=1):
                if err:
                    print(f"   [{i}/{len(pool)}] 失败: {err}", flush=True)
                    continue
                for c in cards:
                    front = str(c.get("front") or "").strip()
                    back = str(c.get("back") or "").strip()
                    if not front or not back:
                        continue
                    k = norm_front(front)
                    if len(k) < 4 or k in seen:
                        continue
                    toks = _tokens(front)
                    if any(is_near_dup(front, toks, f, tk) for f, tk in idx):
                        continue
                    if not dry:
                        con.execute(
                            "INSERT INTO knowledge_cards (id, chapter_id, sub_concept, front, back,"
                            " source_chunk_id, created_at) VALUES (?,?,?,?,?,?,datetime('now'))",
                            (str(uuid.uuid4()), cid, c["sub_concept"], front, back, row["id"]))
                    seen.add(k)
                    idx.append((front, toks))
                    added += 1
                if i % 10 == 0:
                    if not dry:
                        con.commit()
                    print(f"   [{i}/{len(pool)}] 累计补 {added} 张", flush=True)
        if not dry:
            con.commit()
        out.append({"chapter": ch["name"], "orphans": len(pool), "added": added})
        print(f"  → {ch['name']}: 无卡切片 {len(pool)} 条 → 补卡 {added} 张", flush=True)
    return {"added": sum(o["added"] for o in out), "chapters": out}


def rebind_recent(con, n: int) -> dict:
    """把最近插入的 N 张卡片重绑到**内容最吻合**的切片。

    为什么必须做：fill_gaps 的检索是按关键词 LIKE 取首条，命中「AI」「工具」这类泛词时
    会把卡片绑到完全无关的切片（实测「智能编程」卡被绑到「行业黑话」表），
    使「卡片↔切片一一对应」名存实亡。这里以卡片正面+背面的词元与本章每个切片求重合度，取最高者。
    """
    ids = [r["id"] for r in con.execute(
        "SELECT id FROM knowledge_cards ORDER BY rowid DESC LIMIT ?", (n,))]
    reb = _bind_by_content(con, ids)
    con.commit()
    return {"scanned": len(ids), "rebound": reb}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapter", default=None, help="chapter_id 前缀")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--dedupe-db", action="store_true", help="对库中已有卡片做近似去重")
    ap.add_argument("--fill-gaps", default=None,
                    help="考点补漏：传入 audit_alignment.py --llm --save-report 产出的 JSON 报告路径")
    ap.add_argument("--fill-orphans", nargs="?", const="", default=None,
                    help="给「无卡切片」逐条补卡（可带 chapter_id 前缀限定单章）")
    ap.add_argument("--limit", type=int, default=0, help="配合 --fill-orphans：每章只处理前 N 条切片")
    ap.add_argument("--rebind-recent", type=int, default=0,
                    help="把最近 N 张卡片重绑到内容最吻合的切片（补漏后必跑）")
    ap.add_argument("--no-rebind", action="store_true",
                    help="跳过生成后的绑定精度回绑（默认会跑；绑定错位是历史最大缺陷，别关）")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    con = sqlite3.connect(args.db, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=60000")

    def _rebind() -> None:
        """生成后自动回绑：卡片绑到同资料内更吻合的切片（见 scripts/audit_binding.py 头注）。"""
        if args.no_rebind:
            return
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from audit_binding import rebind_weak
        con.commit()
        rebind_weak(Path(args.db))
        con.execute("PRAGMA busy_timeout=60000")
    if args.rebind_recent:
        print("=== 重绑切片 ===")
        print(rebind_recent(con, args.rebind_recent))
        con.close()
        return 0
    if args.dedupe_db:
        print("=== 近似去重 ===")
        print(dedupe_db(con))
        con.close()
        return 0
    if args.fill_gaps:
        print("=== 考点补漏 ===")
        print(fill_gaps(con, Path(args.fill_gaps)))
        _rebind()
        con.close()
        return 0
    if args.fill_orphans is not None:
        print("=== 无卡切片补卡 ===")
        print(fill_orphans(con, args.fill_orphans or None, args.dry_run, args.limit))
        _rebind()
        con.close()
        return 0
    rows = con.execute(
        "SELECT id, name FROM chapters ORDER BY folder, order_no").fetchall()
    if args.chapter:
        rows = [r for r in rows if r["id"].startswith(args.chapter)]
    elif not args.all:
        ap.error("请指定 --chapter <id前缀> 或 --all")

    results = []
    for r in rows:
        results.append(rebuild_chapter(con, r["id"], r["name"], args.dry_run))

    print("\n=== 卡片重做汇总 ===")
    for s in results:
        print(f"  {s['chapter']}: 片组{s['pieces']} 原始{s['raw']} → 去重后 {s['cards']} 张，"
              f"sub_concept {s['sub_concepts']} 个"
              + (f"，继承复习 {s.get('carried_reviews', 0)} 条（旧卡 {s.get('old_cards', 0)} 张）"
                 if not args.dry_run else " [dry-run]"))
    if not args.dry_run:
        _rebind()
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
