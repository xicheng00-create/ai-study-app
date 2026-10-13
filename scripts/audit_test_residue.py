#!/usr/bin/env python3
"""体检生产库里的「测试残留」账号（2026-10-13 事故后新增）。

事故：`tests/test_videos.py::test_prewarm_uses_task_deck_card_set` 曾在未隔离的路径下
跑过一次，把假用户 `warm-user` / 显示名 `Warm`（`created_at='2099'`、`password_hash='x'`）
连同 30 条 prewarm 视频请求写进生产库，并真的生成 30 个视频；该假号随后出现在
学生端「班级」排行榜上。已清理；本脚本是常驻体检判据。

判据（命中任一即视为残留）：
  1. `password_hash` 长度 != 162 —— werkzeug scrypt 哈希固定 162 字符，测试桩常用 `'x'`；
  2. `created_at` 不匹配 ISO-8601（如测试哨兵值 `'2099'`）。

用法：
  python3 scripts/audit_test_residue.py                 # 默认查生产库
  python3 scripts/audit_test_residue.py --db <path>     # 查备份库/副本（用于证明判据真会红）
命中：打印明细 + exit 1；干净：exit 0；库不存在/参数错：exit 2。
"""
import argparse
import os
import re
import sqlite3
import sys

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "instance", "aistudy.sqlite3")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T")
SCrypt_LEN = 162


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print(f"库不存在：{args.db}")
        return 2
    # 路径含中文时 file: URI 的 mode=ro 会打不开（实测 OperationalError）→ 普通连接 + query_only 强制只读
    con = sqlite3.connect(os.path.abspath(args.db))
    con.execute("PRAGMA query_only=ON")
    rows = con.execute("SELECT id, username, display_name, role, created_at, password_hash FROM users").fetchall()
    hits = []
    for uid, username, display, role, created, ph in rows:
        why = []
        if ph is None or len(ph) != SCrypt_LEN:
            why.append(f"password_hash 长度 {len(ph) if ph else 0}（非 {SCrypt_LEN}）")
        if not created or not ISO.match(str(created)):
            why.append(f"created_at 非 ISO-8601：{created!r}")
        if why:
            hits.append((uid, username, display, role, "; ".join(why)))
    print(f"库：{args.db}\n用户数：{len(rows)}")
    if hits:
        print(f"\n❌ 发现测试残留账号 {len(hits)} 个：")
        for h in hits:
            print(f"  - id={h[0]} username={h[1]} display={h[2]} role={h[3]} → {h[4]}")
        print("\n处置：备份库 → DELETE 该 users 行 + 其 user_id 名下 card_video_requests / card_video_daily_runs → 复跑本脚本应 exit 0。")
        return 1
    print("\n✅ 无测试残留（全部账号密码哈希 162 字符、created_at 为 ISO-8601）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
