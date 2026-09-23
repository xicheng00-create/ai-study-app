"""站内通知中心 + Web Push 订阅 Blueprint（NOTIF-001~008，师生共用）。"""
from auth.jwt_utils import jwt_required
from config import VAPID_PUBLIC_KEY
from data import models
from data.db import get_db
from flask import Blueprint, g, request
from middleware.errors import e_input, ok

notify_bp = Blueprint("notify_bp", __name__, url_prefix="/api/notifications")


def _item(row) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "body": row["body"],
        "image": row["image"] or "",
        "ref_kind": row["ref_kind"] or "",
        "ref_id": row["ref_id"] or "",
        "is_read": bool(row["is_read"]),
        "created_at": row["created_at"],
    }


def _ensure_prefs(con, user_id) -> dict:
    row = con.execute(
        "SELECT * FROM notification_prefs WHERE user_id=?", (user_id,)
    ).fetchone()
    if row is None:
        con.execute(
            "INSERT INTO notification_prefs (user_id, push_enabled, remind_daily, updated_at)"
            " VALUES (?, 0, 1, ?)",
            (user_id, models.utcnow()),
        )
        con.commit()
        return {"push_enabled": False, "remind_daily": True}
    return {"push_enabled": bool(row["push_enabled"]), "remind_daily": bool(row["remind_daily"])}


@notify_bp.route("", methods=["GET"])
@jwt_required
def list_notifications():
    con = get_db()
    rows = con.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC, rowid DESC LIMIT 30",
        (g.user_id,),
    ).fetchall()
    unread = con.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (g.user_id,)
    ).fetchone()["c"]
    return ok({"notifications": [_item(r) for r in rows], "unread": unread})


@notify_bp.route("/unread", methods=["GET"])
@jwt_required
def unread():
    """铃铛轮询用，轻量、不挂 LLM 限流。"""
    con = get_db()
    unread = con.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id=? AND is_read=0", (g.user_id,)
    ).fetchone()["c"]
    return ok({"unread": unread})


@notify_bp.route("/read", methods=["POST"])
@jwt_required
def mark_read():
    data = request.get_json(silent=True) or {}
    con = get_db()
    if data.get("all"):
        con.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (g.user_id,))
    else:
        ids = data.get("ids") or []
        if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids):
            return e_input("ids 需为字符串数组")
        if ids:
            ph = ",".join("?" * len(ids))
            con.execute(
                f"UPDATE notifications SET is_read=1 WHERE user_id=? AND id IN ({ph})",
                (g.user_id, *ids),
            )
    con.commit()
    return ok({"updated": 1})


@notify_bp.route("/push/subscribe", methods=["POST"])
@jwt_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    p256dh = (data.get("p256dh") or "").strip()
    auth = (data.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return e_input("缺少订阅字段 endpoint/p256dh/auth")
    con = get_db()
    now = models.utcnow()
    con.execute(
        "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth, user_agent, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id, p256dh=excluded.p256dh,"
        " auth=excluded.auth, user_agent=excluded.user_agent, created_at=excluded.created_at",
        (models.new_id(), g.user_id, endpoint, p256dh, auth,
         request.headers.get("User-Agent", ""), now),
    )
    con.execute(
        "INSERT INTO notification_prefs (user_id, push_enabled, remind_daily, updated_at)"
        " VALUES (?, 1, 1, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET push_enabled=1, updated_at=excluded.updated_at",
        (g.user_id, now),
    )
    con.commit()
    return ok({"subscribed": True})


@notify_bp.route("/push/unsubscribe", methods=["POST"])
@jwt_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("endpoint") or "").strip()
    con = get_db()
    if endpoint:
        con.execute(
            "DELETE FROM push_subscriptions WHERE endpoint=? AND user_id=?", (endpoint, g.user_id)
        )
    else:
        con.execute("DELETE FROM push_subscriptions WHERE user_id=?", (g.user_id,))
    con.execute(
        "UPDATE notification_prefs SET push_enabled=0, updated_at=? WHERE user_id=?",
        (models.utcnow(), g.user_id),
    )
    con.commit()
    return ok({"unsubscribed": True})


@notify_bp.route("/prefs", methods=["GET"])
@jwt_required
def get_prefs():
    con = get_db()
    prefs = _ensure_prefs(con, g.user_id)
    from services.push import subscribed_user_ids

    # NOTIF-010：前端用 has_push_sub（订阅存在性）与 push_enabled 一起决定引导卡文案
    prefs["has_push_sub"] = g.user_id in subscribed_user_ids(con)
    return ok(prefs)


@notify_bp.route("/prefs", methods=["POST"])
@jwt_required
def set_prefs():
    data = request.get_json(silent=True) or {}
    con = get_db()
    cur = _ensure_prefs(con, g.user_id)
    push_enabled = int(bool(data.get("push_enabled", cur["push_enabled"])))
    remind_daily = int(bool(data.get("remind_daily", cur["remind_daily"])))
    con.execute(
        "INSERT INTO notification_prefs (user_id, push_enabled, remind_daily, updated_at)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT(user_id) DO UPDATE SET push_enabled=excluded.push_enabled,"
        " remind_daily=excluded.remind_daily, updated_at=excluded.updated_at",
        (g.user_id, push_enabled, remind_daily, models.utcnow()),
    )
    con.commit()
    return ok({"push_enabled": bool(push_enabled), "remind_daily": bool(remind_daily)})


@notify_bp.route("/vapid-public-key", methods=["GET"])
@jwt_required
def vapid_public_key():
    return ok({"key": VAPID_PUBLIC_KEY})
