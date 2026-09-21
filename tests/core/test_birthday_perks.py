"""P2：四项寿星特权。"""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.schema import (
    Base,
    BirthdayGreetingRecord,
    EmployeeBirthdayRecord,
    InboundRecord,
    ItemRecord,
    UserItemRecord,
    UserRecord,
)

BEIJING = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 17, 10, 0, tzinfo=BEIJING)
JOINED_AT = datetime(2024, 2, 10, 12, 0, tzinfo=BEIJING)
OTHER_DAY = datetime(2026, 9, 18, 10, 0, tzinfo=BEIJING)


@pytest.fixture
def harness():
    from dzmm_bot.core.repository import CoreRepository

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=perks", NOW
    )
    repository.create_user("p1", "小明", JOINED_AT, 100)
    repository.create_user("p2", "小红", JOINED_AT, 100)
    return repository, factory, group


def enable(repository, **overrides):
    updated = replace(repository.get_birthday_settings(), enabled=True, **overrides)
    repository.set_birthday_settings(**vars(updated))
    return updated


def give_birthday(factory, platform_id, month, day):
    with factory.begin() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == platform_id)
        )
        session.add(
            EmployeeBirthdayRecord(
                user_id=user_id,
                month=month,
                day=day,
                visibility="public",
                edit_count=0,
                edit_count_year=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def balance_of(factory, platform_id):
    with factory() as session:
        return session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == platform_id)
        )


# ---------------------------------------------------------------- 打卡双倍

