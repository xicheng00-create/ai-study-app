"""JWT 签发/解析与鉴权装饰器（对齐 Design Spec §3.1 / 横切 A）。

- jwt_required：解析 Bearer → g.user_id / g.role
- role_required：角色门禁
- user_scope：资源归属校验（越权读 403，F9）
"""
import functools
from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app, g, request
from middleware.errors import e_auth, e_forbidden, e_role

_ALGO = "HS256"


def _secret():
    return current_app.config.get("JWT_SECRET") or current_app.config["SECRET_KEY"]


def make_token(user_id: str, role: str) -> str:
    ttl = current_app.config.get("ACCESS_TOKEN_TTL_HOURS", 12)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=ttl),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_token(token: str):
    return jwt.decode(token, _secret(), algorithms=[_ALGO])


def _load_user(user_id: str):
    from data.db import get_db

    con = get_db()
    row = con.execute(
        "SELECT id, role, is_active FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row


def jwt_required(fn):
    """解析 Authorization: Bearer <jwt>，注入 g.user_id / g.role。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return e_auth("缺少 Bearer Token")
        token = auth[7:].strip()
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            return e_auth("Token 已过期")
        except jwt.InvalidTokenError:
            return e_auth("Token 无效")
        row = _load_user(payload["sub"])
        if row is None or not row["is_active"]:
            return e_auth("账号不存在或已停用")
        g.user_id = row["id"]
        g.role = row["role"]
        return fn(*args, **kwargs)

    return wrapper


def role_required(role: str):
    """要求 g.role == role，需在 jwt_required 之后使用。"""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if getattr(g, "role", None) != role:
                return e_role()
            return fn(*args, **kwargs)

        return wrapper

    return deco


def user_scope(fn):
    """校验路径参数 user_id == g.user_id（学生读操作自动归属，F9）。"""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = kwargs.get("user_id") or (request.view_args or {}).get("user_id")
        if user_id is not None and user_id != g.user_id:
            return e_forbidden("只能访问本人数据")
        return fn(*args, **kwargs)

    return wrapper
