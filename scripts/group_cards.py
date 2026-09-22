#!/usr/bin/env python3
"""卡片主题分组（v2.7.0 / KNOW-008）：把一章几百张卡片归并成 10~16 个「学习主题」。

动机：一章 300~650 张卡平铺不可用（用户实报「每个 session 几百张卡片挺多的」）。
本脚本用 LLM 做**三级处理**，只产出**浏览用标签**，绝不改动卡片正文/绑定/复习态：

  1) 主题表（taxonomy）：把该章资料名 + 高频 sub_concept + 抽样 front 投喂，让模型给出
     10~16 个主题（名称 ≤12 字、互不重叠、覆盖全章、**体量均衡**）。
  2) 逐卡归类（assign）：按 25 张一批，把每张卡归到给定主题之一（禁止新造主题）。
  3) 再平衡（rebalance）——首轮实测：模型会把一半卡片塞进「模型选型与对比(280)」这类大桶，
     同时留下一堆 1~4 张的碎片组。故：
       · 超大组（> MAX_TOPIC_CARDS）→ 让模型**拆成 2~4 个子主题**并重新归类（最多拆 2 轮）；
       · 碎片组（< MIN_TOPIC_CARDS）→ 把卡片**并入最贴切的大主题**；实在无处可去才落「其他要点」。

落库：`card_topics(card_id, chapter_id, topic, ord)`（幂等：按章先删后插）。
默认 dry-run，`--apply` 才写库；只删/写 `card_topics`，不碰 `knowledge_cards`。

用法：
    python3 scripts/group_cards.py                  # 全部章节，预览（主题 + 分布 + 抽样）
    python3 scripts/group_cards.py --chapter 3      # 只处理第 3 章（按 chapters.order_no）
    python3 scripts/group_cards.py --apply          # 落库
"""
import argparse
import concurrent.futures as futures
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
DB = BASE / "instance" / "aistudy.sqlite3"

MIN_TOPICS, MAX_TOPICS = 10, 16      # 每章主题数区间
BATCH = 25                           # 每批归类的卡片数
TIMEOUT = 180
WORKERS = 4
SAMPLE_FRONTS = 80                   # 主题表阶段抽样的卡片正面数
MAX_SUBCONCEPTS = 120                # 主题表阶段投喂的高频 sub_concept 上限
MAX_TOPIC_CARDS = 80                 # 单主题卡片上限（≈ 2.5 天量），超过就拆
MIN_TOPIC_CARDS = 5                  # 单主题卡片下限，低于就并
SPLIT_ROUNDS = 2                     # 超大组最多拆几轮
CATCHALL = "其他要点"                 # 无处可去的兜底组（应尽量为空）


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

# 建表：直接复用后端的 schema/migrate（单一真相），避免脚本与 app 的 DDL 漂移。
# 说明：card_topics 由 backend/data/models.py 定义，app 启动时 init_db 也会建；脚本自建是为了
# 「独立可跑」（不依赖先启动一次服务），幂等无副作用。
sys.path.insert(0, str(BASE / "backend"))


def ensure_schema(con) -> None:
    from data import models
    con.executescript(models.SCHEMA)
    models.migrate(con)


def log_usage(model: str, usage, feature: str = "kc-topic") -> None:
    """逐次记账到 app-usage JSONL（与 backend/ai/usage_log.py 同格式）。异常一律吞掉。"""
    try:
        path = (ENV.get("LLM_USAGE_LOG") or os.environ.get("LLM_USAGE_LOG")
                or os.path.expanduser("~/.hermes/app-usage/aistudy.jsonl"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        u = usage or {}
        rec = {
            "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
            "model": str(model or "unknown"),
            "feature": feature,
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "prompt_cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
        }
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def parse_json_obj(text: str) -> dict:
    """容错解析模型输出的 JSON 对象（允许前后有解释文字/代码围栏）。"""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        return json.loads(t)
    except Exception:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            return {}
    return {}


def chat(system: str, feature: str = "kc-topic") -> dict:
    """一次 LLM 调用 → JSON 对象。temperature=0（归类任务要可复现）。"""
    import requests
    key = ENV.get("DEEPSEEK_API_KEY", "")
    base = ENV.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    model = ENV.get("DEEPSEEK_MODEL", "deepseek-chat")
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY（.env）")
    resp = requests.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "system", "content": system}],
              "temperature": 0},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    log_usage(model, data.get("usage"), feature)
    return parse_json_obj(data["choices"][0]["message"]["content"])


