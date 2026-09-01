"""内存级 LLM 调用限速（NFR-006：每用户 ≤60/天）。

单进程 waitress 下足够；4 人规模无需 Redis。
"""
import functools
import threading
import time

from flask import g, request

from middleware.errors import e_rate

_lock = threading.Lock()
# user_id -> [unix timestamps]
_buckets = {}


def _prune(user_id, window):
    now = time.time()
    _buckets[user_id] = [t for t in _buckets.get(user_id, []) if now - t < window]


def rate_limit(limit=60, window=86400):
    """窗口内最多 limit 次；超限返回 429。"""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = getattr(g, "user_id", request.remote_addr or "anon")
            with _lock:
                _prune(user_id, window)
                if len(_buckets.get(user_id, [])) >= limit:
                    return e_rate()
                _buckets.setdefault(user_id, []).append(time.time())
            return fn(*args, **kwargs)

        return wrapper

    return deco
