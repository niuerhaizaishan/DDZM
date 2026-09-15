from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.company_lottery import (
    BEIJING,
    LOTTERY_PRIZE_SOURCE,
    LOTTERY_PURCHASE_SOURCE,
    Ticket,
)
from dzmm_bot.core.repository import balance_source_label
from dzmm_bot.core.schema import (
    BalanceTransactionRecord,
    Base,
    CompanyLotteryBetRecord,
    CompanyLotteryPoolLedgerRecord,
    CompanyLotteryRoundRecord,
    CompanyLotteryWelfarePayoutRecord,
    CompanyLotteryWelfareRecord,
    GroupChatRecord,
    InboundRecord,
    OutboundRecord,
    PRIMARY_GROUP_CHAT_ID,
    UserRecord,
)

SECOND_GROUP_CHAT_ID = UUID("00000000-0000-0000-0000-0000000000ff")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def now():
    return datetime(2026, 9, 14, 12, 0, tzinfo=BEIJING)


@pytest.fixture
def repository(session_factory):
    from dzmm_bot.core.repository import CoreRepository

    return CoreRepository(session_factory)


def add_group(session, group_id, name, chatroom_id=None):
    session.add(
        GroupChatRecord(
            id=group_id,
            name=name,
            chat_url=None,
            chatroom_id=chatroom_id,
            listening_enabled=True,
            games_enabled=True,
            random_events_enabled=True,
            announcements_enabled=True,
            created_at=datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING),
            updated_at=datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING),
        )
    )


def add_user(session, platform_id, display_name, employee_number, balance=100):
    session.add(
        UserRecord(
            platform_id=platform_id,
            display_name=display_name,
            employee_number=employee_number,
            balance=balance,
            joined_at=datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING),
        )
    )


@pytest.fixture
def seeded(session_factory):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊", chatroom_id="room-main")
        add_group(
            session, SECOND_GROUP_CHAT_ID, "第二群", chatroom_id="room-second"
        )
        add_user(session, "p1", "小明", 1)
        add_user(session, "p2", "小红", 2)
    return session_factory


def seed_pool(repository, amount=100):
    seed_account(repository, "pool", amount)


def seed_account(repository, account, amount):
    """把全公司共用的某个账本重置成指定余额，覆盖首期自动注入的启动奖池。"""
    with repository.transaction():
        with repository._session() as session:
            session.execute(
                delete(CompanyLotteryPoolLedgerRecord).where(
                    CompanyLotteryPoolLedgerRecord.account == account,
                )
            )
            if amount:
                repository._company_lottery_pool_append(
                    session,
                    None,
                    account,
                    "deposit",
                    amount,
                    datetime(2026, 9, 14, 11, 0, tzinfo=BEIJING),
                )


def ticket(reds, blue):
    return Ticket(reds=tuple(reds), blue=blue)


# --------------------------------------------------------------------------- 基础

def test_settings_have_designed_defaults(repository):
    settings = repository.get_company_lottery_settings()

    assert settings.enabled is True
    assert (settings.red_pool, settings.red_count, settings.blue_pool) == (10, 4, 6)
    assert settings.ticket_price == 2
    assert settings.pool_ceiling == 200
    assert settings.pool_seed == 100
    assert settings.per_person_cap == 100
    assert settings.max_tickets_per_day == 5
    assert settings.combinations == 1_260


def test_settings_can_be_updated(repository):
    repository.update_company_lottery_settings(ticket_price=3, pool_ceiling=500)

    settings = repository.get_company_lottery_settings()
    assert settings.ticket_price == 3
    assert settings.pool_ceiling == 500


def test_ensure_round_opens_exactly_one_open_round(repository, seeded, now):
    first = repository.ensure_company_lottery_round(now)
    second = repository.ensure_company_lottery_round(now)

    assert first.id == second.id
    assert first.round_number == 1
    assert first.state == "open"


def test_round_answer_is_hidden_until_drawn(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)

    assert view.answer is None
    assert view.commit_hash

    with repository._session() as session:
        record = session.get(CompanyLotteryRoundRecord, view.id)
    assert record.red_1 is not None
    assert record.salt


# --------------------------------------------------------------------------- 购票

def test_buy_debits_balance_and_records_the_ticket(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a1"),
        "p1",
        [ticket((3, 7, 9, 10), 5)],
        now,
    )

    assert result.status == "bought"
    assert result.cost == 2
    assert result.balance == 98
    assert result.remaining == 4
    assert result.tickets == (ticket((3, 7, 9, 10), 5),)

    history = repository.own_company_lottery_bets("p1")
    assert len(history.bets) == 1
    assert history.total_cost == 2
    assert history.bets[0].ticket == ticket((3, 7, 9, 10), 5)


def test_buy_is_idempotent_for_the_same_inbound_message(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    message_id = UUID("00000000-0000-0000-0000-0000000000a2")

    first = repository.buy_company_lottery_tickets(
        message_id, "p1", [ticket((1, 2, 3, 4), 1)], now
    )
    second = repository.buy_company_lottery_tickets(
        message_id, "p1", [ticket((1, 2, 3, 4), 1)], now
    )

    assert first.status == "bought"
    assert second.status == "duplicate_request"

    with repository._session() as session:
        count = session.scalar(
            select(func.count()).select_from(CompanyLotteryBetRecord)
        )
    assert count == 1
    assert repository.own_company_lottery_bets("p1").total_cost == 2


def test_buy_rejects_a_ticket_already_owned_this_round(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    choice = ticket((1, 2, 3, 4), 1)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a3"),
        "p1",
        [choice],
        now,
    )

    again = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a4"),
        "p1",
        [choice],
        now,
    )

    assert again.status == "duplicate"
    assert repository.own_company_lottery_bets("p1").total_cost == 2


