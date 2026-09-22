#!/usr/bin/env python3
"""章节重命名（v2.7.0）：把「第X周·第Y节 · 标题」解耦为「第 N 章 · 标题」。

背景：学习节奏由学生自己定（每日 30 张即可，一周 210 张），章节挂「周/节」既不真实
也把「内容结构」和「时间安排」绑死了。本脚本只改展示口径，不动任何内容/绑定关系。

规则：
  - name  ：「第X周·第Y节 · 标题」→「第 N 章 · 标题」（N = 全局课程顺序，1 起）
  - folder：置空（不再有「第X周」分组）；展示层改为「预计 X 天学完」
  - order_no：按原 (folder, order_no, name) 顺序重排为 1..N（folder 置空后仍能正确排序）

幂等：可重复执行（已重命名过的章节取「·」后段标题，结果不变）。
默认 dry-run，`--apply` 才写库；写库前用 SQLite `.backup` 做一致快照备份。

用法：
    python scripts/rename_chapters.py            # 预览
    python scripts/rename_chapters.py --apply    # 落库（自动备份）
"""
import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "instance", "aistudy.sqlite3")
BACKUP_DIR = os.path.join(ROOT, "backups", datetime.now().strftime("%Y-%m-%d") + "-chapters")


def topic_of(name: str) -> str:
    """取「·」后的标题段：'第1周·第1节 · AI 产品地图' → 'AI 产品地图'（幂等）。"""
    parts = [p.strip() for p in (name or "").split("·")]
    return parts[-1] if parts else (name or "").strip()


def backup() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = os.path.join(BACKUP_DIR, f"aistudy.sqlite3.pre-rename-{stamp}.bak")
    # 用 SQLite .backup 取一致快照（`cp` 会漏掉 -wal 里未 checkpoint 的写入）
    subprocess.run(["/usr/bin/sqlite3", DB, f".backup {dst}"], check=True)
    return dst


def plan(con) -> list:
    rows = con.execute(
        "SELECT id, folder, name, order_no FROM chapters ORDER BY folder, order_no, name"
    ).fetchall()
    out = []
    for i, r in enumerate(rows, start=1):
        out.append({
            "id": r["id"],
            "old_name": r["name"],
            "new_name": f"第 {i} 章 · {topic_of(r['name'])}",
            "old_order": r["order_no"],
            "new_order": i,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落库（默认只预览）")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"库不存在：{DB}", file=sys.stderr)
        return 1
    if args.apply and not shutil.which("sqlite3"):
        print("需要 sqlite3 命令行做一致快照备份", file=sys.stderr)
        return 1

    con = sqlite3.connect(DB, timeout=10)
    con.row_factory = sqlite3.Row
    rows = plan(con)
    if not rows:
        print("没有章节可改")
        return 0

    for r in rows:
        changed = r["old_name"] != r["new_name"] or r["old_order"] != r["new_order"]
        mark = "改" if changed else "同"
        print(f"[{mark}] order {r['old_order']}→{r['new_order']}｜{r['old_name']}")
        print(f"      → {r['new_name']}")

    if not args.apply:
        print("\n（dry-run；加 --apply 落库）")
        return 0

    bak = backup()
    print(f"\n已备份：{bak}")
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        con.execute(
            "UPDATE chapters SET name=?, folder='', order_no=?, status=COALESCE(status,'published')"
            " WHERE id=?",
            (r["new_name"], r["new_order"], r["id"]),
        )
        # 兼容老库：chapters 无 updated_at 列，故不写时间戳
        _ = now
    con.commit()

    # 落库后自检
    chk = con.execute(
        "SELECT id, folder, name, order_no FROM chapters ORDER BY folder, order_no"
    ).fetchall()
    print("落库后：")
    for c in chk:
        print(f"  order {c['order_no']}｜folder={c['folder']!r}｜{c['name']}")
    print(f"共 {len(chk)} 章")
    return 0


if __name__ == "__main__":
    sys.exit(main())
