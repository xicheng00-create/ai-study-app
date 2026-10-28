#!/usr/bin/env python3
"""补发冰冻（REQ-ICE-01）：按用户名追加一条人工补发记录，附原因，便于对账。

余额 = 2（初始）+ 每 5 天里程碑 − 已消耗 + 补发合计。历史 freeze 行永不改动，
所以补发不会伪造「某天被冻住」的历史，也不会误把连胜判成已断。

用法：
    python3 scripts/grant_freeze.py --user Winnie --count 1 --reason "故障补偿"
"""
import argparse
import sys
from pathlib import Path

BASE = Path("/Users/xicheng/WorkBuddy/AI学习小组app")
sys.path.insert(0, str(BASE / "backend"))

from app import create_app  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True, help="username 或 display_name")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--reason", default="人工补发")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        from data import checkin, models
        from data.db import get_db, init_db
        init_db()
        con = get_db()
        row = con.execute(
            "SELECT id, username, display_name FROM users WHERE username=? OR display_name=?",
            (args.user, args.user),
        ).fetchone()
        if not row:
            print("找不到用户:", args.user)
            return 2
        before = checkin.freeze_status(con, row["id"])
        print("用户 %s（%s）当前余额 %d（granted %d / used %d）"
              % (row["display_name"], row["username"], before["available"],
                 before["granted"], before["used"]))
        if not args.apply:
            print("预演：将补发 %d 个，余额 → %d。加 --apply 落库。"
                  % (args.count, before["available"] + args.count))
            return 0
        con.execute(
            "INSERT INTO freeze_grants (id,user_id,count,reason,created_at) VALUES (?,?,?,?,?)",
            (models.new_id(), row["id"], max(1, args.count), args.reason, models.utcnow()),
        )
        con.commit()
        after = checkin.freeze_status(con, row["id"])
        print("已补发 %d 个（原因：%s）；余额 %d → %d"
              % (args.count, args.reason, before["available"], after["available"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
