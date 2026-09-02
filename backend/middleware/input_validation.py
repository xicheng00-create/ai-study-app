"""输入长度校验（横切 A：入参长度限制）。

长度上限对齐 PRD 字段（用户名/密码/内容等），防超大 payload。
"""
from middleware.errors import e_input

_LIMITS = {
    "username": 64,
    "display_name": 64,
    "password": 128,
    "grade": 32,
    "folder": 64,
    "name": 128,
    "title": 128,
    "content": 4000,
    "answer": 4000,
    "url": 2048,
    "goal": 500,
    "description": 2000,
    "platform": 32,
    "milestone": 200,
}


def require_fields(data: dict, fields: tuple):
    """校验必填字段存在且为字符串。"""
    for f in fields:
        if f not in data or not isinstance(data[f], str) or not data[f].strip():
            return e_input(f"缺少字段 {f}")
    return None


def check_len(field: str, value):
    """超长则返回错误，否则 None。"""
    limit = _LIMITS.get(field)
    if limit is not None and isinstance(value, str) and len(value) > limit:
        return e_input(f"字段 {field} 超出长度限制")
    return None
