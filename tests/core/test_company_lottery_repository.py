from datetime import datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.company_lottery import BEIJING, Ticket
from dzmm_bot.core.schema import (
    Base,
    CompanyLotteryBetRecord,
    CompanyLotteryPoolLedgerRecord,
    CompanyLotteryRoundRecord,
    GroupChatRecord,
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


def add_group(session, group_id, name):
    session.add(
        GroupChatRecord(
            id=group_id,
            name=name,
            chat_url=None,
            chatroom_id=None,
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
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_group(session, SECOND_GROUP_CHAT_ID, "第二群")
        add_user(session, "p1", "小明", 1)
        add_user(session, "p2", "小红", 2)
    return session_factory


def seed_pool(session_factory, group_id, amount=100):
    from dzmm_bot.core.repository import CoreRepository

    repository = CoreRepository(session_factory)
    with repository.transaction():
        with repository._session() as session:
            repository._company_lottery_pool_append(
                session,
                group_id,
                None,
                "pool",
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
    assert settings.per_person_cap == 100
    assert settings.max_tickets_per_day == 5
    assert settings.combinations == 1_260


def test_settings_can_be_updated(repository):
    repository.update_company_lottery_settings(ticket_price=3, pool_ceiling=500)

    settings = repository.get_company_lottery_settings()
    assert settings.ticket_price == 3
    assert settings.pool_ceiling == 500


def test_ensure_round_opens_exactly_one_open_round(repository, seeded, now):
    first = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    second = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    assert first.id == second.id
    assert first.round_number == 1
    assert first.state == "open"


def test_round_answer_is_hidden_until_drawn(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    assert view.answer is None
    assert view.commit_hash

    with repository._session() as session:
        record = session.get(CompanyLotteryRoundRecord, view.id)
    assert record.red_1 is not None
    assert record.salt


# --------------------------------------------------------------------------- 购票

def test_buy_debits_balance_and_records_the_ticket(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a1"),
        "p1",
        [ticket((3, 7, 9, 10), 5)],
        PRIMARY_GROUP_CHAT_ID,
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    message_id = UUID("00000000-0000-0000-0000-0000000000a2")

    first = repository.buy_company_lottery_tickets(
        message_id, "p1", [ticket((1, 2, 3, 4), 1)], PRIMARY_GROUP_CHAT_ID, now
    )
    second = repository.buy_company_lottery_tickets(
        message_id, "p1", [ticket((1, 2, 3, 4), 1)], PRIMARY_GROUP_CHAT_ID, now
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    choice = ticket((1, 2, 3, 4), 1)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a3"),
        "p1",
        [choice],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    again = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a4"),
        "p1",
        [choice],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert again.status == "duplicate"
    assert repository.own_company_lottery_bets("p1").total_cost == 2


def test_buy_accepts_a_different_ticket_in_the_same_round(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a5"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    second = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000a6"),
        "p1",
        [ticket((5, 6, 7, 8), 2)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert second.status == "bought"
    assert second.remaining == 3


def test_buy_enforces_the_daily_cap_per_beijing_day(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    for index in range(5):
        result = repository.buy_company_lottery_tickets(
            UUID(f"00000000-0000-0000-0000-0000000000b{index}"),
            "p1",
            [ticket((1, 2, 3, index), 1)],
            PRIMARY_GROUP_CHAT_ID,
            now,
        )
        assert result.status == "bought"

    blocked = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000bf"),
        "p1",
        [ticket((4, 5, 6, 7), 3)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert blocked.status == "daily_limit"
    assert blocked.remaining == 0
    assert repository.own_company_lottery_bets("p1").total_cost == 10


def test_daily_cap_resets_on_the_next_beijing_day(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    for index in range(5):
        repository.buy_company_lottery_tickets(
            UUID(f"00000000-0000-0000-0000-0000000000c{index}"),
            "p1",
            [ticket((1, 2, 3, index), 1)],
            PRIMARY_GROUP_CHAT_ID,
            now,
        )

    # 模拟 22:00 开奖，让下一期开出来
    with repository.transaction():
        with repository._session() as session:
            session.get(CompanyLotteryRoundRecord, view.id).state = "drawn"

    tomorrow = datetime(2026, 9, 15, 9, 0, tzinfo=BEIJING)
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, tomorrow)
    later = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000cf"),
        "p1",
        [ticket((4, 5, 6, 8), 3)],
        PRIMARY_GROUP_CHAT_ID,
        tomorrow,
    )

    assert later.status == "bought"
    assert later.round_number == 2


def test_buy_rejects_after_close(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    after_close = datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d1"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        after_close,
    )

    assert result.status == "closed"


def test_buy_rejects_when_balance_is_short(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_user(session, "poor", "穷鬼", 9, balance=1)
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d2"),
        "poor",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d3"),
        "nobody",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "not_joined"


def test_buy_rejects_when_disabled(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.update_company_lottery_settings(enabled=False)

    result = repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000d4"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "disabled"


# --------------------------------------------------------------------------- 机选

def test_quick_picks_buy_several_distinct_tickets(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e1"),
        "p1",
        5,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "bought"
    assert result.is_quick_pick is True
    assert len(result.tickets) == 5
    assert len({entry.as_key() for entry in result.tickets}) == 5
    assert result.cost == 10
    assert result.remaining == 0


def test_quick_picks_avoid_tickets_already_owned(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    owned = ticket((3, 7, 9, 10), 5)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000e2"),
        "p1",
        [owned],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e3"),
        "p1",
        4,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert owned.as_key() not in {entry.as_key() for entry in result.tickets}


def test_quick_picks_share_the_daily_cap(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000e4"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e5"),
        "p1",
        5,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "daily_limit"
    assert result.remaining == 4


def test_quick_pick_result_is_marked_on_the_bet(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_quick_picks(
        UUID("00000000-0000-0000-0000-0000000000e6"),
        "p1",
        1,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    history = repository.own_company_lottery_bets("p1")
    assert history.bets[0].is_quick_pick is True


# --------------------------------------------------------------------------- 账本

def test_sales_land_in_the_pool_ledger(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f1"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f2"),
        "p2",
        [ticket((5, 6, 7, 8), 2), ticket((1, 5, 6, 7), 3)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    pool, adjustment = repository.company_lottery_balances(PRIMARY_GROUP_CHAT_ID)

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


def test_pool_balance_matches_the_ledger_sum(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-0000000000f3"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    pool, _ = repository.company_lottery_balances(PRIMARY_GROUP_CHAT_ID)
    with repository._session() as session:
        total = session.scalar(
            select(
                func.coalesce(func.sum(CompanyLotteryPoolLedgerRecord.amount), 0)
            ).where(
                CompanyLotteryPoolLedgerRecord.group_chat_id == PRIMARY_GROUP_CHAT_ID,
                CompanyLotteryPoolLedgerRecord.account == "pool",
            )
        )

    assert pool == int(total)


# --------------------------------------------------------------------------- 多群

def test_rounds_and_pools_are_scoped_per_group(repository, seeded, now):
    first = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    second = repository.ensure_company_lottery_round(SECOND_GROUP_CHAT_ID, now)

    assert first.round_number == 1
    assert second.round_number == 1
    assert first.id != second.id

    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000101"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert repository.company_lottery_balances(PRIMARY_GROUP_CHAT_ID)[0] == 2
    assert repository.company_lottery_balances(SECOND_GROUP_CHAT_ID)[0] == 0


def test_own_history_is_cross_group(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.ensure_company_lottery_round(SECOND_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000102"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000103"),
        "p1",
        [ticket((5, 6, 7, 8), 2)],
        SECOND_GROUP_CHAT_ID,
        now,
    )

    history = repository.own_company_lottery_bets("p1")

    assert len(history.bets) == 2
    assert history.total_cost == 4
