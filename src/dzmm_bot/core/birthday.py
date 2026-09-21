"""生日与入职纪念日的纯逻辑：只算日子，不碰数据库。

三件事：

1. `parse_birthday` 把玩家输入（`5-20` / `5/20` / `5月20日` / `1995-5-20`）解析成月日；
2. `matches` 判断"今天是不是这个日子"，并统一处理 **2/29 在平年按 2/28** 的口径；
3. `format_tenure` 把入职时间说成人话（`2 年 3 个月`）。

生日与入职周年共用这一套：它们的差别只在数据来源。
"""

from dataclasses import dataclass
from datetime import date, datetime
import re

#: 解析时可用的分隔符（`年/月/日` 会先被换成 `-`）。
_SEPARATORS = re.compile(r"[-/.\s、,，]+")


@dataclass(frozen=True)
class BirthdayInput:
    """一次解析结果；`year` 只有玩家主动写了才会有。"""

    month: int
    day: int
    year: int | None = None


def is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def days_in_month(month: int, year: int | None = None) -> int:
    if month == 2:
        return 29 if (year is None or is_leap_year(year)) else 28
    return (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)[month - 1]


def valid_month_day(month: int, day: int, year: int | None = None) -> bool:
    """月日必须是真实存在的组合；给了年份还要满足闰年规则。"""
    if not isinstance(month, int) or not isinstance(day, int):
        return False
    if not 1 <= month <= 12:
        return False
    if year is not None:
        if not isinstance(year, int) or not 1900 <= year <= 2100:
            return False
    return 1 <= day <= days_in_month(month, year)


def parse_birthday(text: str) -> BirthdayInput | None:
    """解析生日；无法解析就返回 `None`（调用方决定提示什么）。"""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    for token in ("年", "月", "日", "号"):
        raw = raw.replace(token, "-")
    parts = [part for part in _SEPARATORS.split(raw) if part]
    if len(parts) not in (2, 3):
        return None
    if any(not part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if len(numbers) == 3:
        year, month, day = numbers
        # 三段时只认"年份在前"：`5-20-1995` 这种一律拒绝，避免歧义
        if year < 1900:
            return None
    else:
        year, month, day = None, numbers[0], numbers[1]
    if not valid_month_day(month, day, year):
        return None
    return BirthdayInput(month=month, day=day, year=year)


def matches(
    month: int, day: int, today: date, *, shift_feb29: bool = True
) -> bool:
    """今天是不是这个日子；平年的 2/29 统一按 2/28 算。"""
    if shift_feb29 and (month, day) == (2, 29) and not is_leap_year(today.year):
        return (today.month, today.day) == (2, 28)
    return (today.month, today.day) == (month, day)


def occurrence_in_year(month: int, day: int, year: int) -> date:
    """某个日子在某年的实际发生日（平年的 2/29 落到 2/28）。"""
    if (month, day) == (2, 29) and not is_leap_year(year):
        return date(year, 2, 28)
    return date(year, month, day)


def next_occurrence(month: int, day: int, today: date) -> date:
    """下一次过这个日子是哪天（今天算今天）。"""
    candidate = occurrence_in_year(month, day, today.year)
    if candidate < today:
        candidate = occurrence_in_year(month, day, today.year + 1)
    return candidate


def format_tenure(joined_at: datetime | date, today: date) -> str:
    """工龄：`2 年 3 个月` / `3 个月` / `不到 1 个月`。"""
    start = joined_at.date() if isinstance(joined_at, datetime) else joined_at
    months = (today.year - start.year) * 12 + (today.month - start.month)
    if today.day < start.day:
        months -= 1
    if months <= 0:
        return "不到 1 个月"
    years, remainder = divmod(months, 12)
    if years and remainder:
        return f"{years} 年 {remainder} 个月"
    if years:
        return f"{years} 年"
    return f"{remainder} 个月"


def parse_visibility(text: str) -> str | None:
    """从输入里认「公开 / 不公开」；没写就返回 `None`（保持原样）。"""
    if not isinstance(text, str):
        return None
    normalized = text.strip()
    for token in ("不公开", "隐藏", "私密"):
        if token in normalized:
            return "private"
    for token in ("公开", "可公开"):
        if token in normalized:
            return "public"
    return None


def strip_visibility(text: str) -> str:
    """把可见性关键词从日期输入里摘掉，剩下的才是日期。"""
    if not isinstance(text, str):
        return ""
    for token in ("不公开", "隐藏", "私密", "公开", "可显示", "可公开"):
        text = text.replace(token, " ")
    return text.strip()
