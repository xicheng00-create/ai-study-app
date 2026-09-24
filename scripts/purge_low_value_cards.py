#!/usr/bin/env python3
"""清退「低价值卡」：按 2026-09-22 教研定调判定的卡片，带备份 + 可回滚报告。

用户 2026-09-24 指示：删全部 70 张（LLM 依门槛判定：课程元信息 27 / 纯数值 25 / 纯清单 10 / 代码细节 8）。

用法：
    python3 purge_low_value.py --plan <judge.jsonl>            # dry-run（默认）
    python3 purge_low_value.py --plan <judge.jsonl> --apply    # 落库，自动备份

口径：
    - 默认 dry-run；--apply 前先 wal_checkpoint(FULL) + 复制整库备份
    - 报告含被删卡 front/back 全文 + 其复习行全文（可人工还原）
    - 复习行、card_topics 行随外键级联删除；删后必须校验孤儿行 = 0

路径依赖：
    - 本脚本 BASE 常量固定为「AI学习小组app」仓库绝对路径，DB 默认取
      BASE/instance/aistudy.sqlite3、报告默认落 BASE/backups/<日期>-lowvalue/。
      在其它机器运行前请把 BASE 改成该机仓库路径（或直接用 --db / --outdir 覆盖）。
"""
import argparse
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
DB = BASE / "instance" / "aistudy.sqlite3"


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def load_plan(path: Path) -> list[dict]:
    items = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        r = json.loads(line)
        if r.get("keep") is False and r.get("id"):
            items.append({"id": r["id"], "front": r.get("front", ""), "reason": r.get("reason", ""),
                          "category": r.get("category", "")})
    if not items:
        raise SystemExit("计划为空：没有 keep=false 的条目")
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="清退低价值知识卡片")
    ap.add_argument("--plan", required=True, help="LLM 判定结果 JSONL（取 keep=false 的行）")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--outdir", default=str(BASE / "backups" / "2026-09-24-lowvalue"))
    args = ap.parse_args()

    plan = load_plan(Path(args.plan))
    db, outdir = Path(args.db), Path(args.outdir)
    con = connect(db)
    before = con.execute("SELECT COUNT(*) FROM knowledge_cards").fetchone()[0]
    print(f"{'落库' if args.apply else 'DRY-RUN'}｜库 {db}")
    print(f"计划删卡 {len(plan)} 张（当前 {before} 张）")

    backup_path = None
    if args.apply:
        outdir.mkdir(parents=True, exist_ok=True)
        con.execute("PRAGMA wal_checkpoint(FULL)")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = outdir / f"{db.name}.pre-lowvalue-purge-{stamp}.bak"
        shutil.copy2(db, backup_path)
        shutil.copy2(Path(args.plan), outdir / f"plan-lowvalue-{stamp}.jsonl")
        print(f"已备份：{backup_path}")

    detail, missing = [], 0
    for it in plan:
        row = con.execute("SELECT * FROM knowledge_cards WHERE id=?", (it["id"],)).fetchone()
        if not row:
            missing += 1
            continue
        revs = [dict(r) for r in con.execute(
            "SELECT * FROM knowledge_reviews WHERE card_id=?", (it["id"],)).fetchall()]
        topics = [dict(r) for r in con.execute(
            "SELECT * FROM card_topics WHERE card_id=?", (it["id"],)).fetchall()]
        detail.append({"card": dict(row), "reviews": revs, "topics": topics,
                       "reason": it["reason"], "category": it["category"]})
        if args.apply:
            con.execute("DELETE FROM knowledge_cards WHERE id=?", (it["id"],))
    if args.apply:
        con.commit()
    after = con.execute("SELECT COUNT(*) FROM knowledge_cards").fetchone()[0]
    orphans_r = con.execute(
        "SELECT COUNT(*) FROM knowledge_reviews r WHERE NOT EXISTS "
        "(SELECT 1 FROM knowledge_cards c WHERE c.id=r.card_id)").fetchone()[0]
    orphans_t = con.execute(
        "SELECT COUNT(*) FROM card_topics t WHERE NOT EXISTS "
        "(SELECT 1 FROM knowledge_cards c WHERE c.id=t.card_id)").fetchone()[0]
    print(f"  删卡 {len(detail)}｜缺卡 {missing}｜卡数 {before} → {after}｜孤儿 复习行 {orphans_r} / 主题行 {orphans_t}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = outdir / f"lowvalue-report-{stamp}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "applied": bool(args.apply), "db": str(db), "plan": args.plan,
        "backup": str(backup_path) if backup_path else None,
        "before": before, "after": after, "deleted": len(detail),
        "by_category": {c: sum(1 for d in detail if d["category"] == c)
                        for c in sorted({d["category"] for d in detail})},
        "detail": detail,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  报告：{report}（含被删卡与复习行全文，可回滚）")
    con.close()


if __name__ == "__main__":
    main()
