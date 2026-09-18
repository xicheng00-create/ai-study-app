"""Web Push（VAPID）发送封装（NOTIF-002）。

降级优先：无 VAPID 密钥 / 无订阅 / 发送异常 → 只落站内，绝不 500。
收到 404/410（订阅已失效）→ 删除该订阅。
"""
import logging

from config import (
    VAPID_PRIVATE_KEY,
    VAPID_PUBLIC_KEY,
    VAPID_SUBJECT,
)
from data import models

log = logging.getLogger("aistudy.push")


def _webpush(subscription: dict, payload: dict) -> None:
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            },
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
    except WebPushException as exc:
        # 404/410：订阅已失效，由上层删除
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise _SubscriptionGone(subscription["endpoint"])
        log.warning("webpush send failed (%s): %s", status, exc)
    except Exception as exc:  # noqa: BLE001 - 推送异常绝不向上冒泡
        log.warning("webpush send error: %s", exc)


class _SubscriptionGone(Exception):
    def __init__(self, endpoint):
        self.endpoint = endpoint
        super().__init__(f"subscription gone: {endpoint}")


def send_push(con, user_ids, payload: dict) -> None:
    """给一组用户推送；无密钥/无订阅静默跳过，失败降级，失效订阅删除。"""
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return
    if not user_ids:
        return

    ph = ",".join("?" * len(user_ids))
    subs = con.execute(
        f"SELECT id, user_id, endpoint, p256dh, auth FROM push_subscriptions"
        f" WHERE user_id IN ({ph})",
        (*user_ids,),
    ).fetchall()
    for s in subs:
        try:
            _webpush(dict(s), payload)
        except _SubscriptionGone as exc:
            con.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (exc.endpoint,))
            continue
        con.execute(
            "UPDATE push_subscriptions SET last_ok_at=? WHERE id=?", (models.utcnow(), s["id"])
        )
    con.commit()
