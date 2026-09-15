from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from dzmm_bot.core.company_lottery import (
    BEIJING,
    DEFAULT_PRIZES,
    OrderKind,
    PrizeTier,
    Ticket,
    TicketParseError,
    check_welfare,
    commit_hash,
    draw_numbers,
    expected_return,
    is_quick_pick,
    judge,
    parse_order,
    parse_single,
    quick_tickets,
    round_timing,
    settle_round,
    should_notify_close,
    tier_counts,
    total_combinations,
    winning_combinations,
)


# --------------------------------------------------------------------------- 概率

def test_tier_counts_matches_design():
    counts = tier_counts()

    assert counts == {
        PrizeTier.HEAD: 1,
        PrizeTier.SECOND: 5,
        PrizeTier.THIRD: 24,
        PrizeTier.FOURTH: 120,
        PrizeTier.FIFTH: 185,
        None: 925,
    }
    assert sum(counts.values()) == 1_260


def test_total_combinations_is_1260():
    assert total_combinations() == 1_260


def test_tier_probabilities_match_design():
    counts = tier_counts()

    assert 1_260 / counts[PrizeTier.HEAD] == 1_260
    assert 1_260 / counts[PrizeTier.SECOND] == 252
    assert 1_260 / counts[PrizeTier.THIRD] == Decimal(1_260) / Decimal(24)
    assert 1_260 / counts[PrizeTier.FOURTH] == Decimal(1_260) / Decimal(120)
    assert 1_260 / counts[PrizeTier.FIFTH] == pytest.approx(6.8108, abs=1e-4)


def test_win_rate_matches_design():
    assert winning_combinations() == 335
    assert winning_combinations() / 1_260 == pytest.approx(0.265873, abs=1e-6)


def test_expected_return_matches_design():
    assert expected_return(DEFAULT_PRIZES) == Decimal(1_495) / Decimal(1_260)
    assert expected_return(DEFAULT_PRIZES) == pytest.approx(
        Decimal("1.186508"), abs=1e-6
    )


# --------------------------------------------------------------------------- 判档

def test_judge_covers_every_tier_and_the_miss():
    answer = Ticket(reds=(1, 2, 3, 4), blue=1)

    assert judge(answer, Ticket((1, 2, 3, 4), 1)) is PrizeTier.HEAD
    assert judge(answer, Ticket((1, 2, 3, 4), 2)) is PrizeTier.SECOND
    assert judge(answer, Ticket((1, 2, 3, 5), 1)) is PrizeTier.THIRD
    assert judge(answer, Ticket((1, 2, 3, 5), 2)) is PrizeTier.FOURTH
    assert judge(answer, Ticket((1, 2, 5, 6), 1)) is PrizeTier.FIFTH
    assert judge(answer, Ticket((1, 2, 5, 6), 2)) is None
    assert judge(answer, Ticket((6, 7, 8, 9), 1)) is PrizeTier.FIFTH
    assert judge(answer, Ticket((6, 7, 8, 9), 2)) is None


def test_judge_ignores_red_ball_order():
    answer = Ticket(reds=(1, 2, 3, 4), blue=1)

    assert judge(answer, Ticket((4, 3, 2, 1), 1)) is PrizeTier.HEAD


def test_fifth_prize_requires_blue_hit_only():
    """红球中 3 个但蓝球不中，是四等奖；红球中 2 个且蓝球中，才是五等奖。"""
    answer = Ticket(reds=(1, 2, 3, 4), blue=1)

    assert judge(answer, Ticket((1, 2, 3, 9), 2)) is PrizeTier.FOURTH
    assert judge(answer, Ticket((1, 2, 9, 10), 1)) is PrizeTier.FIFTH


# --------------------------------------------------------------------------- 号码

def test_draw_numbers_stays_inside_the_pool():
    for _ in range(200):
        ticket = draw_numbers()

        assert len(ticket.reds) == 4
        assert len(set(ticket.reds)) == 4
        assert ticket.reds == tuple(sorted(ticket.reds))
        assert all(1 <= number <= 10 for number in ticket.reds)
        assert 1 <= ticket.blue <= 6