def test_buy_accepts_a_different_ticket_in_the_same_round(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a5"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    second = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a6"),
        "p1",
        [ticket((5, 6, 7, 8), 2)],
        now,
    )

    assert second.status == "bought"
    assert second.remaining == 3


def test_buy_enforces_the_daily_cap_per_beijing_day(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    for index in range(5):
        result = repository.buy_company_lottery_tickets(
            UUID(f"00000000-0000-0000-0000-0000000000b{index}"),
            "p1",
            [ticket((1, 2, 3, index), 1)],
            now,
        )
        assert result.status == "bought"

    blocked = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000bf"),
        "p1",
        [ticket((4, 5, 6, 7), 3)],
        now,
    )

    assert blocked.status == "daily_limit"
    assert blocked.remaining == 0
    assert repository.own_company_lottery_bets("p1").total_cost == 10


def test_daily_cap_resets_on_the_next_beijing_day(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    for index in range(5):
        repository.buy_company_lottery_tickets(
            UUID(f"00000000-0000-0000-0000-0000000000c{index}"),
            "p1",
            [ticket((1, 2, 3, index), 1)],
            now,
        )

    # 模拟 22:00 开奖，让下一期开出来
    with repository.transaction():
        with repository._session() as session:
            session.get(CompanyLotteryRoundRecord, view.id).state = "drawn"

    tomorrow = datetime(2026, 9, 15, 9, 0, tzinfo=BEIJING)
    repository.ensure_company_lottery_round(tomorrow)
    later = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000cf"),
        "p1",
        [ticket((4, 5, 6, 8), 3)],
        tomorrow,
    )

    assert later.status == "bought"
    assert later.round_number == 2


def test_buy_rejects_after_close(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    after_close = datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d1"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        after_close,
    )

    assert result.status == "closed"


def test_buy_rejects_when_balance_is_short(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_user(session, "poor", "穷鬼", 9, balance=1)
    repository.ensure_company_lottery_round(now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d2"),
        "poor",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    assert result.status == "insufficient_balance"
    assert result.needed == 1

    with repository._session() as session:
        count = session.scalar(
            select(func.count()).select_from(CompanyLotteryBetRecord)
        )
        user = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "poor")
        )
    assert count == 0
    assert user.balance == 1


def test_buy_rejects_unknown_employee(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d3"),
        "nobody",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    assert result.status == "not_joined"


def test_buy_rejects_when_disabled(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.update_company_lottery_settings(enabled=False)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d4"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    assert result.status == "disabled"


# --------------------------------------------------------------------------- 机选

def test_quick_picks_buy_several_distinct_tickets(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e1"),
        "p1",
        5,
        now,
    )

    assert result.status == "bought"
    assert result.is_quick_pick is True
    assert len(result.tickets) == 5
    assert len({entry.as_key() for entry in result.tickets}) == 5
    assert result.cost == 10
    assert result.remaining == 0


def test_quick_picks_avoid_tickets_already_owned(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    owned = ticket((3, 7, 9, 10), 5)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000e2"),
        "p1",
        [owned],
        now,
    )

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e3"),
        "p1",
        4,
        now,
    )

    assert owned.as_key() not in {entry.as_key() for entry in result.tickets}


def test_quick_picks_share_the_daily_cap(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000e4"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e5"),
        "p1",
        5,
        now,
    )

    assert result.status == "daily_limit"
    assert result.remaining == 4


def test_quick_pick_result_is_marked_on_the_bet(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e6"),
        "p1",
        1,
        now,
    )

    history = repository.own_company_lottery_bets("p1")
    assert history.bets[0].is_quick_pick is True


# --------------------------------------------------------------------------- 账本

def test_sales_land_in_the_pool_ledger(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_pool(repository, 0)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f1"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f2"),
        "p2",
        [ticket((5, 6, 7, 8), 2), ticket((1, 5, 6, 7), 3)],
        now,
    )

    pool, adjustment = repository.company_lottery_balances()

    assert pool == 6
    assert adjustment == 0

    with repository._session() as session:
        balances = list(
            session.scalars(select(CompanyLotteryPoolLedgerRecord.balance_after))
        )
        round_row = session.scalars(select(CompanyLotteryRoundRecord)).first()

    # 两笔流水同一时刻写入，顺序不定，用最大值代表最终余额
    assert max(balances) == 6
    assert round_row.tickets_sold == 3
    assert round_row.gross_amount == 6


