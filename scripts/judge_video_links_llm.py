"""借链相关性 LLM 裁定（REQ-VID-LINK-01 第二道闸）。

机械判据只能抓住「同切片/同子概念」；剩下的要靠语义判断，否则会把
「职业发展」这种真同块的删掉，又把「PMF vs MVP」这种模板相同的留下。

判据（写死，防漂移）：
- true：同一个具体知识点 / 同一术语 / 同一小节内容；
- false：只同章、同大类、模板句式相同但对象不同（PMF vs MVP、Gemini vs GPT）、判不准。
输出 JSON 决策表，供 apply 脚本使用；不改库。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))

from ai.agents import _chat  # noqa: E402
from video_links import is_related  # noqa: E402

DB = BASE / "instance" / "aistudy.sqlite3"
OUT = Path("/tmp/video_link_judge.json")

PROMPT = """判断下面「卡片」与「视频」讲的是不是同一个知识点（同一个小节 / 同一个概念）。

卡片问题：{front}
卡片答案要点：{back}
视频主题：{title}

判定规则：
- 两者围绕同一个命名概念或同一个小节展开 → same=true（例：都在讲「职业发展」，都在讲「Transformer 架构」）；
- 属于同一大类但各自讲不同对象、不同结论 → false（例：PMF 与 MVP、Gemini 与 GPT、六大设计对象 与 持久化上下文工作台）；
- 只是章节相同、句式相同、都提到「大模型」这种泛词 → false；
- 判断不了 → false。
只输出 JSON：{{"same": true/false, "concept": "两者共同的知识点名称；不同则空字符串"}}"""


def judge(row) -> dict:
    try:
        script = json.loads(row["script_json"] or "{}")
    except (ValueError, TypeError):
        script = {}
    prompt = PROMPT.format(
        front=(row["cfront"] or "")[:200],
        back=(row["cback"] or "")[:120],
        title=(row["title"] or "")[:160],
        concept=str(script.get("concept", ""))[:80],
    )
    raw = _chat([{"role": "user", "content": prompt}], feature="video_link_judge") or ""
    same, evidence = False, ""
    try:
        start = raw.index("{")
        obj = json.loads(raw[start:raw.rindex("}") + 1])
        same = bool(obj.get("same")) is True
        evidence = str(obj.get("concept", ""))[:60]
    except (ValueError, TypeError, json.JSONDecodeError):
        same = False
    return {"video_id": row["video_id"], "card_id": row["card_id"],
            "same": same, "evidence": evidence,
            "card": (row["cfront"] or "")[:40], "video": (row["title"] or "")[:40]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("缺 DEEPSEEK_API_KEY：先 set -a; source .env; set +a 再跑")
        return 2
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """SELECT l.video_id,l.card_id,v.title,v.script_json,
                  c.front cfront,c.back cback,c.sub_concept csub,c.source_chunk_id cchunk,
                  core.sub_concept ksub,core.source_chunk_id kchunk
           FROM card_video_links l
           JOIN card_videos v ON v.id=l.video_id
           JOIN knowledge_cards c ON c.id=l.card_id
           JOIN knowledge_cards core ON core.id=v.core_card_id
           WHERE l.is_core=0"""
    ).fetchall()
    todo = []
    structural = 0
    for r in rows:
        card = {"sub_concept": r["csub"], "source_chunk_id": r["cchunk"]}
        core = {"sub_concept": r["ksub"], "source_chunk_id": r["kchunk"]}
        if is_related(card, core):
            structural += 1
        else:
            todo.append(r)
    if args.limit:
        todo = todo[:args.limit]
    print("借链 %d｜机械判定通过 %d｜送审 %d" % (len(rows), structural, len(todo)))
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(judge, todo))
    same = [r for r in results if r["same"]]
    print("裁定同一知识点 %d｜不相关 %d" % (len(same), len(results) - len(same)))
    print("--- 判为同块的前 6 例 ---")
    for r in same[:6]:
        print("  [%s] 卡「%s」⇢片「%s」" % (r["evidence"], r["card"], r["video"]))
    print("--- 判为不相关的前 6 例 ---")
    for r in [x for x in results if not x["same"]][:6]:
        print("  卡「%s」⇢片「%s」" % (r["card"], r["video"]))
    OUT.write_text(json.dumps({"structural": structural, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("决策表已写", OUT)
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
