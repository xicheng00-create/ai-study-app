#!/usr/bin/env python3
"""存量收敛：把库内「分组标签」的仅空格差异同义写法归一。

- 官方唯一实现：`backend/ai/cardtext.py::normalize_label`（口径 + 覆盖路径写在那个文件的文档里）。
- 覆盖对象：`knowledge_cards.sub_concept`（教师端分组头 + 学生端卡片副标题；分裂的出处）。
  `card_topics.topic`（学生端分组头）**不纳入**：它每章一次性生成、章内同构无分裂，
  纳入只会无收益地改写线上学生正在看的主题名。理由详见 `backend/ai/cardtext.py` 文档。
- 默认 **dry-run**（只打印将要改什么）；`--apply` 才写库，且**先做 sqlite 快照备份**。
- 幂等：重复跑第二次 0 改动。

用法：
    ./.venv/bin/python scripts/normalize_subconcepts.py            # 看计划
    ./.venv/bin/python scripts/normalize_subconcepts.py --apply    # 落库（自动备份）
"""
import argparse
import collections
import datetime
import sqlite3
import sys
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))
from ai.cardtext import normalize_label, group_key  # noqa: E402

DB = BASE / "instance" / "aistudy.sqlite3"
# (表, 列, 主键列)
TARGETS = (("knowledge_cards", "sub_concept", "id"),)


def whitespace_synonym_groups(con, table="knowledge_cards", col="sub_concept"):
    """返回 {去空白键: [写法...]} —— 值长度 >1 即为同义分裂（差异仅空白）。"""
    rows = con.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''")
    g = collections.defaultdict(set)
    for (v,) in rows:
        g[group_key(v)].add(v)
    return {k: sorted(v) for k, v in g.items() if len(v) > 1}


def snapshot(db: Path) -> Path:
    out = BASE / "backups" / f"{datetime.date.today().isoformat()}-subconcept-normalize"
    out.mkdir(parents=True, exist_ok=True)
    dst = out / "aistudy-before-normalize.sqlite3"
    src = sqlite3.connect(str(db))
    tgt = sqlite3.connect(str(dst))
    src.backup(tgt)
    tgt.close()
    src.close()
    return dst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--apply", action="store_true", help="写库（默认只打印计划）")
    ap.add_argument("--sample", type=int, default=8, help="打印多少条改写样例")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row

    if args.apply:
        print("备份 ->", snapshot(Path(args.db)))

    total_changed = 0
    for table, col, key in TARGETS:
        before = whitespace_synonym_groups(con, table, col)
        rows = con.execute(
            f"SELECT {key} AS k, {col} AS v FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''").fetchall()
        plan = [(r["k"], r["v"], normalize_label(r["v"])) for r in rows]
        plan = [(k, v, nv) for k, v, nv in plan if nv != v]
        print(f"\n== {table}.{col}：同义组 {len(before)} / 待改写 {len(plan)} 行")
        for key_, variants in list(before.items())[:args.sample]:
            print(f"   {group_key(variants[0])!r}: {variants}")
        for k, v, nv in plan[:args.sample]:
            print(f"   · {v!r} -> {nv!r}")
        if args.apply and plan:
            con.executemany(
                f"UPDATE {table} SET {col}=? WHERE {key}=?", [(nv, k) for k, _, nv in plan])
            con.commit()
        total_changed += len(plan)
        after = whitespace_synonym_groups(con, table, col)
        print(f"   → 归一反剩余同义组: {len(after)}" + (f" {after}" if after else ""))

    print(f"\n合计改写 {total_changed} 行" + ("（已落库）" if args.apply else "（dry-run，未写库）"))
    print("完整性:", con.execute("PRAGMA integrity_check").fetchone()[0])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