def test_first_round_injects_the_starting_pool_once(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    assert repository.company_lottery_balances() == (100, 0)

    # 开第二期时不能再注入一次
    repository.draw_company_lottery_round(DRAW_AT)

    assert repository.company_lottery_balances() == (100, 0)
    with repository._session() as session:
        deposits = session.scalars(
            select(CompanyLotteryPoolLedgerRecord.amount).where(
                CompanyLotteryPoolLedgerRecord.account == "pool",
                CompanyLotteryPoolLedgerRecord.kind == "deposit",
            )
        ).all()
    assert list(deposits) == [100]


def test_pool_seed_is_configurable(repository, seeded, now):
    repository.update_company_lottery_settings(pool_seed=40)
    repository.ensure_company_lottery_round(now)

    assert repository.company_lottery_balances() == (40, 0)


def test_round_schedule_is_beijing_time_even_for_a_utc_clock(repository, seeded):
    """核心层 clock 给的是 UTC，停售与开奖必须仍落在北京时间整点。"""
    from datetime import UTC

    view = repository.ensure_company_lottery_round(datetime(2026, 9, 14, 12, 0, tzinfo=UTC)
    )

    assert view.close_at.astimezone(BEIJING).strftime("%H:%M") == "21:50"
    assert view.draw_at.astimezone(BEIJING).strftime("%H:%M") == "22:00"
    assert view.draw_at.astimezone(BEIJING).date().isoformat() == "2026-09-14"


def test_pool_balance_matches_the_ledger_sum(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f3"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    pool, _ = repository.company_lottery_balances()
    with repository._session() as session:
        total = session.scalar(
            select(
                func.coalesce(func.sum(CompanyLotteryPoolLedgerRecord.amount), 0)
            ).where(
                CompanyLotteryPoolLedgerRecord.account == "pool",
            )
        )

    assert pool == int(total)


# --------------------------------------------------------------------------- 全公司共用

def test_one_round_and_one_pool_are_shared_across_groups(repository, seeded, now):
    """三个群共用一套经济：无论从哪个群调用，都是同一期、同一本奖池账。"""
    first = repository.ensure_company_lottery_round(now)
    second = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 0)

    assert first.id == second.id
    assert first.round_number == 1

    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000101"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000104"),
        "p2",
        [ticket((5, 6, 7, 8), 2)],
        now,
    )

    # 来自不同群的两次购票进的是同一本账、同一期
    pool, adjustment = repository.company_lottery_balances()
    assert pool == 4
    assert adjustment == 0
    assert repository.current_company_lottery_round().tickets_sold == 2


def test_own_history_is_cross_group(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000102"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000103"),
        "p1",
        [ticket((5, 6, 7, 8), 2)],
        now,
    )

    history = repository.own_company_lottery_bets("p1")

    assert len(history.bets) == 2
    assert history.total_cost == 4


# --------------------------------------------------------------------------- 引导购票

def test_draft_starts_and_reports_its_target(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    result = repository.start_company_lottery_draft(
        "p1", 5, now
    )

    assert result.status == "started"
    assert result.target == 5
    assert result.collected == 0
    assert result.remaining == 5


def test_draft_target_is_capped_by_the_daily_limit(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000201"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    result = repository.start_company_lottery_draft(
        "p1", 5, now
    )

    assert result.status == "started"
    assert result.target == 4


def test_draft_collects_manual_tickets_until_ready(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 2, now)

    first = repository.append_company_lottery_draft(
        "p1", ticket((1, 2, 3, 4), 1), now
    )
    second = repository.append_company_lottery_draft(
        "p1", ticket((5, 6, 7, 8), 2), now
    )

    assert first.status == "appended"
    assert first.collected == 1
    assert second.status == "ready"
    assert second.collected == 2

    draft = repository.load_company_lottery_draft("p1", now)
    assert draft is not None
    assert draft.complete is True


def test_draft_accepts_quick_picks_mixed_with_manual(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 2, now)
    manual = ticket((1, 2, 3, 4), 1)
    repository.append_company_lottery_draft("p1", manual, now)

    quick = repository.append_quick_pick_to_draft("p1", now)

    assert quick.is_quick_pick is True
    assert quick.latest is not None
    assert quick.latest.as_key() != manual.as_key()

    draft = repository.load_company_lottery_draft("p1", now)
    assert draft is not None
    assert draft.quick_flags == (False, True)


def test_draft_rejects_a_duplicate_ticket(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 3, now)
    choice = ticket((1, 2, 3, 4), 1)
    repository.append_company_lottery_draft("p1", choice, now)

    again = repository.append_company_lottery_draft("p1", choice, now)

    assert again.status == "duplicate"
    assert again.collected == 1


def test_draft_rejects_a_ticket_already_owned_this_round(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    owned = ticket((1, 2, 3, 4), 1)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000202"),
        "p1",
        [owned],
        now,
    )
    repository.start_company_lottery_draft("p1", 3, now)

    again = repository.append_company_lottery_draft("p1", owned, now)

    assert again.status == "duplicate"


def test_draft_expires_after_the_timeout(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 3, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)

    later = datetime(2026, 9, 14, 12, 16, tzinfo=BEIJING)

    assert repository.load_company_lottery_draft("p1", later) is None
    late_append = repository.append_company_lottery_draft(
        "p1", ticket((5, 6, 7, 8), 2), later
    )
    assert late_append.status == "no_draft"


def test_cancelling_a_draft_never_touches_the_balance(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 3, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)

    cancelled = repository.cancel_company_lottery_draft("p1")

    assert cancelled is True
    assert repository.load_company_lottery_draft("p1", now) is None
    with repository._session() as session:
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == "p1"))
        bets = session.scalar(select(func.count()).select_from(CompanyLotteryBetRecord))
    assert user.balance == 100
    assert bets == 0


