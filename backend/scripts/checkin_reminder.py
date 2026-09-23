#!/usr/bin/env python3
"""每晚 19:00–23:00 阶梯式未达标提醒（NOTIF-005/009）。

本机直连库，不经 HTTP。收件人 = role='student' + is_active=1 + 非测试号 +
今日未达标 + 未关闭每晚提醒（`remind_daily`，无 prefs 记录视为开）。
站内通知一律落库（App 内通知中心可见）；Web Push 只到「已授权订阅」的学生——
订阅行的存在与否本身就代表他点过设置页的「打开提醒」，故这里不按 push_enabled 过滤，
否则没开推送的学生会连站内提醒都收不到。
由 launchd `com.aistudy.checkin-reminder` 每天 19/20/21/22/23:00 触发，档位按当前小时推导。
"""
import argparse
import logging
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]  # backend/scripts -> backend -> repo 根
sys.path.insert(0, str(BASE / "backend"))

LOG_PATH = BASE / "logs" / "checkin-reminder.log"


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip())


def eligible_students(con) -> list:
    """当日可提醒学生：在用学生（非测试号由调用方排除）+ 未关闭每晚提醒。

    无 notification_prefs 记录时按默认「开」处理（COALESCE 1），
    否则新学生永远收不到提醒（prefs 行是懒创建的）。
    """
    return con.execute(
        "SELECT u.id, u.display_name, u.username FROM users u"
        " LEFT JOIN notification_prefs np ON np.user_id=u.id"
        " WHERE u.role='student' AND u.is_active=1"
        " AND COALESCE(np.remind_daily, 1)=1"
    ).fetchall()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="每晚阶梯式未达标提醒")
    parser.add_argument("--slot", choices=sorted(("L1", "L2", "L3", "L4", "L5")), default=None)
    args = parser.parse_args(argv)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("checkin-reminder")

    _load_env(BASE / ".env")

    from ai.reminder_copy import reminder_copy, slot_for_hour
    from app import create_app
    from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED
    from data import checkin, timeutil
    from data.db import get_db
    from services.notify import EXCLUDED_USERNAMES, notify_users

    hour = timeutil.shanghai_now().hour
    slot = args.slot or slot_for_hour(hour)
    if slot is None:
        msg = f"[checkin_reminder] skip hour={hour}"
        log.info(msg)
        print(msg)
        return 0

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    today = timeutil.today_str()
    sent = 0
    absent = []  # 未达标学生名（供 L3 教师名单）

    with app.app_context():
        con = get_db()
        rows = eligible_students(con)
        for r in rows:
            if r["username"] in EXCLUDED_USERNAMES:
                continue
            c = checkin.counts_today(con, r["id"])
            if c["cards"] >= TASK_CARDS_REQUIRED and c["questions"] >= TASK_QUESTIONS_REQUIRED:
                continue  # 达标即停：后续档位不再发
            info = checkin.streak_info(con, r["id"])
            name = r["display_name"] or r["username"]
            lapse = checkin.days_since_last_checkin(con, r["id"])
            copy = reminder_copy(name, info["streak"], c["cards"], c["questions"], slot, lapse)
            sent += notify_users(
                con, [r["id"]], "streak_reminder", copy["title"], copy["body"],
                image=copy["image"], ref_kind="reminder", ref_id=f"{today}#{slot}",
            )
            absent.append(name)

        # L3（21:00）追加教师端未达标名单（NOTIF-009）
        if slot == "L3" and absent:
            teachers = con.execute(
                "SELECT id, username FROM users WHERE role='teacher' AND is_active=1"
            ).fetchall()
            tids = [t["id"] for t in teachers if t["username"] not in EXCLUDED_USERNAMES]
            if tids:
                names = "、".join(absent[:5]) + ("等" if len(absent) > 5 else "")
                body = f"今天还有 {len(absent)} 人没达标：{names}。快去催一下～"
                sent += notify_users(
                    con, tids, "absent_digest", "📋 今日未达标名单", body,
                    ref_kind="reminder", ref_id=today,
                )

    msg = f"[checkin_reminder] {today} slot={slot} sent={sent}"
    log.info(msg)
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
