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


def seed_pool(repository, group_id, amount=100):
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


# --------------------------------------------------------------------------- 引导购票

def test_draft_starts_and_reports_its_target(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.start_company_lottery_draft(
        "p1", 5, PRIMARY_GROUP_CHAT_ID, now
    )

    assert result.status == "started"
    assert result.target == 5
    assert result.collected == 0
    assert result.remaining == 5


def test_draft_target_is_capped_by_the_daily_limit(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000201"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.start_company_lottery_draft(
        "p1", 5, PRIMARY_GROUP_CHAT_ID, now
    )

    assert result.status == "started"
    assert result.target == 4


def test_draft_collects_manual_tickets_until_ready(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 2, PRIMARY_GROUP_CHAT_ID, now)

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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 2, PRIMARY_GROUP_CHAT_ID, now)
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 3, PRIMARY_GROUP_CHAT_ID, now)
    choice = ticket((1, 2, 3, 4), 1)
    repository.append_company_lottery_draft("p1", choice, now)

    again = repository.append_company_lottery_draft("p1", choice, now)

    assert again.status == "duplicate"
    assert again.collected == 1


def test_draft_rejects_a_ticket_already_owned_this_round(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    owned = ticket((1, 2, 3, 4), 1)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000202"),
        "p1",
        [owned],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    repository.start_company_lottery_draft("p1", 3, PRIMARY_GROUP_CHAT_ID, now)

    again = repository.append_company_lottery_draft("p1", owned, now)

    assert again.status == "duplicate"


def test_draft_expires_after_the_timeout(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 3, PRIMARY_GROUP_CHAT_ID, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)

    later = datetime(2026, 9, 14, 12, 16, tzinfo=BEIJING)

    assert repository.load_company_lottery_draft("p1", later) is None
    late_append = repository.append_company_lottery_draft(
        "p1", ticket((5, 6, 7, 8), 2), later
    )
    assert late_append.status == "no_draft"


def test_cancelling_a_draft_never_touches_the_balance(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 3, PRIMARY_GROUP_CHAT_ID, now)
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 3, PRIMARY_GROUP_CHAT_ID, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)
    repository.append_company_lottery_draft("p1", ticket((5, 6, 7, 8), 2), now)
    repository.append_company_lottery_draft("p1", ticket((1, 5, 6, 7), 3), now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000203"),
        "p1",
        PRIMARY_GROUP_CHAT_ID,
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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 2, PRIMARY_GROUP_CHAT_ID, now)
    repository.append_quick_pick_to_draft("p1", now)
    repository.append_quick_pick_to_draft("p1", now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000204"),
        "p1",
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "bought"
    assert result.purchase.is_quick_pick is True

    history = repository.own_company_lottery_bets("p1")
    assert all(bet.is_quick_pick for bet in history.bets)


def test_confirming_without_a_draft_reports_no_draft(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000205"),
        "p1",
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "no_draft"


def test_confirming_a_draft_respects_the_current_balance(repository, session_factory, now):
    with session_factory.begin() as session:
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊")
        add_user(session, "p3", "小刚", 3, balance=3)
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p3", 3, PRIMARY_GROUP_CHAT_ID, now)
    repository.append_company_lottery_draft("p3", ticket((1, 2, 3, 4), 1), now)
    repository.append_company_lottery_draft("p3", ticket((5, 6, 7, 8), 2), now)

    result = repository.confirm_company_lottery_draft(
        UUID("00000000-0000-0000-0000-000000000206"),
        "p3",
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "insufficient_balance"
    with repository._session() as session:
        bets = session.scalar(select(func.count()).select_from(CompanyLotteryBetRecord))
        user = session.scalar(select(UserRecord).where(UserRecord.platform_id == "p3"))
    assert bets == 0
    assert user.balance == 3


def test_starting_a_draft_again_replaces_the_previous_one(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.start_company_lottery_draft("p1", 5, PRIMARY_GROUP_CHAT_ID, now)
    repository.append_company_lottery_draft("p1", ticket((1, 2, 3, 4), 1), now)

    repository.start_company_lottery_draft("p1", 2, PRIMARY_GROUP_CHAT_ID, now)

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
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    assert repository.close_company_lottery_round(
        PRIMARY_GROUP_CHAT_ID, now
    ) == 0
    assert repository.close_company_lottery_round(
        PRIMARY_GROUP_CHAT_ID, datetime(2026, 9, 14, 21, 50, tzinfo=BEIJING)
    ) == 1
    assert repository.close_company_lottery_round(
        PRIMARY_GROUP_CHAT_ID, datetime(2026, 9, 14, 21, 55, tzinfo=BEIJING)
    ) == 0

    view = repository.current_company_lottery_round(PRIMARY_GROUP_CHAT_ID)
    assert view.state == "closed"


def test_draw_waits_for_the_draw_time(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)

    assert repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now) is None


def test_draw_pays_the_head_prize(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    seed_pool(repository, PRIMARY_GROUP_CHAT_ID, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000301"),
        "p1",
        [answer_for(repository, view.id)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    assert result is not None
    assert result.round_number == 1
    assert result.winner_count == 1
    assert result.winners[0].tier == "head"
    assert result.winners[0].amount == 100
    assert result.haircut is None
    # 100 起始 − 2 购票 + 100 中奖
    assert balance_of(repository, "p1") == 198


def test_draw_pays_a_fifth_prize_for_a_blue_hit(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    answer = answer_for(repository, view.id)
    near_miss = Ticket(reds=(9, 10, 8, 7), blue=answer.blue)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000302"),
        "p1",
        [near_miss],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

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
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000303"),
        "p1",
        [losing_ticket(answer)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    assert result.winner_count == 0
    assert result.paid_total == 0
    assert balance_of(repository, "p1") == 98


def test_draw_is_idempotent(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    seed_pool(repository, PRIMARY_GROUP_CHAT_ID, 100)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000304"),
        "p1",
        [answer_for(repository, view.id)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    first = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)
    second = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

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
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    seed_pool(repository, PRIMARY_GROUP_CHAT_ID, 200)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000305"),
        "p1",
        [answer, Ticket(reds=answer.reds, blue=answer.blue % 6 + 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    # 两张中奖票面值 200，合并后封顶 100
    assert result.payable == 100
    assert result.paid_total == 100
    assert result.capped_users == (result.capped_users[0],)
    assert len(result.capped_users) == 1
    assert sum(winner.amount for winner in result.winners) == 100


def test_draw_haircuts_when_the_pool_is_short(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000306"),
        "p1",
        [answer_for(repository, view.id)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    # 奖池只有 2 币，应付 100，按比例折算
    assert result.payable == 100
    assert result.haircut is not None
    assert result.paid_total == 2
    assert result.winners[0].amount == 2
    assert result.pool_balance == 0
    assert balance_of(repository, "p1") == 100


def test_draw_pours_overflow_into_the_adjustment_fund(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    seed_pool(repository, PRIMARY_GROUP_CHAT_ID, 200)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000307"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    pool, adjustment = repository.company_lottery_balances(PRIMARY_GROUP_CHAT_ID)
    assert result.pool_balance == 200
    assert pool == 200
    assert adjustment == 2


def test_draw_keeps_the_head_pool_rolling_when_nobody_wins(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    seed_pool(repository, PRIMARY_GROUP_CHAT_ID, 100)
    answer = answer_for(repository, view.id)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000308"),
        "p1",
        [losing_ticket(answer)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    first = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)
    pool_after_first, _ = repository.company_lottery_balances(PRIMARY_GROUP_CHAT_ID)

    assert first.winner_count == 0
    assert first.paid_total == 0
    assert pool_after_first == 102


def test_draw_opens_the_next_round(repository, seeded, now):
    repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    repository.buy_company_lottery_tickets(
        UUID("00000000-0000-0000-0000-000000000309"),
        "p1",
        [ticket((1, 2, 3, 4), 1)],
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    result = repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    assert result.next_round_number == 2
    view = repository.current_company_lottery_round(PRIMARY_GROUP_CHAT_ID)
    assert view.round_number == 2
    assert view.state == "open"
    assert view.answer is None
    assert view.tickets_sold == 0


def test_draw_reveals_the_answer_only_after_settlement(repository, seeded, now):
    view = repository.ensure_company_lottery_round(PRIMARY_GROUP_CHAT_ID, now)
    expected = answer_for(repository, view.id)
    assert view.answer is None

    repository.draw_company_lottery_round(PRIMARY_GROUP_CHAT_ID, DRAW_AT)

    settled = repository.company_lottery_round_by_number(PRIMARY_GROUP_CHAT_ID, 1)
    assert settled.state == "drawn"
    assert settled.answer == expected
    assert settled.salt