def test_confirming_a_draft_buys_every_ticket_in_one_go(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 3, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)
    repository.append_company_lottery_draft("p1", ticket((5, 6, 7, 8), 2), now)
    repository.append_company_lottery_draft("p1", ticket((1, 5, 6, 7), 3), now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000203"),
        "p1",
        now,
    )

    assert result.status == "bought"
    assert result.purchase is not None
    assert result.purchase.cost == 6
    assert result.purchase.balance == 94
    assert len(result.purchase.tickets) == 3
    assert repository.load_company_lottery_draft("p1", now) is None

    with repository._session() as session:
        bets = session.scalar(select(func.count()).select_from(CompanyLotteryBetRecord))
    assert bets == 3


def test_confirming_an_all_quick_draft_marks_bets_as_quick(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 2, now)
    repository.append_quick_pick_to_draft("p1", now)
    repository.append_quick_pick_to_draft("p1", now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000204"),
        "p1",
        now,
    )

    assert result.status == "bought"
    assert result.purchase.is_quick_pick is True

    history = repository.own_company_lottery_bets("p1")
    assert all(bet.is_quick_pick for bet in history.bets)


def test_confirming_without_a_draft_reports_no_draft(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000205"),
        "p1",
        now,
    )

    assert result.status == "no_draft"


def test_confirming_a_draft_respects_the_current_balance(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_user(session, "p3", "小刚", 3, balance=3)
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p3", 3, now)
    repository.append_company_lottery_draft("p3", ticket((1, 2, 3, 4), 1), now)
    repository.append_company_lottery_draft("p3", ticket((5, 6, 7, 8), 2), now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000206"),
        "p3",
        now,
    )

    assert result.status == "insufficient_balance"
    with repository._session() as session:
        bets = session.scalar(select(func.count()).select_from(CompanyLotteryBetRecord))
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == "p3"))
    assert bets == 0
    assert user.balance == 3


def test_starting_a_draft_again_replaces_the_previous_one(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.start_company_lottery_draft("p1", 5, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)

    repository.start_company_lottery_draft("p1", 2, now)

    draft = repository.load_company_lottery_draft("p1", now)
    assert draft is not None
    assert draft.target_count == 2
    assert draft.collected == 0


# --------------------------------------------------------------------------- 开奖

DRAW_AT = datetime(2026, 9, 14, 22, 0, tzinfo=BEIJING)


def answer_for(repository, round_id):
    with repository._session() as session:
        record = session.get(CompanyLotteryRoundRecord, round_id)
    return Ticket(
        reds=(record.red_1, record.red_2, record.red_3, record.red_4),
        blue=record.blue,
    )


def balance_of(repository, platform_id):
    with repository._session() as session:
        return session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == platform_id)
        )


def test_close_marks_due_rounds_closed(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    assert repository.close_company_lottery_round(now
    ) == 0
    assert repository.close_company_lottery_round(datetime(2026, 9, 14, 21, 50, tzinfo=BEIJING)
    ) == 1
    assert repository.close_company_lottery_round(datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING)
    ) == 0

    view = repository.current_company_lottery_round()
    assert view.state == "closed"


def test_draw_waits_for_the_draw_time(repository, seeded, now):
    repository.ensure_company_lottery_round(now)

    assert repository.draw_company_lottery_round(now) is None


