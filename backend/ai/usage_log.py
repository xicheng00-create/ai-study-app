"""LLM 调用用量日志：每次成功调用追加一行 JSONL，供 Token 账单看板精确记账。"""
import json
import os
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
DEFAULT_LOG = os.path.expanduser("~/.hermes/app-usage/aistudy.jsonl")


def log_usage(model, usage, feature="unknown"):
    """追加一次 LLM 调用记录；任何异常都吞掉，绝不影响主流程。"""
    try:
        path = os.environ.get("LLM_USAGE_LOG") or DEFAULT_LOG
        os.makedirs(os.path.dirname(path), exist_ok=True)
        u = usage or {}
        rec = {
            "timestamp": datetime.now(TZ8).isoformat(timespec="seconds"),
            "model": str(model or "unknown"),
            "feature": str(feature),
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "prompt_cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
