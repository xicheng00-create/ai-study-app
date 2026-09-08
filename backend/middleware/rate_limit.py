"""内存级 LLM 调用限速（NFR-006：每用户 ≤60/天）。

单进程 waitress 下足够；4 人规模无需 Redis。
"""
import functools
import threading
import time

from flask import g, request

from middleware.errors import e_rate

_lock = threading.Lock()
# (user_id, endpoint) -> [unix timestamps]
# ⚠️ 桶必须带 endpoint 维度：若所有端点共享同一 user_id 桶，
# 翻卡/拉列表这类高频非 LLM 请求会挤占对话/出题的 LLM 额度，
# 导致学生没聊几句全 app 就 429「操作过于频繁」（2026-09-08 hermesstu 血泪）。
_buckets = {}


def _prune(key, window):
    now = time.time()
    _buckets[key] = [t for t in _buckets.get(key, []) if now - t < window]


def rate_limit(limit=60, window=86400):
    """每用户每端点窗口内最多 limit 次；超限返回 429。"""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            # request.endpoint 形如 'knowledge_bp.cards'：同一视图函数共享一桶，不同端点互不挤占
            user_id = getattr(g, "user_id", request.remote_addr or "anon")
            key = f"{user_id}:{request.endpoint or 'anon'}"
            with _lock:
                _prune(key, window)
                if len(_buckets.get(key, [])) >= limit:
                    return e_rate()
                _buckets.setdefault(key, []).append(time.time())
            return fn(*args, **kwargs)

        return wrapper

    return deco