# ---------------------------------------------------------------- 数据读取

def load_chapters(con, only=None):
    rows = con.execute(
        "SELECT c.id, c.name, c.order_no FROM chapters c ORDER BY c.folder, c.order_no, c.name"
    ).fetchall()
    if only:
        rows = [r for r in rows if r["order_no"] == only]
    return rows


def load_cards(con, chapter_id):
    """卡片 + 来源资料名（分组时给模型当上下文；也用于人工复核）。"""
    rows = con.execute(
        """SELECT kc.id, kc.sub_concept, kc.front,
                  COALESCE(m.original_name, '') AS material
             FROM knowledge_cards kc
             LEFT JOIN chunks ch ON ch.id = kc.source_chunk_id
             LEFT JOIN materials m ON m.id = ch.material_id
            WHERE kc.chapter_id = ?
            ORDER BY kc.rowid""",
        (chapter_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def sample(items, n):
    """等距抽样（保住头尾，避免只看到开头一批）。"""
    if len(items) <= n:
        return list(items)
    step = len(items) / float(n)
    return [items[int(i * step)] for i in range(n)]


# ---------------------------------------------------------------- 阶段 1：主题表

TAXO_SYS = """你是「AI 学习小组」的资深教研老师。任务：为**一章**知识卡片设计一套「浏览用主题分类」。

要求：
1. 给出 %d~%d 个主题，互不重叠、合起来覆盖全章所有卡片。
2. 主题名 **4~12 个汉字**，是学生一眼能懂的知识领域名（例：大模型基础概念 / 模型选型对比 /
   产品经理视角 / 常见误区澄清）。**不要**用「其他」「综合」「杂项」这类垃圾桶名，
   也不要带「第X章」等章节前缀。
3. **体量必须均衡**：每个主题大致 25~70 张卡，**不允许**某一主题吞掉全章一半以上。
   当一个领域卡片很多时（例：「模型选型」「产品经理视角」），必须按**子话题**拆成多个主题
   （例：闭源旗舰模型 / 开源模型榜单 / 小模型选型 / AI 编程工具选型）。
4. 只输出 JSON，不要多余文字：
{"topics":[{"name":"主题名","brief":"一句话说明涵盖什么"}, ...]}"""


def build_taxonomy(con, chapter):
    cards = load_cards(con, chapter["id"])
    subs = {}
    for c in cards:
        key = (c["sub_concept"] or "").strip() or "(无标签)"
        subs[key] = subs.get(key, 0) + 1
    top_subs = sorted(subs.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_SUBCONCEPTS]
    fronts = sample([c["front"] for c in cards], SAMPLE_FRONTS)
    mats = sorted({c["material"] for c in cards if c["material"]})

    payload = [
        f"章节：{chapter['name']}（共 {len(cards)} 张卡片）",
        "",
        "## 本章资料文件",
        *(f"- {m}" for m in mats),
        "",
        "## 卡片子标签（标签:卡片数，按数量降序，已截断）",
        "、".join(f"{s}({n})" for s, n in top_subs),
        "",
        f"## 卡片正面抽样（等距抽样 {len(fronts)} 条）",
        *(f"- {f}" for f in fronts),
        "",
        "请输出这套主题分类的 JSON。",
    ]
    got = chat(TAXO_SYS % (MIN_TOPICS, MAX_TOPICS), "kc-topic-taxonomy")
    topics, seen = [], set()
    for t in got.get("topics") or []:
        name = str((t or {}).get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        topics.append({"name": name[:14], "brief": str((t or {}).get("brief") or "").strip()})
    if not (MIN_TOPICS <= len(topics) <= MAX_TOPICS + 2):
        print(f"  ⚠️ 主题数异常：{len(topics)}（期望 {MIN_TOPICS}~{MAX_TOPICS}），仍继续")
    return cards, topics


# ---------------------------------------------------------------- 阶段 2：逐卡归类

ASSIGN_SYS = """你在给知识卡片做**浏览用主题归类**。下面是本章已定好的主题表，请把每张卡片归到**其中最贴切的一个**主题。

硬约束：
1. 只能用给定的主题（用主题的**序号**回答）；**绝不新造主题**。
2. 每张卡片都必须有一个归类，不许留空。
3. 拿不准时选「主要考察内容」最接近的那个主题，不要因为出现同一个词就选。
4. 只输出 JSON：{"assignments":[{"i":1,"t":3}, ...]}，i = 卡片序号，t = 主题序号（从 1 开始）。"""


def assign_batch(topic_names, batch, feature="kc-topic-assign"):
    lines = [f"## 主题表（{len(topic_names)} 个）"]
    for i, name in enumerate(topic_names, start=1):
        lines.append(f"{i}. {name}")
    lines += ["", f"## 待归类卡片（{len(batch)} 张）"]
    for i, c in enumerate(batch, start=1):
        lines.append(f"{i}. {c['front']}")
    lines += ["", "请为上面每张卡片输出 {i, t} 的 JSON。"]
    got = chat(ASSIGN_SYS + "\n\n" + "\n".join(lines), feature)
    out = {}
    for a in got.get("assignments") or []:
        try:
            i = int(a.get("i")); t = int(a.get("t"))
        except Exception:
            continue
        if 1 <= i <= len(batch) and 1 <= t <= len(topic_names):
            out[i] = t
    return out


def assign_all(topic_names, cards, feature="kc-topic-assign"):
    """并发按批归类；返回 {卡片序号(1起): 主题序号(1起)}（缺失的由调用方兜底）。"""
    batches = [cards[i:i + BATCH] for i in range(0, len(cards), BATCH)]
    result = {}
    with futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        jobs = [(bi, pool.submit(assign_batch, topic_names, b, feature)) for bi, b in enumerate(batches)]
        for bi, job in jobs:
            b = batches[bi]
            try:
                got = job.result()
            except Exception as exc:                        # 单批失败不影响其他批
                print(f"  ⚠️ 批次 {bi + 1}/{len(batches)} 归类失败：{exc}")
                got = {}
            for i, c in enumerate(b, start=1):
                result[c["id"]] = got.get(i)
    return result


# ---------------------------------------------------------------- 阶段 3：再平衡

SPLIT_SYS = """一组卡片被归在同一个主题下，但这组**太大了**（浏览时又变成卡片墙）。请把它拆成 %d~%d 个更细的**子主题**。

要求：
1. 子主题名 4~12 个汉字，互不重叠、合起来覆盖这组全部卡片，**体量尽量均衡**。
2. 不要用「其他」「其他要点」这类名字。
3. 只输出 JSON：{"topics":[{"name":"子主题名","brief":"一句话"}, ...]}"""

SPLIT_ASSIGN_SYS = """下面是刚拆好的子主题表。请把每张卡片归到**其中最贴切的一个**子主题。

硬约束：只能用给定子主题（用序号回答）；每张卡都必须有归属；只输出 JSON：
{"assignments":[{"i":1,"t":2}, ...]}（i = 卡片序号，t = 子主题序号，从 1 开始）。"""

MERGE_SYS = """下面这些卡片目前所在的主题**太小**（不成组）。请把每张卡片归到给定大主题中最贴切的一个。

硬约束：只能用给定大主题（用序号回答）；每张卡都必须有归属；只输出 JSON：
{"assignments":[{"i":1,"t":2}, ...]}（i = 卡片序号，t = 大主题序号，从 1 开始）。"""


def _one_pass_assign(sys_prompt, topic_names, cards, feature):
    """给一批卡片按给定主题名归类（复用 assign_batch 的解析逻辑）。"""
    batches = [cards[i:i + BATCH] for i in range(0, len(cards), BATCH)]
    lines = [f"## 主题表（{len(topic_names)} 个）"]
    for i, name in enumerate(topic_names, start=1):
        lines.append(f"{i}. {name}")
    lines += ["", f"## 待归类卡片（{len(cards)} 张）"]
    for i, c in enumerate(cards, start=1):
        lines.append(f"{i}. {c['front']}")
    lines += ["", "请为上面每张卡片输出 {i, t} 的 JSON。"]
    full = sys_prompt + "\n\n" + "\n".join(lines)
    if len(batches) == 1:
        pairs = [_parse_assignments(chat(full, feature), len(cards), len(topic_names))]
    else:
        # 卡片太多：按批并发（每批重新带上主题表，保证上下文完整）
        with futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
            jobs = []
            for b in batches:
                head = [f"## 主题表（{len(topic_names)} 个）"]
                head += [f"{i}. {n}" for i, n in enumerate(topic_names, start=1)]
                head += ["", f"## 待归类卡片（{len(b)} 张）"]
                head += [f"{i}. {c['front']}" for i, c in enumerate(b, start=1)]
                head += ["", "请为上面每张卡片输出 {i, t} 的 JSON。"]
                jobs.append((b, pool.submit(chat, sys_prompt + "\n\n" + "\n".join(head), feature)))
            pairs = []
            for b, job in jobs:
                try:
                    got = job.result()
                except Exception:
                    got = {}
                pairs.append(_parse_assignments(got, len(b), len(topic_names)))
    out = {}
    for b, got in zip(batches, pairs):
        for i, c in enumerate(b, start=1):
            t = got.get(i)
            if t:
                out[c["id"]] = t
    return out


def _parse_assignments(got, n_cards, n_topics):
    out = {}
    for a in (got or {}).get("assignments") or []:
        try:
            i = int(a.get("i")); t = int(a.get("t"))
        except Exception:
            continue
        if 1 <= i <= n_cards and 1 <= t <= n_topics:
            out[i] = t
    return out


def rebalance(cards, names_of, report):
    """把 {card_id: 主题名} 调均衡：超大组拆细、碎片组并入。返回新的 {card_id: 主题名}。"""
    by_card = {c["id"]: c for c in cards}

    def groups(mapping):
        g = {}
        for cid, name in mapping.items():
            g.setdefault(name, []).append(cid)
        return g

    # ---- ① 超大组：拆
    for _ in range(SPLIT_ROUNDS):
        g = groups(names_of)
        oversized = [(n, ids) for n, ids in g.items() if len(ids) > MAX_TOPIC_CARDS]
        if not oversized:
            break
        for name, ids in sorted(oversized, key=lambda kv: -len(kv[1])):
            sub_cards = [by_card[i] for i in ids]
            got = chat((SPLIT_SYS % (2, 4)) + "\n\n下面是这组卡片（%d 张）：\n" % len(sub_cards)
                       + "\n".join(f"- {c['front']}" for c in sample(sub_cards, 120))
                       + "\n\n请给出子主题 JSON。", "kc-topic-split")
            subs, seen = [], set()
            for t in got.get("topics") or []:
                nm = str((t or {}).get("name") or "").strip()
                if nm and nm not in seen and nm != CATCHALL:
                    seen.add(nm)
                    subs.append(nm[:14])
            if len(subs) < 2:                                  # 拆不动就保持原样
                continue
            sub_cards_all = sorted(sub_cards, key=lambda c: c["front"])
            mapping = _one_pass_assign(SPLIT_ASSIGN_SYS, subs, sub_cards_all, "kc-topic-split-assign")
            moved = 0
            for c in sub_cards_all:
                t = mapping.get(c["id"])
                if t:
                    names_of[c["id"]] = subs[t - 1] if t <= len(subs) else name
                    moved += 1
            report["split"] += 1
            print(f"    拆：{name}({len(ids)}) → {len(subs)} 个子主题（归类 {moved}/{len(ids)}）：{'｜'.join(subs)}")

    # ---- ② 碎片组：并
    g = groups(names_of)
    big = sorted([(n, len(ids)) for n, ids in g.items() if len(ids) >= MIN_TOPIC_CARDS],
                 key=lambda kv: -kv[1])
    tiny = [(n, ids) for n, ids in g.items() if len(ids) < MIN_TOPIC_CARDS and n != CATCHALL]
    if tiny and big:
        big_names = [n for n, _ in big]
        tiny_cards = [by_card[i] for _, ids in tiny for i in ids]
        mapping = _one_pass_assign(MERGE_SYS, big_names, sorted(tiny_cards, key=lambda c: c["front"]),
                                   "kc-topic-merge")
        moved = 0
        for c in tiny_cards:
            t = mapping.get(c["id"])
            if t and 1 <= t <= len(big_names):
                names_of[c["id"]] = big_names[t - 1]
                moved += 1
            else:
                names_of[c["id"]] = CATCHALL
        report["merged"] += moved
        report["catchall"] += len(tiny_cards) - moved
        print(f"    并：{len(tiny)} 个碎片组 {len(tiny_cards)} 张 → 大主题（成功 {moved}，兜底 {len(tiny_cards) - moved}）")
    return names_of


# ---------------------------------------------------------------- 主流程

def run_chapter(con, chapter, apply_):
    print(f"\n=== [{chapter['order_no']}] {chapter['name']}")
    cards, topics = build_taxonomy(con, chapter)
    if not cards:
        print("  （无卡片，跳过）")
        return None
    print(f"  主题表（{len(topics)} 个）：" + "｜".join(t["name"] for t in topics))
    tnames = [t["name"] for t in topics]

    # 首轮归类（返回 {card_id: 主题序号} → 换成主题名）
    raw = assign_all(tnames, cards)
    names_of = {}
    miss = 0
    for c in cards:
        t = raw.get(c["id"])
        if t and 1 <= t <= len(tnames):
            names_of[c["id"]] = tnames[t - 1]
        else:
            names_of[c["id"]] = CATCHALL
            miss += 1
    report = {"split": 0, "merged": 0, "catchall": miss}
    print(f"  首轮归类：兜底 {miss} 张")
    names_of = rebalance(cards, names_of, report)

    # 统计 + 落库
    per_topic = {}
    for c in cards:
        per_topic[names_of[c["id"]]] = per_topic.get(names_of[c["id"]], 0) + 1
    ordered = sorted(per_topic.items(), key=lambda kv: -kv[1])
    ords = {name: i for i, (name, _) in enumerate(ordered)}
    print(f"  最终 {len(ordered)} 组（拆分 {report['split']} 次，并入 {report['merged']} 张，兜底 {report['catchall']} 张）：")
    for name, n in ordered:
        print(f"    {n:4} 张 ← {name}")

    if apply_:
        con.execute("DELETE FROM card_topics WHERE chapter_id=?", (chapter["id"],))
        con.executemany(
            "INSERT OR REPLACE INTO card_topics (card_id, chapter_id, topic, ord) VALUES (?,?,?,?)",
            [(c["id"], chapter["id"], names_of[c["id"]], ords[names_of[c["id"]]]) for c in cards],
        )
        con.commit()
        n = con.execute("SELECT COUNT(*) FROM card_topics WHERE chapter_id=?", (chapter["id"],)).fetchone()[0]
        print(f"  ✅ 已落库 {n} 行 card_topics")
    return {"chapter": chapter["name"], "cards": len(cards), "topics": len(ordered),
            "max": ordered[0][1] if ordered else 0, "catchall": report["catchall"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落库（默认只预览）")
    ap.add_argument("--chapter", type=int, default=None, help="只处理指定章（chapters.order_no）")
    args = ap.parse_args()

    con = sqlite3.connect(str(DB), timeout=15)
    con.row_factory = sqlite3.Row
    ensure_schema(con)
    chapters = load_chapters(con, args.chapter)
    if not chapters:
        print("没有匹配的章节", file=sys.stderr)
        return 1

    reports = []
    for ch in chapters:
        rep = run_chapter(con, ch, args.apply)
        if rep:
            reports.append(rep)

    print("\n" + "=" * 60)
    print("汇总（章｜卡片数｜主题组数｜最大组｜兜底张数）")
    for r in reports:
        print(f"  {r['chapter']}｜{r['cards']}｜{r['topics']}｜{r['max']}｜{r['catchall']}")
    if not args.apply:
        print("\n（dry-run；加 --apply 落库 card_topics）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