def test_commit_hash_is_deterministic_and_salt_sensitive():
    ticket = Ticket(reds=(3, 7, 9, 10), blue=5)

    assert commit_hash(ticket, "abc123") == commit_hash(ticket, "abc123")
    assert commit_hash(ticket, "abc123") != commit_hash(ticket, "abc124")
    assert commit_hash(ticket, "abc123") != commit_hash(
        Ticket(reds=(1, 7, 9, 10), blue=5), "abc123"
    )


# --------------------------------------------------------------------------- 机选

def test_quick_tickets_never_repeat():
    picked = quick_tickets(quantity=20)

    assert len(picked) == 20
    assert len({ticket.as_key() for ticket in picked}) == 20


def test_quick_tickets_avoids_excluded_numbers():
    taken = {"03|07|09|10+05"}

    picked = quick_tickets(quantity=20, exclude=taken)

    assert taken.isdisjoint({ticket.as_key() for ticket in picked})


def test_quick_tickets_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        quick_tickets(quantity=0)


def test_is_quick_pick_recognises_aliases():
    assert is_quick_pick("机选")
    assert is_quick_pick(" 随机 ")
    assert is_quick_pick("机")
    assert not is_quick_pick("03 07 09 10 + 05")


# --------------------------------------------------------------------------- 奖池结算

def test_settle_round_pours_every_ticket_into_the_pool():
    settlement = settle_round(
        pool_opening=100, sales=60, winners=[], prizes=DEFAULT_PRIZES
    )

    assert settlement.overflow == 0
    assert settlement.pool_available == 160
    assert settlement.pool_closing == 160


def test_settle_round_reaches_steady_state_overflow():
    """奖池满额时，100 → 164 的稳态每期溢出 24 摸鱼币。"""
    settlement = settle_round(
        pool_opening=164, sales=60, winners=[], prizes=DEFAULT_PRIZES
    )

    assert settlement.overflow == 24
    assert settlement.pool_available == 200
    assert settlement.pool_closing == 200


def test_settle_round_caps_the_pool_and_diverts_the_excess():
    settlement = settle_round(
        pool_opening=200, sales=100, winners=[], prizes=DEFAULT_PRIZES
    )

    assert settlement.overflow == 100
    assert settlement.pool_available == 200


