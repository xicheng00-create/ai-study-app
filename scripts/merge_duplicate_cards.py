#!/usr/bin/env python3
"""合并「重复知识点」卡片：按合并计划改写保留卡正文、迁移复习态、删除重复卡。

背景（2026-09-22）：全库 2384 张卡片中存在大量同一知识点的重复卡（确认 138 组：同章 131、跨章 7）。
`rebuild_cards.py --dedupe-db` 的判据是「词元 Jaccard≥0.85 且数字集合相同」，
会漏掉「同问句不同主体」（如四家 IDE 插件同模板）、也会漏掉措辞差异大的真重复，
且**从未做过跨章比较**。本次改用「按 sub_concept 候选召回 → LLM 分组 → 对抗式复核 →
信息整合 → 忠实度校验」的流程产出合并计划，由本脚本落地执行。

用法：
    python3 scripts/merge_duplicate_cards.py --plan <plan.json>            # dry-run（默认）
    python3 scripts/merge_duplicate_cards.py --plan <plan.json> --apply    # 落库，自动备份
    python3 scripts/merge_duplicate_cards.py --plan <plan.json> --db /tmp/x.sqlite3 --apply

计划文件格式（JSON 数组）：
    [{"keep_id": "<保留卡 id>", "delete_ids": ["<重复卡 id>", ...],
      "new_front": "<整合后问句，空则不改>", "new_back": "<整合后答案，空则不改>"}]

复习态合并口径（保住学生进度，不产生孤儿行）：
    每卡每生一行（UNIQUE(card_id, user_id)）。重复卡的复习行按学生迁移到保留卡：
    - 保留卡已无该生行 → 直接改 card_id（进度无损）；
    - 已有一行 → 两行合一：learn_count 取大、status 取更进阶、last_review_at 取晚、
      next_review_at 取早（更保守，宁可早复习）。
"""
import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
DB = BASE / "instance" / "aistudy.sqlite3"

STATUS_RANK = {"new": 0, "learning": 1, "reviewing": 2, "mastered": 3}


def connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path), timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=5000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def load_plan(path: Path) -> list[dict]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, list) or not plan:
        sys.exit("计划文件为空或格式错误（应为 JSON 数组）")
    keep_ids, del_ids = set(), set()
    for i, g in enumerate(plan):
        if not g.get("keep_id") or not g.get("delete_ids"):
            sys.exit(f"第 {i + 1} 组缺少 keep_id / delete_ids")
        if g["keep_id"] in del_ids:
            sys.exit(f"第 {i + 1} 组：保留卡同时出现在别组的删除列表")
        if keep_ids & set(g["delete_ids"]):
            sys.exit(f"第 {i + 1} 组：删除卡同时是别组的保留卡")
        keep_ids.add(g["keep_id"])
        del_ids |= set(g["delete_ids"])
    return plan


