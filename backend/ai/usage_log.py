"""LLM 调用用量日志：每次成功调用追加一行 JSONL，供 Token 账单看板精确记账。"""
import json
import os
from datetime import datetime, timedelta, timezone

TZ8 = timezone(timedelta(hours=8))
DEFAULT_LOG = os.path.expanduser("~/.hermes/app-usage/aistudy.jsonl")


def log_usage(model, usage, feature="unknown", thinking=""):
    """追加一次 LLM 调用记录；任何异常都吞掉，绝不影响主流程。

    2026-10-01 起额外记 `reasoning_tokens` / `thinking`（成本纪律铁律 2）：没有它们，
    护栏 `llm_cost_guard.py` 就查不出「有人绕过统一入口在烧推理 token」。
    """
    try:
        path = os.environ.get("LLM_USAGE_LOG") or DEFAULT_LOG
        os.makedirs(os.path.dirname(path), exist_ok=True)
        u = usage or {}
        det = u.get("completion_tokens_details") or {}
        rec = {
            "timestamp": datetime.now(TZ8).isoformat(timespec="seconds"),
            "model": str(model or "unknown"),
            "feature": str(feature),
            "prompt_tokens": int(u.get("prompt_tokens") or 0),
            "prompt_cache_hit_tokens": int(u.get("prompt_cache_hit_tokens") or 0),
            "completion_tokens": int(u.get("completion_tokens") or 0),
            "total_tokens": int(u.get("total_tokens") or 0),
            "reasoning_tokens": int(det.get("reasoning_tokens") or u.get("reasoning_tokens") or 0),
            "thinking": str(thinking or "unknown"),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
