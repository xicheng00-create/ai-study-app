"""Web Push（VAPID）发送封装（NOTIF-002）。

降级优先：无 VAPID 密钥 / 无订阅 / 发送异常 → 只落站内，绝不 500。
收到 404/410（订阅已失效）→ 删除该订阅。

⚠️ pywebpush 的 `data` 契约 = **已序列化的 str/bytes**；直传 dict 会在本地加密阶段抛
`KeyError: slice(0, 4079, None)`（v2.4.0~v2.9.0 推送 100% 静默失败的根因）。
"""
import json
import logging

from config import (
    VAPID_PRIVATE_KEY,
    VAPID_PUBLIC_KEY,
    VAPID_SUBJECT,
)
from data import models

log = logging.getLogger("aistudy.push")


def _webpush(subscription: dict, payload) -> bool:
    """推送单条；返回是否成功（异常一律吞掉降级，由上层决定是否记 last_ok_at）。"""
    from pywebpush import WebPushException, webpush

    # 已序列化的 str/bytes 才能进加密层；dict/其它 → 先 json.dumps
    data = payload if isinstance(payload, (str, bytes)) else json.dumps(payload, ensure_ascii=False)
    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
            },
            data=data,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": VAPID_SUBJECT},
        )
    except WebPushException as exc:
        # 404/410：订阅已失效，由上层删除
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            raise _SubscriptionGone(subscription["endpoint"])
        log.warning("webpush send failed (%s): %s", status, exc)
        return False
    except Exception as exc:  # noqa: BLE001 - 推送异常绝不向上冒泡
        log.warning("webpush send error: %s", exc)
        return False
    return True


class _SubscriptionGone(Exception):
    def __init__(self, endpoint):
        self.endpoint = endpoint
        super().__init__(f"subscription gone: {endpoint}")


def subscribed_user_ids(con) -> set:
    """已存在推送订阅行的用户 id 集合（NOTIF-010 状态判据 = 订阅存在性）。"""
    rows = con.execute("SELECT DISTINCT user_id FROM push_subscriptions").fetchall()
    return {r["user_id"] for r in rows}


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
            ok = _webpush(dict(s), payload)
        except _SubscriptionGone as exc:
            # 订阅失效（Apple 返回 404/410）删行必须留痕：否则「曾经开过、后来失效」与
            # 「从未开过」在库里长得一模一样，学生报「没收到通知」时无法归因
            # （2026-09-26 周大维尼 / 5onghan 排查：分不清二者，只能靠猜）。
            log.warning(
                "订阅失效（HTTP 404/410）→ 删除订阅行 sub=%s user=%s endpoint=%.56s",
                s["id"], s["user_id"], exc.endpoint,
            )
            con.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (exc.endpoint,))
            continue
        # 只有真投递成功才记 last_ok_at（曾无条件写入 → 失败也被记为「最近成功」）
        if ok:
            con.execute(
                "UPDATE push_subscriptions SET last_ok_at=? WHERE id=?", (models.utcnow(), s["id"])
            )
    con.commit()
