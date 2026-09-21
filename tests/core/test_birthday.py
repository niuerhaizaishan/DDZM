from datetime import date, datetime
from zoneinfo import ZoneInfo

from dzmm_bot.core.birthday import (
    BirthdayInput,
    format_tenure,
    is_leap_year,
    matches,
    next_occurrence,
    occurrence_in_year,
    parse_birthday,
    parse_visibility,
    strip_visibility,
    valid_month_day,
)


BEIJING = ZoneInfo("Asia/Shanghai")


def test_parse_birthday_accepts_the_common_shapes():
    assert parse_birthday("5-20") == BirthdayInput(5, 20)
    assert parse_birthday("5/20") == BirthdayInput(5, 20)
    assert parse_birthday("05.20") == BirthdayInput(5, 20)
    assert parse_birthday("5月20日") == BirthdayInput(5, 20)
    assert parse_birthday(" 5 20 ") == BirthdayInput(5, 20)
    assert parse_birthday("1995-5-20") == BirthdayInput(5, 20, 1995)
    assert parse_birthday("1995年5月20日") == BirthdayInput(5, 20, 1995)


def test_parse_birthday_rejects_what_is_not_a_date():
    assert parse_birthday("") is None
    assert parse_birthday("生日") is None
    assert parse_birthday("13-1") is None
    assert parse_birthday("2-30") is None
    assert parse_birthday("4-31") is None
    assert parse_birthday("0-10") is None
    assert parse_birthday("5-20-1995") is None
    assert parse_birthday("5") is None
    assert parse_birthday("1995-5-20-1") is None


def test_parse_birthday_only_allows_feb_29_in_a_leap_year():
    assert parse_birthday("2-29") == BirthdayInput(2, 29)
    assert parse_birthday("1996-2-29") == BirthdayInput(2, 29, 1996)
    assert parse_birthday("1995-2-29") is None


def test_valid_month_day_checks_the_calendar():
    assert valid_month_day(2, 29) is True
    assert valid_month_day(2, 29, 1996) is True
    assert valid_month_day(2, 29, 1995) is False
    assert valid_month_day(12, 31) is True
    assert valid_month_day(12, 32) is False
    assert valid_month_day(1, 0) is False


def test_is_leap_year_matches_the_gregorian_rule():
    assert is_leap_year(1996) is True
    assert is_leap_year(1900) is False
    assert is_leap_year(2000) is True
    assert is_leap_year(2026) is False


def test_matches_handles_the_leap_day_shift():
    assert matches(5, 20, date(2026, 5, 20)) is True
    assert matches(5, 20, date(2026, 5, 21)) is False
    # 平年：2/29 的生日落在 2/28
    assert matches(2, 29, date(2026, 2, 28)) is True
    assert matches(2, 29, date(2026, 3, 1)) is False
    # 闰年：还是正日子
    assert matches(2, 29, date(2028, 2, 29)) is True
    assert matches(2, 29, date(2028, 2, 28)) is False
    assert matches(2, 28, date(2026, 2, 28)) is True
    assert matches(2, 29, date(2026, 2, 28), shift_feb29=False) is False


def test_occurrence_and_next_occurrence():
    assert occurrence_in_year(2, 29, 2026) == date(2026, 2, 28)
    assert occurrence_in_year(2, 29, 2028) == date(2028, 2, 29)
    assert next_occurrence(5, 20, date(2026, 1, 1)) == date(2026, 5, 20)
    assert next_occurrence(5, 20, date(2026, 5, 20)) == date(2026, 5, 20)
    assert next_occurrence(5, 20, date(2026, 5, 21)) == date(2027, 5, 20)
    assert next_occurrence(2, 29, date(2026, 3, 1)) == date(2027, 2, 28)


def test_format_tenure_speaks_like_a_person():
    joined = datetime(2024, 2, 10, 12, 0, tzinfo=BEIJING)
    assert format_tenure(joined, date(2026, 5, 10)) == "2 年 3 个月"
    assert format_tenure(joined, date(2026, 2, 10)) == "2 年"
    assert format_tenure(joined, date(2024, 5, 10)) == "3 个月"
    assert format_tenure(joined, date(2024, 2, 20)) == "不到 1 个月"
    assert format_tenure(joined, date(2024, 1, 1)) == "不到 1 个月"
    assert format_tenure(date(2025, 5, 10), date(2026, 5, 10)) == "1 年"


def test_visibility_keywords_are_recognised_and_stripped():
    assert parse_visibility("不公开") == "private"
    assert parse_visibility("隐藏") == "private"
    assert parse_visibility("公开") == "public"
    assert parse_visibility("5-20") is None
    assert strip_visibility("5-20 不公开").strip() == "5-20"
    assert strip_visibility("5-20") == "5-20"
    assert parse_birthday(strip_visibility("5-20 不公开")) == BirthdayInput(5, 20)
