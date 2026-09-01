"""间隔复习状态机（Design Spec §5.3/§5.4，PROG-006）。

review_items：pending ─[到期+完成]─► done；
答对 interval *= 3（1→3→7 封顶），答错重置 1。
"""
from datetime import datetime, timedelta, timezone

MAX_INTERVAL = 7


def next_interval(correct: bool, current: int) -> int:
    """答对顺延 1→3→7；答错重置 1。"""
    if correct:
        return min(max(current * 3, 1), MAX_INTERVAL)
    return 1


def next_review_at_iso(interval_days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=interval_days)).isoformat()