def test_draw_pays_the_head_prize(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000301"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    assert result is not None
    assert result.round_number == 1
    assert result.winner_count == 1
    assert result.winners[0].tier == "head"
    assert result.winners[0].amount == 100
    assert result.haircut is None
    # 100 起始 − 2 购票 + 100 中奖
    assert balance_of(repository, "p1") == 198


def test_draw_pays_a_fifth_prize_for_a_blue_hit(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    answer = answer_for(repository, view.id)
    near_miss = Ticket(reds=losing_ticket(answer).reds, blue=answer.blue)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000302"),
        "p1",
        [near_miss],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    assert result.winners[0].tier == "fifth"
    assert result.winners[0].amount == 1
    assert balance_of(repository, "p1") == 99


def losing_ticket(answer):
    """找一张红球全不中、蓝球也不中的号码。"""
    for a in range(1, 11):
        for b in range(a + 1, 11):
            for c in range(b + 1, 11):
                for d in range(c + 1, 11):
                    if set((a, b, c, d)) & set(answer.reds):
                        continue
                    for blue in range(1, 7):
                        if blue != answer.blue:
                            return Ticket(reds=(a, b, c, d), blue=blue)
    raise AssertionError("找不到必定不中奖的号码")


def test_draw_ignores_losing_tickets(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000303"),
        "p1",
        [losing_ticket(answer)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    assert result.winner_count == 0
    assert result.paid_total == 0
    assert balance_of(repository, "p1") == 98


def test_draw_is_idempotent(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000304"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    first = repository.draw_company_lottery_round(DRAW_AT)
    second = repository.draw_company_lottery_round(DRAW_AT)

    assert first is not None
    assert second is None
    assert balance_of(repository, "p1") == 198

    with repository._session() as session:
        drawn = session.scalars(
            select(CompanyLotteryRoundRecord).where(
                CompanyLotteryRoundRecord.state == "drawn"
            )
        ).all()
    assert len(drawn) == 1


def test_draw_merges_and_caps_per_employee(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 200)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000305"),
        "p1",
        [answer, Ticket(reds=answer.reds, blue=answer.blue % 6 + 1)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    # 一等奖 100 + 二等奖 50 = 150，合并后按单人 100 封顶
    assert result.payable == 100
    assert result.paid_total == 100
    assert result.capped_users == (result.capped_users[0],)
    assert len(result.capped_users) == 1
    assert sum(winner.amount for winner in result.winners) == 100


def test_draw_haircuts_when_the_pool_is_short(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 0)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000306"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    # 奖池只有 2 币，应付 100，按比例折算
    assert result.payable == 100
    assert result.haircut is not None
    assert result.paid_total == 2
    assert result.winners[0].amount == 2
    assert result.pool_balance == 0
    assert balance_of(repository, "p1") == 100


def test_draw_pours_overflow_into_the_adjustment_fund(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 200)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000307"),
        "p1",
        [losing_ticket(answer)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    pool, adjustment = repository.company_lottery_balances()
    assert result.pool_balance == 200
    assert pool == 200
    assert adjustment == 2


def test_draw_keeps_the_head_pool_rolling_when_nobody_wins(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    seed_pool(repository, 100)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000308"),
        "p1",
        [losing_ticket(answer)],
        now,
    )

    first = repository.draw_company_lottery_round(DRAW_AT)
    pool_after_first, _ = repository.company_lottery_balances()

    assert first.winner_count == 0
    assert first.paid_total == 0
    assert pool_after_first == 102


def test_draw_opens_the_next_round(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000309"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )

    result = repository.draw_company_lottery_round(DRAW_AT)

    assert result.next_round_number == 2
    view = repository.current_company_lottery_round()
    assert view.round_number == 2
    assert view.state == "open"
    assert view.answer is None
    assert view.tickets_sold == 0


def test_draw_reveals_the_answer_only_after_settlement(repository, seeded, now):
    view = repository.ensure_company_lottery_round(now)
    expected = answer_for(repository, view.id)
    assert view.answer is None

    repository.draw_company_lottery_round(DRAW_AT)

    settled = repository.company_lottery_round_by_number(1)
    assert settled.state == "drawn"
    assert settled.answer == expected
    assert settled.salt


# --------------------------------------------------------------------------- 全员福利

def test_employee_headcount_is_the_welfare_threshold(repository, seeded):
    assert repository.count_registered_employees() == 2


def test_welfare_does_nothing_below_the_threshold(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 1)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "not_due"
    assert result.employee_count == 2
    assert result.fund_after == 1
    assert balance_of(repository, "p1") == 100
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 1


def test_welfare_pays_every_employee_once(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 2)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "paid"
    assert result.employee_count == 2
    assert result.per_person == 1
    assert result.paid_total == 2
    assert result.fund_before == 2
    assert result.fund_after == 0
    assert balance_of(repository, "p1") == 101
    assert balance_of(repository, "p2") == 101
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 0


def test_welfare_keeps_the_remainder(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 5)

    result = repository.settle_company_lottery_welfare(now)

    assert result.paid_total == 2
    assert result.fund_after == 3
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 3


def test_welfare_pays_only_one_round_even_with_a_large_fund(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 100)

    result = repository.settle_company_lottery_welfare(now)

    assert result.paid_total == 2
    assert result.fund_after == 98
    assert balance_of(repository, "p1") == 101


def test_welfare_threshold_follows_the_latest_headcount(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 2)
    with seeded.begin() as session:
        add_user(session, "p3", "小刚", 3)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "not_due"
    assert result.employee_count == 3
    assert balance_of(repository, "p1") == 100


def test_welfare_can_skip_recent_hires(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_user(session, "veteran", "老员工", 1)
        add_user(session, "rookie", "新员工", 2)
        session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "rookie")
        ).joined_at = now
    repository.update_company_lottery_settings(welfare_min_tenure_hours=24)

    assert repository.count_registered_employees(
        min_tenure_hours=24, now=now
    ) == 1

    seed_account(repository, "adjustment", 1)
    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "paid"
    assert result.employee_count == 1
    assert balance_of(repository, "veteran") == 101
    assert balance_of(repository, "rookie") == 100


def test_welfare_writes_ledger_and_payout_rows(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 6)

    result = repository.settle_company_lottery_welfare(now)

    with repository._session() as session:
        welfare_rows = session.scalars(select(CompanyLotteryWelfareRecord)).all()
        payout_rows = session.scalars(
            select(CompanyLotteryWelfarePayoutRecord)
        ).all()

    assert result.status == "paid"
    assert len(welfare_rows) == 1
    assert welfare_rows[0].paid_total == 2
    assert welfare_rows[0].fund_before == 6
    assert welfare_rows[0].fund_after == 4
    assert len(payout_rows) == 2
    assert {row.amount for row in payout_rows} == {1}


def test_welfare_does_nothing_without_employees(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
    seed_account(repository, "adjustment", 50)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "not_due"
    assert result.employee_count == 0
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 50


def test_welfare_can_be_disabled(repository, seeded, now):
    repository.update_company_lottery_settings(welfare_enabled=False)
    seed_account(repository, "adjustment", 10)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "disabled"
    assert balance_of(repository, "p1") == 100


def test_welfare_rolls_back_entirely_on_failure(
    repository, seeded, now, monkeypatch
):
    repository.ensure_company_lottery_round(now)
    seed_account(repository, "adjustment", 10)

    calls = {"count": 0}
    original = repository._apply_balance_change

    def flaky(user, amount, source, occurred_at, **kwargs):
        calls["count"] += 1
        if calls["count"] > 1:
            raise RuntimeError("模拟发放中途失败")
        return original(user, amount, source, occurred_at, **kwargs)

    monkeypatch.setattr(repository, "_apply_balance_change", flaky)

    with pytest.raises(RuntimeError):
        repository.settle_company_lottery_welfare(now)

    assert balance_of(repository, "p1") == 100
    assert balance_of(repository, "p2") == 100
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 10

    with repository._session() as session:
        welfare_rows = session.scalars(select(CompanyLotteryWelfareRecord)).all()
        payout_rows = session.scalars(
            select(CompanyLotteryWelfarePayoutRecord)
        ).all()
    assert welfare_rows == []
    assert payout_rows == []


def test_welfare_runs_once_for_the_whole_company(repository, seeded, now):
    """福利也是全公司一本账：发过一轮之后立刻再判就是 not_due。"""
    seed_account(repository, "adjustment", 2)

    result = repository.settle_company_lottery_welfare(now)

    assert result.status == "paid"
    _, adjustment = repository.company_lottery_balances()
    assert adjustment == 0

    second = repository.settle_company_lottery_welfare(now)
    assert second.status == "not_due"


def test_announcements_are_broadcast_to_every_group(repository, seeded, now):
    """期次是全局的，但开奖公告要送到每一个群。"""
    seed_pool(repository, 100)
    view = repository.ensure_company_lottery_round(now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000001a1"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    assert any(
        "【公司双色球开奖】" in text
        for text in outbound_texts(repository)
    )
    assert any(
        "【公司双色球开奖】" in text
        for text in outbound_texts(repository)
    )


# --------------------------------------------------------------------------- 调度

def outbound_texts(repository, group_chat_id=PRIMARY_GROUP_CHAT_ID):
    """只取指定群的消息：任务会遍历所有群，各群各自播报。"""
    with repository._session() as session:
        return [
            row.text
            for row in session.scalars(
                select(OutboundRecord)
                .where(OutboundRecord.group_chat_id == group_chat_id)
                .order_by(OutboundRecord.created_at)
            )
        ]


def test_run_jobs_opens_the_first_round(repository, seeded, now):
    repository.run_company_lottery_jobs(now)

    view = repository.current_company_lottery_round()
    assert view is not None
    assert view.round_number == 1
    assert view.state == "open"
    assert outbound_texts(repository) == []


def test_run_jobs_opens_one_round_for_the_whole_company(repository, seeded, now):
    repository.run_company_lottery_jobs(now)

    with repository._session() as session:
        rounds = session.scalars(select(CompanyLotteryRoundRecord)).all()

    assert len(rounds) == 1
    assert rounds[0].round_number == 1


def test_run_jobs_draws_and_announces_at_the_draw_time(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000401"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    texts = outbound_texts(repository)
    assert len(texts) == 1
    assert "【公司双色球开奖】" in texts[0]
    assert "🏆 一等奖 100 —— 小明" in texts[0]
    assert "第 2 期已开卖" in texts[0]
    # 开奖公告里的对账行必须与结算结果一致
    assert "流水校验：期初 100 ＋ 售票 2 ＝ 派奖 100 ＋ 溢出 0 ＋ 期末 2" in texts[0]

    assert repository.company_lottery_round_by_number(1).state == "drawn"
    assert repository.current_company_lottery_round().round_number == 2


def test_draw_announcement_stays_a_single_group_message(repository, seeded, now):
    """群消息上限是 10 个换行；对账信息不能把开奖公告挤成两条。"""
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000004a1"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    assert len(outbound_texts(repository)) == 1


# --------------------------------------------------------------------------- 对账

def test_reconcile_reports_a_balanced_ledger(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000005a1"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )
    repository.run_company_lottery_jobs(DRAW_AT)

    recon = repository.company_lottery_overview().reconcile

    assert recon.injected_total == 100
    assert recon.sales_total == 2
    assert recon.prize_paid_total == 100
    assert recon.welfare_paid_total == 0
    assert (recon.pool_balance, recon.adjustment_balance) == (2, 0)
    assert recon.expected_balance == 2
    assert recon.actual_balance == 2
    assert recon.balanced is True


def test_reconcile_counts_welfare_and_manual_deposits(repository, seeded, now):
    repository.ensure_company_lottery_round(now)
    repository.deposit_company_lottery_pool(7, now)
    seed_account(repository, "adjustment", 5)

    assert repository.settle_company_lottery_welfare(now).status == "paid"
    recon = repository.company_lottery_overview().reconcile

    # 启动奖池 100 + 后台注资 7 + 调节金注入 5，全部算系统注入
    assert recon.injected_total == 112
    assert recon.sales_total == 0
    assert recon.welfare_paid_total == 2
    assert recon.credited_total == 2
    assert recon.expected_balance == 110
    assert recon.actual_balance == 110
    assert recon.balanced is True


def test_draw_is_idempotent_across_repeated_ticks(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000005a2"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    for _ in range(3):
        repository.run_company_lottery_jobs(DRAW_AT)

    recon = repository.company_lottery_overview().reconcile
    assert recon.prize_paid_total == 100
    assert recon.balanced is True
    assert len(repository.company_lottery_overview().rounds) == 2


# --------------------------------------------------------------------------- 余额流水来源

def test_balance_sources_are_stable_tokens_with_labels(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000006a1"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )
    repository.run_company_lottery_jobs(DRAW_AT)

    with repository._session() as session:
        sources = set(
            session.scalars(
                select(BalanceTransactionRecord.source).where(
                    BalanceTransactionRecord.source.like("company_lottery%")
                )
            )
        )

    assert sources == {LOTTERY_PURCHASE_SOURCE, LOTTERY_PRIZE_SOURCE}
    for source in sources:
        assert balance_source_label(source) != source


def test_lottery_flows_stay_out_of_daily_income(repository, seeded, now):
    """中奖不是劳动收益：一次头奖不该把人顶上今日收益榜。"""
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000006a2"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )
    repository.run_company_lottery_jobs(DRAW_AT)
    with repository._session() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )

    assert balance_of(repository, "p1") == 198
    assert repository.today_income(user_id, DRAW_AT) == 0
    with repository._session() as session:
        assert repository._income_rankings(session, DRAW_AT) == []


def test_daily_income_before_the_draw_only_has_the_ticket_cost(repository, seeded, now):
    """购票是负数，本来就不进收益；这里确认它没有意外变成正数。"""
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000006a3"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        now,
    )
    with repository._session() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )

    assert repository.today_income(user_id, now) == 0


def test_daily_ticket_limit_only_counts_the_same_beijing_day(repository, seeded, now):
    """只写下界的话，明天买的票会算进今天的额度里。"""
    from datetime import timedelta
    from uuid import uuid4

    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    tomorrow = now + timedelta(days=1)
    with repository._session() as session:
        session.add(
            CompanyLotteryBetRecord(
                round_id=view.id,
                user_id=session.scalar(
                    select(UserRecord.id).where(UserRecord.platform_id == "p1")
                ),
                red_1=1,
                red_2=2,
                red_3=3,
                red_4=4,
                blue=1,
                ticket_key="01020304-01",
                cost=2,
                is_quick_pick=True,
                inbound_message_id=uuid4(),
                created_at=tomorrow,
            )
        )

    with repository._session() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )
        assert repository._company_lottery_today_count(session, user_id, now) == 0
        assert (
            repository._company_lottery_today_count(session, user_id, tomorrow) == 1
        )


def test_reconcile_cross_checks_the_employee_ledger(repository, seeded, now):
    """三边对齐：期次/福利表记的应发 = 余额流水实际入账；且等于两本账的余额差。"""
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000006a5"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )
    repository.run_company_lottery_jobs(DRAW_AT)
    seed_account(repository, "adjustment", 4)
    assert (
        repository.settle_company_lottery_welfare_manually(DRAW_AT).status == "paid"
    )

    recon = repository.company_lottery_overview().reconcile

    assert recon.prize_paid_total == 100
    assert recon.welfare_paid_total == 2
    assert recon.credited_total == 102
    assert recon.credited_ledger_total == 102
    assert recon.balanced is True


def test_reconcile_flags_a_diverged_employee_ledger(repository, seeded, now):
    """故意把员工侧流水改坏，对账必须报不平。"""
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000006a6"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )
    repository.run_company_lottery_jobs(DRAW_AT)
    with repository._session() as session:
        row = session.scalar(
            select(BalanceTransactionRecord).where(
                BalanceTransactionRecord.source == LOTTERY_PRIZE_SOURCE
            )
        )
        row.amount += 1

    recon = repository.company_lottery_overview().reconcile

    assert recon.credited_total == 100
    assert recon.credited_ledger_total == 101
    assert recon.balanced is False


# --------------------------------------------------------------------------- 群级入口开关

def set_group_switch(repository, group_id, **flags):
    """测试辅助建的群没有 chat_url，走不了 update_group_chat，直接改列。"""
    with repository._session() as session:
        record = session.get(GroupChatRecord, group_id)
        for name, value in flags.items():
            setattr(record, name, value)


def test_lottery_switch_does_not_stop_announcements(repository, seeded, now):
    """开关只控制入口：关掉彩票的群照样能看到今天开出了什么号。"""
    set_group_switch(repository, SECOND_GROUP_CHAT_ID, lottery_enabled=False)
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000007a1"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    assert any(
        "【公司双色球开奖】" in text
        for text in outbound_texts(repository, SECOND_GROUP_CHAT_ID)
    )


def test_announcements_ignore_the_announcement_switch(repository, seeded, now):
    """开奖结果是公司级公共信息，不受「接收定时活动/公告」影响。"""
    set_group_switch(repository, SECOND_GROUP_CHAT_ID, announcements_enabled=False)
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000007a2"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    assert any(
        "【公司双色球开奖】" in text
        for text in outbound_texts(repository, SECOND_GROUP_CHAT_ID)
    )


def test_announcements_skip_groups_with_listening_off(repository, seeded, now):
    """监听关掉等于该群停止全部新收发，往那儿排队没有意义。"""
    set_group_switch(repository, SECOND_GROUP_CHAT_ID, listening_enabled=False)
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000007a3"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)

    assert outbound_texts(repository, PRIMARY_GROUP_CHAT_ID)
    assert outbound_texts(repository, SECOND_GROUP_CHAT_ID) == []


def test_disabled_group_cannot_buy_but_the_round_still_runs(repository, seeded, now):
    set_group_switch(repository, PRIMARY_GROUP_CHAT_ID, lottery_enabled=False)
    repository.run_company_lottery_jobs(now)

    # 期次是全公司的，开卖与否不受单群开关影响
    assert repository.current_company_lottery_round().round_number == 1


def test_run_jobs_does_not_draw_before_the_draw_time(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    repository.run_company_lottery_jobs(datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING))

    view = repository.current_company_lottery_round()
    assert view.round_number == 1
    assert view.state == "closed"
    assert outbound_texts(repository) == []


def test_run_jobs_reminds_before_the_close(repository, seeded, now):
    repository.run_company_lottery_jobs(now)

    repository.run_company_lottery_jobs(
        datetime(2026, 9, 14, 21, 46, tzinfo=BEIJING)
    )

    texts = outbound_texts(repository)
    assert len(texts) == 1
    assert "还有 5 分钟停售" in texts[0]
    assert "/购买彩票 机选" in texts[0]


def test_close_reminder_is_sent_once_per_round(repository, seeded, now):
    """Worker 每秒跑一次任务，冷清的群不能被同一条停售提醒刷屏。"""
    from datetime import timedelta

    repository.run_company_lottery_jobs(now)

    close_minute = datetime(2026, 9, 14, 21, 45, tzinfo=BEIJING)
    for second in range(0, 5 * 60, 20):
        repository.run_company_lottery_jobs(close_minute + timedelta(seconds=second))

    reminders = [text for text in outbound_texts(repository) if "停售" in text]
    assert len(reminders) == 1


def test_run_jobs_skips_the_reminder_when_the_group_is_busy(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    with repository._session() as session:
        session.add(
            InboundRecord(
                platform_message_id="m-busy",
                sender_platform_id="p1",
                content="刚说完话",
                received_at=datetime(2026, 9, 14, 21, 45, tzinfo=BEIJING),
                status="accepted",
                source_type="group",
                group_chat_id=PRIMARY_GROUP_CHAT_ID,
                created_at=datetime(2026, 9, 14, 21, 45, tzinfo=BEIJING),
            )
        )

    repository.run_company_lottery_jobs(
        datetime(2026, 9, 14, 21, 46, tzinfo=BEIJING)
    )

    assert outbound_texts(repository) == []


def test_welfare_waits_for_a_manual_command_after_the_draw(repository, seeded, now):
    """定时任务不再自动发福利；开奖后要有人发 /发放福利 才发。"""
    repository.run_company_lottery_jobs(now)
    seed_account(repository, "adjustment", 2)

    repository.run_company_lottery_jobs(DRAW_AT)

    # 开奖本身不发福利
    assert not any("公司福利发放" in text for text in outbound_texts(repository))
    assert balance_of(repository, "p1") == 100
    assert repository.company_lottery_balances()[1] == 2

    assert (
        repository.settle_company_lottery_welfare_manually(DRAW_AT).status == "paid"
    )

    texts = outbound_texts(repository)
    assert any("🎉 公司福利发放" in text for text in texts)
    welfare_text = next(text for text in texts if "公司福利发放" in text)
    assert "调节金累计达 2 摸鱼币" in welfare_text
    assert "全员各获得 1 摸鱼币" in welfare_text
    assert balance_of(repository, "p1") == 101


def test_manual_draw_also_leaves_the_welfare_to_the_command(repository, seeded, now):
    """后台手动开奖与定时任务同口径：都不发福利，避免绕开 /发放福利 的门槛。"""
    repository.run_company_lottery_jobs(now)
    seed_account(repository, "adjustment", 2)
    view = repository.current_company_lottery_round()

    drawn = repository.draw_company_lottery_round_manually(DRAW_AT)

    assert drawn is not None and view is not None
    assert not any("公司福利发放" in text for text in outbound_texts(repository))
    assert balance_of(repository, "p1") == 100
    assert repository.company_lottery_balances()[1] == 2

    assert (
        repository.settle_company_lottery_welfare_manually(DRAW_AT).status == "paid"
    )
    assert balance_of(repository, "p1") == 101


def test_welfare_refuses_before_the_round_is_drawn(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    seed_account(repository, "adjustment", 2)

    result = repository.settle_company_lottery_welfare_manually(now)

    assert result.status == "not_drawn"
    assert balance_of(repository, "p1") == 100
    assert repository.company_lottery_balances()[1] == 2
    assert outbound_texts(repository) == []


def test_welfare_refuses_when_the_lottery_is_disabled(repository, seeded, now):
    repository.update_company_lottery_settings(enabled=False)

    assert (
        repository.settle_company_lottery_welfare_manually(now).status == "disabled"
    )


def test_run_jobs_does_nothing_when_disabled(repository, seeded, now):
    repository.update_company_lottery_settings(enabled=False)

    repository.run_company_lottery_jobs(now)

    assert repository.current_company_lottery_round() is None
    assert outbound_texts(repository) == []


def test_run_jobs_is_idempotent_across_ticks(repository, seeded, now):
    repository.run_company_lottery_jobs(now)
    view = repository.current_company_lottery_round()
    seed_pool(repository, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000402"),
        "p1",
        [answer_for(repository, view.id)],
        now,
    )

    repository.run_company_lottery_jobs(DRAW_AT)
    repository.run_company_lottery_jobs(DRAW_AT)
    repository.run_company_lottery_jobs(DRAW_AT)

    texts = outbound_texts(repository)
    assert sum(1 for text in texts if "【公司双色球开奖】" in text) == 1
    assert balance_of(repository, "p1") == 198