def _check_in_reply(harness, platform_id, now=NOW):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.runtime.contracts import InboundMessage

    repository, factory, group = harness
    handler = GroupCommandHandler(repository)
    return handler.handle(
        InboundMessage(
            f"checkin-{platform_id}-{now.date()}",
            platform_id,
            "/打卡",
            now,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )


def test_checkin_is_doubled_on_the_birthday(harness):
    repository, factory, _ = harness
    enable(repository)
    give_birthday(factory, "p1", 9, 17)

    _check_in_reply(harness, "p1")

    assert balance_of(factory, "p1") == 100 + 10  # 基础 5 × 2


def test_checkin_is_untouched_on_a_normal_day(harness):
    repository, factory, _ = harness
    enable(repository)
    give_birthday(factory, "p1", 9, 20)

    _check_in_reply(harness, "p1")

    assert balance_of(factory, "p1") == 100 + 5


def test_checkin_is_untouched_when_the_feature_is_off(harness):
    _, factory, _ = harness
    give_birthday(factory, "p1", 9, 17)

    _check_in_reply(harness, "p1")

    assert balance_of(factory, "p1") == 100 + 5


# ------------------------------------------------------------ 随机事件加成

def test_the_completion_reward_is_boosted_on_the_birthday():
    from dzmm_bot.core.repository import birthday_completion_reward

    settings = replace(
        _settings_stub(), enabled=True, event_reward_bonus_percent=50
    )

    assert birthday_completion_reward(6, settings) == 9
    assert birthday_completion_reward(6, None) == 6
    assert birthday_completion_reward(5, None) == 5


def _settings_stub():
    from dzmm_bot.core.repository import BirthdaySettings

    return BirthdaySettings(
        enabled=False,
        greet_time="09:00",
        preview_enabled=True,
        preview_time="20:00",
        gift_amount=20,
        same_day_backfill=True,
        edit_limit_per_year=1,
        checkin_multiplier=2,
        shop_discount_percent=80,
        lottery_free_tickets=5,
        event_reward_bonus_percent=0,
        tips_enabled=True,
        tip_max_amount=20,
        tip_window_minutes=60,
        anniversary_enabled=True,
        greet_template="x",
        preview_template="x",
        tips_summary_template="x",
    )


# ---------------------------------------------------------------- 购彩免单

def _buy_tickets(harness, platform_id, count, *, message_id, now=NOW):
    repository, factory, group = harness
    repository.run_company_lottery_jobs(now)
    return repository.buy_quick_picks(message_id, platform_id, count, now)


def test_the_first_tickets_are_free_on_the_birthday(harness):
    repository, factory, _ = harness
    enable(repository, lottery_free_tickets=2)
    give_birthday(factory, "p1", 9, 17)
    with factory.begin() as session:
        session.add(
            InboundRecord(
                platform_message_id="seed",
                sender_platform_id="p1",
                content="/购买彩票 机选 3",
                received_at=NOW,
                status="accepted",
                source_type="group",
                created_at=NOW,
            )
        )

    repository.run_birthday_jobs(NOW)  # 祝福发出后免单资格才生效
    result = _buy_tickets(harness, "p1", 3, message_id="seed")

    assert result.status == "bought", result.status
    assert balance_of(factory, "p1") == 100 + 20 - 2  # 礼金 20，2 注免单只付 1 注
    with factory() as session:
        used = session.scalar(
            select(BirthdayGreetingRecord.lottery_tickets).where(
                BirthdayGreetingRecord.user_id
                == session.scalar(
                    select(UserRecord.id).where(UserRecord.platform_id == "p1")
                )
            )
        )
    assert used == 2


def test_tickets_are_not_free_on_a_normal_day(harness):
    repository, factory, _ = harness
    enable(repository, lottery_free_tickets=5)
    give_birthday(factory, "p1", 9, 20)
    with factory.begin() as session:
        session.add(
            InboundRecord(
                platform_message_id="seed2",
                sender_platform_id="p1",
                content="/购买彩票 机选 2",
                received_at=NOW,
                status="accepted",
                source_type="group",
                created_at=NOW,
            )
        )

    result = _buy_tickets(harness, "p1", 2, message_id="seed2")

    assert result.status == "bought", result.status
    assert balance_of(factory, "p1") == 100 - 4


# ---------------------------------------------------------------- 商店折扣

def test_the_shop_price_is_discounted_on_the_birthday(harness):
    repository, factory, _ = harness
    enable(repository)
    give_birthday(factory, "p1", 9, 17)
    with factory() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )
        other_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p2")
        )

    assert repository.shop_price_for(10, user_id, NOW) == 8
    assert repository.shop_price_for(10, other_id, NOW) == 10
    assert repository.shop_price_for(10, user_id, OTHER_DAY) == 10
    assert repository.shop_price_for(10, None, NOW) == 10


def test_a_discounted_purchase_charges_once(harness):
    repository, factory, group = harness
    enable(repository)
    give_birthday(factory, "p1", 9, 17)
    repository.list_shop_items()
    with factory() as session:
        item = session.scalar(
            select(ItemRecord)
            .where(ItemRecord.enabled.is_(True))
            .order_by(ItemRecord.public_number)
        )
        number, price = item.public_number, item.price
    with factory.begin() as session:
        session.add(
            InboundRecord(
                platform_message_id="shop-buy",
                sender_platform_id="p1",
                content=f"/购买 {number}",
                received_at=NOW,
                status="accepted",
                source_type="group",
                chatroom_id=group.chatroom_id,
                created_at=NOW,
            )
        )
        inbound_id = session.scalar(
            select(InboundRecord.id).where(
                InboundRecord.platform_message_id == "shop-buy"
            )
        )

    result = repository.purchase_shop_item(
        inbound_id, "p1", number, group.id, NOW
    )

    assert result.status in {"purchased", "adult_disabled", "rank_required"}
    if result.status == "bought":
        expected = price * 80 // 100
        assert balance_of(factory, "p1") == 100 - expected
        with factory() as session:
            assert session.scalar(
                select(UserItemRecord.quantity).where(
                    UserItemRecord.user_id
                    == session.scalar(
                        select(UserRecord.id).where(UserRecord.platform_id == "p1")
                    )
                )
            ) == 1
