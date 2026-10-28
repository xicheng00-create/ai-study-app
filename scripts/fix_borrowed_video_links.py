#!/usr/bin/env python3
"""把「借来的视频」链接改指到卡片自己的成片。

背景：旧批量任务按「概念」出片，然后把同一片挂到多张卡（is_core=0 的借链）。
结果一张卡点开视频，播的是别的卡的内容（2026-10-27 用户实测发现：第 3 章
「六大核心设计对象」这张卡，点开播的是「持久化上下文工作台」那一集）。

本脚本只处理「自己有成片」的卡：删借链、补自己的链接（is_core=1）。
没有自己成片的卡不在这里处理（另见 --report 输出待生成清单）。

用法：
    python3 scripts/fix_borrowed_video_links.py            # 预演
    python3 scripts/fix_borrowed_video_links.py --apply    # 落库
"""
import argparse
import sqlite3
from pathlib import Path

DB = Path("/Users/xicheng/WorkBuddy/AI学习小组app/instance/aistudy.sqlite3")

BORROWED = """
    SELECT DISTINCT l.card_id AS cid, own.id AS own_id
    FROM card_video_links l
    JOIN card_videos v ON v.id = l.video_id AND v.core_card_id <> l.card_id
    JOIN card_videos own ON own.core_card_id = l.card_id AND own.status = 'ready'
"""
PENDING = """
    SELECT DISTINCT l.card_id AS cid
    FROM card_video_links l
    JOIN card_videos v ON v.id = l.video_id AND v.core_card_id <> l.card_id
    WHERE NOT EXISTS (
        SELECT 1 FROM card_videos own WHERE own.core_card_id = l.card_id AND own.status = 'ready'
    )
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写库（默认预演）")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    try:
        fixable = con.execute(BORROWED).fetchall()
        pending = con.execute(PENDING).fetchall()
        print("可立即改指（自己有成片）：%d 张" % len(fixable))
        print("只挂借链、自己没有成片：%d 张（需重新生成或先隐藏）" % len(pending))
        if not args.apply:
            print("预演完成，未写库。加 --apply 落库。")
            return 0
        with con:
            for r in fixable:
                con.execute("DELETE FROM card_video_links WHERE card_id=?", (r["cid"],))
                con.execute(
                    "INSERT OR REPLACE INTO card_video_links(video_id, card_id, is_core) VALUES(?,?,1)",
                    (r["own_id"], r["cid"]),
                )
        left = con.execute(
            """SELECT COUNT(*) AS n FROM card_video_links l
               JOIN card_videos v ON v.id=l.video_id WHERE v.core_card_id <> l.card_id"""
        ).fetchone()["n"]
        print("已改指 %d 张；剩余借链 %d 条" % (len(fixable), left))
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
