"""时间处理工具。

约定：数据库里存的一律是 UTC 的 ISO-8601 字符串（带 Z 后缀），
前端负责转换成浏览器本地时区显示。这样跨时区、夏令时都不会错。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S"


def utcnow() -> datetime:
    """当前 UTC 时间（带时区信息）。"""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """当前时间，ISO-8601 字符串。"""
    return to_iso(utcnow())


def to_iso(value: datetime | None) -> str:
    """datetime -> ISO 字符串（UTC）。"""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime(ISO_FORMAT) + "Z"


def parse_iso(value: str | None) -> datetime | None:
    """ISO 字符串 -> datetime；解析失败返回 None，不抛异常。"""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def from_timestamp(ts: float) -> str:
    """unix 时间戳 -> ISO 字符串。"""
    return to_iso(datetime.fromtimestamp(ts, tz=timezone.utc))


def start_of_day(value: datetime) -> datetime:
    """当天 00:00（保持原时区）。"""
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def add_days(value: datetime, days: int) -> datetime:
    return value + timedelta(days=days)


def add_minutes(value: datetime, minutes: int) -> datetime:
    return value + timedelta(minutes=minutes)


def is_past(value: str | None) -> bool:
    """给定时间是否已经过去。"""
    parsed = parse_iso(value)
    if parsed is None:
        return False
    return parsed < utcnow()


def is_future(value: str | None) -> bool:
    parsed = parse_iso(value)
    if parsed is None:
        return False
    return parsed > utcnow()


def seconds_between(start: str | None, end: str | None) -> float:
    """两个 ISO 时间之间的秒数，任意一个解析失败就返回 0。"""
    a, b = parse_iso(start), parse_iso(end)
    if a is None or b is None:
        return 0.0
    return (b - a).total_seconds()


def days_between(start: str | None, end: str | None) -> float:
    return seconds_between(start, end) / 86400.0


def humanize_duration(seconds: float) -> str:
    """把秒数变成「3 天 4 小时」这种中文描述。"""
    seconds = int(abs(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} 小时 {minutes} 分钟"
    days, hours = divmod(hours, 24)
    return f"{days} 天 {hours} 小时"


def deadline_state(deadline: str | None) -> str:
    """根据截止时间给出状态：none / open / soon / overdue。"""
    if not deadline:
        return "none"
    parsed = parse_iso(deadline)
    if parsed is None:
        return "none"
    remaining = (parsed - utcnow()).total_seconds()
    if remaining < 0:
        return "overdue"
    if remaining < 3 * 3600:
        return "soon"
    return "open"


def term_of(value: datetime | None = None) -> str:
    """根据日期推断学年学期，例如 2026-2027-1。

    9 月到次年 1 月是第一学期，2 月到 8 月是第二学期。
    """
    current = value or utcnow()
    year = current.year
    month = current.month
    if month >= 9:
        return f"{year}-{year + 1}-1"
    if month == 1:
        return f"{year - 1}-{year}-1"
    return f"{year - 1}-{year}-2"


def week_range(term: str, week: int) -> tuple[str, str]:
    """给定学期与周次，返回该周的起止日期（ISO）。"""
    try:
        start_year = int(term.split("-")[0])
    except (ValueError, IndexError):
        start_year = utcnow().year
    # 第一学期从 9 月 1 日算起，第二学期从 2 月 24 日算起
    if term.endswith("-1"):
        base = datetime(start_year, 9, 1, tzinfo=timezone.utc)
    else:
        base = datetime(start_year + 1, 2, 24, tzinfo=timezone.utc)
    begin = base + timedelta(weeks=week - 1)
    end = begin + timedelta(days=6)
    return to_iso(begin), to_iso(end)
