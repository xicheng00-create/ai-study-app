"""时区工具：全 App「今天/今日」一律按 UTC+8（Asia/Shanghai）日历日判定。

存储为 UTC ISO 8601，需转时区后比日期（任务书定义 C）。
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def shanghai_now() -> datetime:
    """当前上海时间（aware）。"""
    return datetime.now(SHANGHAI)


def today_str() -> str:
    """今天（UTC+8）的日历日，形如 YYYY-MM-DD。"""
    return shanghai_now().strftime("%Y-%m-%d")


def to_shanghai(iso) -> datetime | None:
    """UTC/naive ISO → 上海 aware datetime；非法返回 None。"""
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(SHANGHAI)


def shanghai_date(iso) -> str:
    """ISO 时间戳 → 上海日历日（YYYY-MM-DD）；非法返回空串。"""
    dt = to_shanghai(iso)
    return dt.strftime("%Y-%m-%d") if dt else ""