def backup(db: Path, outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = outdir / f"{db.name}.pre-dedup-{stamp}.bak"
    con = connect(db)
    con.execute("PRAGMA wal_checkpoint(FULL)")
    con.close()
    shutil.copy2(db, dst)
    return dst


def merge_reviews(con, dup_id: str, keep_id: str, stat: dict) -> None:
    """把重复卡的复习行并到保留卡（同学生两行合一，取更进阶的一份）。"""
    for rev in con.execute("SELECT * FROM knowledge_reviews WHERE card_id=?", (dup_id,)).fetchall():
        has = con.execute("SELECT * FROM knowledge_reviews WHERE card_id=? AND user_id=?",
                          (keep_id, rev["user_id"])).fetchone()
        if not has:
            con.execute("UPDATE knowledge_reviews SET card_id=? WHERE id=?", (keep_id, rev["id"]))
            stat["reviews_moved"] += 1
            continue
        a, b = dict(has), dict(rev)
        win, lose = (a, b) if (a["learn_count"], STATUS_RANK.get(a["status"], 0)) >= \
            (b["learn_count"], STATUS_RANK.get(b["status"], 0)) else (b, a)
        con.execute(
            """UPDATE knowledge_reviews
               SET learn_count=?, status=?, last_review_at=?, next_review_at=?
               WHERE id=?""",
            (max(a["learn_count"], b["learn_count"]),
             win["status"] if STATUS_RANK.get(win["status"], 0) >= STATUS_RANK.get(lose["status"], 0) else lose["status"],
             max(a["last_review_at"] or "", b["last_review_at"] or "") or None,
             min(a["next_review_at"], b["next_review_at"]),
             win["id"]))
        con.execute("DELETE FROM knowledge_reviews WHERE id=?", (lose["id"],))
        stat["reviews_merged"] += 1


def apply_plan(con, plan: list[dict], write: bool) -> dict:
    stat = {"groups": len(plan), "cards_deleted": 0, "reviews_moved": 0,
            "reviews_merged": 0, "texts_updated": 0, "missing_keep": 0, "missing_dup": 0}
    detail = []
    for g in plan:
        keep = con.execute("SELECT * FROM knowledge_cards WHERE id=?", (g["keep_id"],)).fetchone()
        if not keep:
            stat["missing_keep"] += 1
            continue
        dups = []
        for did in g["delete_ids"]:
            row = con.execute("SELECT * FROM knowledge_cards WHERE id=?", (did,)).fetchone()
            if row:
                dups.append(row)
            else:
                stat["missing_dup"] += 1
        if not dups:
            continue
        if write:
            # 先留复习行全文（合并/级联都会改动它们，回滚要靠这份快照）
            dup_reviews = [dict(r) for d in dups for r in con.execute(
                "SELECT * FROM knowledge_reviews WHERE card_id=?", (d["id"],)).fetchall()]
            for dup in dups:
                merge_reviews(con, dup["id"], keep["id"], stat)
            for dup in dups:
                con.execute("DELETE FROM knowledge_cards WHERE id=?", (dup["id"],))
                stat["cards_deleted"] += 1
            nf = (g.get("new_front") or keep["front"]).strip()
            nb = (g.get("new_back") or keep["back"]).strip()
            if nf != keep["front"] or nb != keep["back"]:
                con.execute("UPDATE knowledge_cards SET front=?, back=? WHERE id=?", (nf, nb, keep["id"]))
                stat["texts_updated"] += 1
        else:
            dup_reviews = [dict(r) for d in dups for r in con.execute(
                "SELECT * FROM knowledge_reviews WHERE card_id=?", (d["id"],)).fetchall()]
        detail.append({
            "keep_id": keep["id"], "chapter_id": keep["chapter_id"],
            "old_front": keep["front"], "old_back": keep["back"],
            "new_front": (g.get("new_front") or keep["front"]).strip(),
            "new_back": (g.get("new_back") or keep["back"]).strip(),
            "deleted_cards": [dict(d) for d in dups],
            "deleted_reviews": dup_reviews,
        })
    return {"stat": stat, "detail": detail}


def main() -> None:
    ap = argparse.ArgumentParser(description="合并重复知识点卡片")
    ap.add_argument("--plan", required=True, help="合并计划 JSON")
    ap.add_argument("--db", default=str(DB), help="目标库（默认生产库）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认 dry-run）")
    ap.add_argument("--outdir", default=str(BASE / "backups" / "2026-09-22-cards"),
                    help="备份与报告目录")
    args = ap.parse_args()

    plan = load_plan(Path(args.plan))
    db = Path(args.db)
    outdir = Path(args.outdir)
    con = connect(db)

    before = con.execute("SELECT COUNT(*) FROM knowledge_cards").fetchone()[0]
    print(f"{'落库' if args.apply else 'DRY-RUN'}｜库 {db}")
    print(f"计划 {len(plan)} 组，预计删卡 {sum(len(g['delete_ids']) for g in plan)} 张"
          f"（当前 {before} 张）")

    backup_path = None
    if args.apply:
        backup_path = backup(db, outdir)
        print(f"已备份：{backup_path}")
        src_plan = Path(args.plan)
        shutil.copy2(src_plan, outdir / f"plan-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json")

    result = apply_plan(con, plan, args.apply)
    if args.apply:
        con.commit()
    else:
        con.rollback()
    stat = result["stat"]
    print(f"  组 {stat['groups']}｜删卡 {stat['cards_deleted']}｜改正文 {stat['texts_updated']}｜"
          f"复习行迁移 {stat['reviews_moved']}｜复习行合一 {stat['reviews_merged']}｜"
          f"缺卡 keep {stat['missing_keep']} / dup {stat['missing_dup']}")

    after = con.execute("SELECT COUNT(*) FROM knowledge_cards").fetchone()[0]
    orphans = con.execute(
        "SELECT COUNT(*) FROM knowledge_reviews r WHERE NOT EXISTS "
        "(SELECT 1 FROM knowledge_cards c WHERE c.id=r.card_id)").fetchone()[0]
    print(f"  卡数 {before} → {after}｜孤儿复习行 {orphans}")
    if args.apply and orphans:
        print("  ⚠ 存在孤儿复习行，请检查！")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = outdir / f"dedup-report-{stamp}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "applied": bool(args.apply), "db": str(db), "plan": args.plan,
        "backup": str(backup_path) if backup_path else None,
        "before": before, "after": after, "stat": stat, "detail": result["detail"],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  报告：{report}（含被删卡与复习行全文，可回滚）")
    con.close()


if __name__ == "__main__":
    main()
