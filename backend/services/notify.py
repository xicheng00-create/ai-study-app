"""站内通知统一入口（NOTIF-001/002）。

notify_users()：先落库（幂等，按 user/type/ref_id/当天 去重）→ 再 Web Push。
发布类通知统一排除测试号（沿用 class_bp.EXCLUDED_USERNAMES）。
"""
from config import PUBLIC_BASE_URL
from data import models, timeutil

from services import push

# 与 class_bp.EXCLUDED_USERNAMES 保持一致（hermestest / hermesstu）。
# 全小写存储 + 比较处统一 .lower() 归一：生产库里用户名是小写 hermestest。
EXCLUDED_USERNAMES = ("hermestest", "hermesstu")


def active_student_ids(con) -> list[str]:
    """全体在用学生（role=student + is_active=1，排除测试号）。"""
    rows = con.execute(
        "SELECT id, username FROM users WHERE role='student' AND is_active=1"
    ).fetchall()
    return [r["id"] for r in rows if r["username"].lower() not in EXCLUDED_USERNAMES]


def _already_notified(con, user_id, ntype, ref_id) -> bool:
    today = timeutil.today_str()
    rows = con.execute(
        "SELECT created_at FROM notifications WHERE user_id=? AND type=? AND ref_id=?",
        (user_id, ntype, ref_id),
    ).fetchall()
    return any(timeutil.shanghai_date(r["created_at"]) == today for r in rows)


def notify_users(con, user_ids, ntype, title, body, image="", ref_kind="", ref_id="") -> int:
    """给一组用户发站内通知 + Web Push；返回实际落库条数（已去重）。"""
    if not user_ids:
        return 0

    now = models.utcnow()
    push_payload = {
        "title": title,
        "body": body,
        "data": {"url": "/", "type": ntype},
    }
    if image:
        push_payload["icon"] = PUBLIC_BASE_URL + image
        push_payload["image"] = PUBLIC_BASE_URL + image
    push_payload["badge"] = PUBLIC_BASE_URL + "/img/notify/notify-badge.png"

    to_push = []
    written = 0
    for uid in user_ids:
        if _already_notified(con, uid, ntype, ref_id):
            continue
        con.execute(
            "INSERT INTO notifications (id, user_id, type, title, body, image, ref_kind,"
            " ref_id, is_read, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (models.new_id(), uid, ntype, title, body, image, ref_kind, ref_id, now),
        )
        written += 1
        to_push.append(uid)

    con.commit()
    if to_push:
        try:
            push.send_push(con, to_push, push_payload)
        except Exception:  # noqa: BLE001 - 推送异常绝不向上冒泡，站内已落库
            import logging

            logging.getLogger("aistudy.notify").warning(
                "send_push failed for %s, notification already persisted", to_push
            )
    return written
