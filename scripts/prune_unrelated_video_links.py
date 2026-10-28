#!/usr/bin/env python3
"""清理「八竿子打不着」的共享视频链接（REQ-VID-LINK-01）。

背景（2026-10-27 用户实测）：第 3 章「六大核心设计对象」那张卡，点开播的是
「持久化上下文工作台」。根因是借链由 LLM「挑最接近的 5–10 个」产生，没有校验。

两道闸：
1) 机械：同切片（source_chunk_id 相同）或同子概念（sub_concept 相同）→ 直接放行；
2) 语义：其余逐条过 LLM 裁定（scripts/judge_video_links_llm.py 的决策表），
   只有 `same=true` 且给出共同知识点名称的才保留。

不满足的借链一律删除（`is_core=1` 永不动）。删完后这些卡退回「▶ AI 视频讲解」，
可自行生成，不再假装「已就绪」播别人的片。

用法：
    python3 scripts/prune_unrelated_video_links.py --judge-json /tmp/video_link_judge.json
    python3 scripts/prune_unrelated_video_links.py --judge-json /tmp/video_link_judge.json --apply
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))

from video_links import is_related  # noqa: E402

DB = BASE / "instance" / "aistudy.sqlite3"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge-json", type=Path, help="LLM 裁定决策表")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    verdict = {}
    if args.judge_json and args.judge_json.exists():
        data = json.loads(args.judge_json.read_text(encoding="utf-8"))
        for r in data.get("results", []):
            verdict[(r["video_id"], r["card_id"])] = r

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute(
        """CREATE TABLE IF NOT EXISTS video_link_reviews(
               video_id TEXT NOT NULL, card_id TEXT NOT NULL,
               same INTEGER NOT NULL, concept TEXT DEFAULT '',
               source TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')),
               PRIMARY KEY(video_id, card_id))"""
    )
    rows = con.execute(
        """SELECT l.video_id,l.card_id,v.title,
                  c.front cfront,c.sub_concept csub,c.source_chunk_id cchunk,
                  core.sub_concept ksub,core.source_chunk_id kchunk
           FROM card_video_links l
           JOIN card_videos v ON v.id=l.video_id
           JOIN knowledge_cards c ON c.id=l.card_id
           JOIN knowledge_cards core ON core.id=v.core_card_id
           WHERE l.is_core=0"""
    ).fetchall()

    bad, keep_struct, keep_llm, unjudged = [], 0, 0, 0
    for r in rows:
        card = {"sub_concept": r["csub"], "source_chunk_id": r["cchunk"]}
        core = {"sub_concept": r["ksub"], "source_chunk_id": r["kchunk"]}
        if is_related(card, core):
            keep_struct += 1
            continue
        v = verdict.get((r["video_id"], r["card_id"]))
        if v is None:
            unjudged += 1
            bad.append(r)
            continue
        if v.get("same") and str(v.get("evidence", "")).strip():
            keep_llm += 1
            continue
        bad.append(r)

    print("借链 %d｜机械保留 %d｜语义保留 %d｜待删 %d（其中未裁定 %d）"
          % (len(rows), keep_struct, keep_llm, len(bad), unjudged))
    for r in bad[:5]:
        print("  删：卡「%s」⇢片「%s」" % ((r["cfront"] or "")[:24], (r["title"] or "")[:24]))
    if not args.apply:
        print("预演完成，未写库。加 --apply 落库。")
        return 0
    with con:
        con.executemany(
            "DELETE FROM card_video_links WHERE video_id=? AND card_id=? AND is_core=0",
            [(r["video_id"], r["card_id"]) for r in bad],
        )
        con.executemany(
            """INSERT OR REPLACE INTO video_link_reviews(video_id,card_id,same,concept,source)
               VALUES(?,?,?,?,?)""",
            [(vid, cid, 1 if (verdict.get((vid, cid)) or {}).get("same") else 0,
              str((verdict.get((vid, cid)) or {}).get("evidence", ""))[:80], "llm_v2")
             for vid, cid in verdict],
        )
    left = con.execute("SELECT COUNT(*) FROM card_video_links WHERE is_core=0").fetchone()[0]
    print("已删 %d 条；剩余借链 %d 条" % (len(bad), left))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
