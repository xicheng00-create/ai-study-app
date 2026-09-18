#!/usr/bin/env python3
"""19:00 未打卡提醒（NOTIF-005）。

本机直连库，不经 HTTP。只发给：role='student' + is_active=1 + 非测试号 +
今日未达标 + notification_prefs.push_enabled=1 且 remind_1900=1。
由 launchd `com.aistudy.checkin-reminder` 每天 19:00 触发（只写脚本与 plist，不安装）。
"""
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


def main() -> int:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_PATH), level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("checkin-reminder")

    _load_env(BASE / ".env")

    from ai.reminder_copy import reminder_copy
    from app import create_app
    from config import TASK_CARDS_REQUIRED, TASK_QUESTIONS_REQUIRED
    from data import checkin, timeutil
    from data.db import get_db
    from services.notify import EXCLUDED_USERNAMES, notify_users

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    today = timeutil.today_str()
    sent = 0

    with app.app_context():
        con = get_db()
        rows = con.execute(
            "SELECT u.id, u.display_name, u.username FROM users u"
            " JOIN notification_prefs np ON np.user_id=u.id"
            " WHERE u.role='student' AND u.is_active=1"
            " AND np.push_enabled=1 AND np.remind_1900=1"
        ).fetchall()
        for r in rows:
            if r["username"] in EXCLUDED_USERNAMES:
                continue
            c = checkin.counts_today(con, r["id"])
            if c["cards"] >= TASK_CARDS_REQUIRED and c["questions"] >= TASK_QUESTIONS_REQUIRED:
                continue
            info = checkin.streak_info(con, r["id"])
            name = r["display_name"] or r["username"]
            copy = reminder_copy(name, info["streak"], c["cards"], c["questions"])
            sent += notify_users(
                con, [r["id"]], "streak_reminder", copy["title"], copy["body"],
                image=copy["image"], ref_kind="reminder", ref_id=today,
            )

    msg = f"[checkin_reminder] {today} sent={sent}"
    log.info(msg)
    print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