def test_settle_round_merges_multiple_winning_tickets_per_employee():
    settlement = settle_round(
        pool_opening=200,
        sales=100,
        winners=[("u1", PrizeTier.THIRD), ("u1", PrizeTier.THIRD)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.per_user == {"u1": 30}
    assert settlement.payable == 30
    assert settlement.haircut is None
    assert settlement.paid_total == 30


def test_settle_round_caps_after_merging_per_employee():
    settlement = settle_round(
        pool_opening=200,
        sales=100,
        winners=[("u1", PrizeTier.HEAD), ("u1", PrizeTier.HEAD)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.per_user == {"u1": 100}
    assert settlement.capped_users == ("u1",)
    assert settlement.payable == 100


def test_settle_round_gives_each_employee_their_own_cap():
    settlement = settle_round(
        pool_opening=200,
        sales=100,
        winners=[("u1", PrizeTier.HEAD), ("u2", PrizeTier.HEAD)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.per_user == {"u1": 100, "u2": 100}
    assert settlement.payable == 200
    assert settlement.capped_users == ()


def test_settle_round_haircuts_when_the_pool_is_short():
    settlement = settle_round(
        pool_opening=0,
        sales=50,
        winners=[("u1", PrizeTier.HEAD)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.pool_available == 50
    assert settlement.payable == 100
    assert settlement.haircut == Decimal("0.5000")
    assert settlement.paid_total == 50
    assert settlement.pool_closing == 0


def test_settle_round_haircuts_after_capping():
    """两张一等奖先合并封顶到 100，再按只有 60 的奖池折算。"""
    settlement = settle_round(
        pool_opening=0,
        sales=60,
        winners=[("u1", PrizeTier.HEAD), ("u1", PrizeTier.HEAD)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.per_user == {"u1": 100}
    assert settlement.payable == 100
    assert settlement.haircut == Decimal("0.6000")
    assert settlement.paid_total == 60


def test_settle_round_never_overpays_or_goes_negative():
    settlement = settle_round(
        pool_opening=0,
        sales=7,
        winners=[("u1", PrizeTier.SECOND), ("u2", PrizeTier.SECOND)],
        prizes=DEFAULT_PRIZES,
    )

    assert settlement.paid_total <= settlement.pool_available
    assert settlement.pool_closing >= 0


def test_settle_round_pool_recovers_after_a_head_prize():
    """头奖中出后奖池见底，三期回到满额。"""
    pool = 200
    trail: list[int] = []

    for winners in ([("u1", PrizeTier.HEAD)], [], [], [], []):
        settlement = settle_round(
            pool_opening=pool, sales=60, winners=winners, prizes=DEFAULT_PRIZES
        )
        pool = settlement.pool_closing
        trail.append(pool)

    assert trail == [100, 160, 200, 200, 200]


# --------------------------------------------------------------------------- 全员福利

@pytest.mark.parametrize(
    ("fund", "count", "triggered", "paid", "after"),
    [
        (127, 128, False, 0, 127),
        (128, 128, True, 128, 0),
        (156, 128, True, 128, 28),
        (255, 128, True, 128, 127),
        (256, 128, True, 128, 128),
        (100, 0, False, 0, 100),
    ],
)
def test_check_welfare_thresholds(fund, count, triggered, paid, after):
    result = check_welfare(fund=fund, employee_count=count)

    assert result.triggered is triggered
    assert result.paid_total == paid
    assert result.fund_after == after


def test_check_welfare_pays_only_one_round():
    """余额够发两轮也只发一轮，余数留给下次触发。"""
    result = check_welfare(fund=300, employee_count=128)

    assert result.triggered
    assert result.paid_total == 128
    assert result.fund_after == 172


def test_check_welfare_threshold_follows_the_latest_headcount():
    assert check_welfare(fund=156, employee_count=128).triggered
    assert not check_welfare(fund=156, employee_count=200).triggered
    assert check_welfare(fund=200, employee_count=200).triggered


def test_check_welfare_rejects_non_positive_headcount():
    assert not check_welfare(fund=1_000, employee_count=0).triggered


# --------------------------------------------------------------------------- 时段

def test_round_timing_rolls_over_to_tomorrow():
    now = datetime(2026, 9, 14, 23, 0, tzinfo=BEIJING)

    close_at, draw_at = round_timing(
        now=now, draw_hour=22, draw_minute=0, close_offset_minutes=10
    )

    assert draw_at == datetime(2026, 9, 15, 22, 0, tzinfo=BEIJING)
    assert close_at == datetime(2026, 9, 15, 21, 50, tzinfo=BEIJING)


def test_round_timing_keeps_today_when_draw_is_ahead():
    now = datetime(2026, 9, 14, 20, 0, tzinfo=BEIJING)

    close_at, draw_at = round_timing(
        now=now, draw_hour=22, draw_minute=0, close_offset_minutes=10
    )

    assert draw_at == datetime(2026, 9, 14, 22, 0, tzinfo=BEIJING)
    assert close_at == datetime(2026, 9, 14, 21, 50, tzinfo=BEIJING)


def test_should_notify_close_only_inside_window_and_when_idle():
    now = datetime(2026, 9, 14, 21, 46, tzinfo=BEIJING)
    close_at = datetime(2026, 9, 14, 21, 50, tzinfo=BEIJING)

    assert should_notify_close(
        now=now, close_at=close_at, notify_offset_minutes=5,
        seconds_since_last_message=3_600,
    )
    assert not should_notify_close(
        now=now, close_at=close_at, notify_offset_minutes=5,
        seconds_since_last_message=60,
    )
    assert not should_notify_close(
        now=datetime(2026, 9, 14, 21, 0, tzinfo=BEIJING), close_at=close_at,
        notify_offset_minutes=5, seconds_since_last_message=3_600,
    )
    assert not should_notify_close(
        now=datetime(2026, 9, 14, 21, 51, tzinfo=BEIJING), close_at=close_at,
        notify_offset_minutes=5, seconds_since_last_message=3_600,
    )


# --------------------------------------------------------------------------- 手选解析

@pytest.mark.parametrize(
    "text",
    [
        "/购买彩票 03 07 09 10 + 05",
        "/购买彩票 3 7 9 10 5",
        "/购买彩票 10 09 07 03 + 05",
        "/购买彩票 03,07,09,10 + 05",
        "/购买彩票 10，09，07，03 + 05",
    ],
)
def test_parse_single_accepts_equivalent_spellings(text):
    assert parse_single(text) == Ticket(reds=(3, 7, 9, 10), blue=5)


@pytest.mark.parametrize(
    ("text", "scenario"),
    [
        ("/购买彩票 12 07 09 10 + 05", "red_out_of_range"),
        ("/购买彩票 07 07 09 10 + 05", "red_duplicate"),
        ("/购买彩票 03 07 09 + 05", "red_count_mismatch"),
        ("/购买彩票 03 07 09 10 05 06 + 05", "red_count_mismatch"),
        ("/购买彩票 03 07 09 10 + 09", "blue_out_of_range"),
        ("/购买彩票 03 07 09 10 + 0", "blue_out_of_range"),
        ("/购买彩票", "format"),
        ("/购买彩票 甲 乙 丙 丁 + 05", "format"),
    ],
)
def test_parse_single_rejects_bad_numbers(text, scenario):
    with pytest.raises(TicketParseError) as error:
        parse_single(text)

    assert error.value.scenario == scenario


# --------------------------------------------------------------------------- 指令解析

def test_parse_order_reads_a_manual_ticket():
    order = parse_order("/购买彩票 03 07 09 10 + 05")

    assert order.kind is OrderKind.MANUAL
    assert order.quantity == 1
    assert order.ticket == Ticket(reds=(3, 7, 9, 10), blue=5)


@pytest.mark.parametrize(
    ("text", "quantity"),
    [
        ("/购买彩票 机选", 1),
        ("/购买彩票 随机", 1),
        ("/购买彩票 机", 1),
        ("/购买彩票 random", 1),
        ("/购买彩票 机选 3", 3),
        ("/购买彩票 机 2", 2),
        ("/购买彩票 quick 5", 5),
    ],
)
def test_parse_order_reads_quick_picks(text, quantity):
    order = parse_order(text)

    assert order.kind is OrderKind.QUICK
    assert order.quantity == quantity
    assert order.ticket is None


@pytest.mark.parametrize(
    ("text", "scenario"),
    [
        ("/购买彩票 机选 6", "limit"),
        ("/购买彩票 机选 0", "limit"),
        ("/购买彩票 机选 1 2", "format"),
        ("/购买彩票 机选 x", "format"),
    ],
)
def test_parse_order_rejects_bad_quick_picks(text, scenario):
    with pytest.raises(TicketParseError) as error:
        parse_order(text)

    assert error.value.scenario == scenario


@pytest.mark.parametrize("text", ["/购买彩票 3 注", "/购买彩票 3", "/购买彩票 3 buy"])
def test_parse_order_reads_guided_purchases(text):
    order = parse_order(text)

    assert order.kind is OrderKind.GUIDED
    assert order.quantity == 3


def test_parse_order_rejects_guided_purchase_above_the_daily_cap():
    with pytest.raises(TicketParseError) as error:
        parse_order("/购买彩票 9 注")

    assert error.value.scenario == "limit"


def test_parse_order_rejects_empty_body():
    with pytest.raises(TicketParseError) as error:
        parse_order("/购买彩票")

    assert error.value.scenario == "empty"


def test_parse_order_rejects_two_token_garbage():
    with pytest.raises(TicketParseError) as error:
        parse_order("/购买彩票 3 号")

    assert error.value.scenario == "format"
