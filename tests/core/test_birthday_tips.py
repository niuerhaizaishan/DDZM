from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.schema import (
    BalanceTransactionRecord,
    Base,
    BirthdayGreetingRecord,
    BirthdayTipRecord,
    EmployeeBirthdayRecord,
    InboundRecord,
    OutboundRecord,
    UserRecord,
)

BEIJING = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 17, 9, 30, tzinfo=BEIJING)
JOINED_AT = datetime(2024, 2, 10, 12, 0, tzinfo=BEIJING)


@pytest.fixture
def harness():
    from dzmm_bot.core.repository import CoreRepository

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=tips", NOW
    )
    for platform_id, name in (("p1", "小明"), ("p2", "小红"), ("p3", "小刚")):
        repository.create_user(platform_id, name, JOINED_AT, 100)
    settings = repository.get_birthday_settings()
    from dataclasses import replace

    updated = replace(settings, enabled=True)
    repository.set_birthday_settings(**vars(updated))
    with factory.begin() as session:
        for platform_id, month, day in (("p1", 9, 17), ("p2", 9, 20)):
            session.add(
                EmployeeBirthdayRecord(
                    user_id=session.scalar(
                        select(UserRecord.id).where(UserRecord.platform_id == platform_id)
                    ),
                    month=month,
                    day=day,
                    visibility="public",
                    edit_count=0,
                    edit_count_year=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
    repository.run_birthday_jobs(NOW)  # 先让祝福发出，随礼窗口打开
    return repository, factory, group


def inbound(factory, message_id, platform_id, content="/随礼 10"):
    with factory.begin() as session:
        session.add(
            InboundRecord(
                platform_message_id=message_id,
                sender_platform_id=platform_id,
                content=content,
                received_at=NOW,
                status="accepted",
                source_type="group",
                created_at=NOW,
            )
        )


def balance_of(factory, platform_id):
    with factory() as session:
        return session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == platform_id)
        )


def tip(repository, factory, platform_id, amount=10, *, message_id="tip-1", name=None):
    inbound(factory, message_id, platform_id)
    return repository.tip_birthday(
        platform_id,
        amount,
        NOW,
        platform_message_id=message_id,
        recipient_name=name,
    )


def test_a_tip_moves_coins_between_two_people(harness):
    repository, factory, _ = harness

    result = tip(repository, factory, "p2")

    assert result.status == "tipped"
    assert result.recipient_name == "小明"
    assert balance_of(factory, "p2") == 100 - 10
    assert balance_of(factory, "p1") == 100 + 20 + 10  # 礼金 20 + 随礼 10
    with factory() as session:
        sources = sorted(
            record.source for record in session.scalars(select(BalanceTransactionRecord))
        )
        assert "birthday_tip_out" in sources
        assert "birthday_tip_in" in sources
        assert len(list(session.scalars(select(BirthdayTipRecord)))) == 1


def test_the_amount_is_capped(harness):
    repository, factory, _ = harness

    result = tip(repository, factory, "p2", amount=50)

    assert result.status == "invalid_amount"
    assert result.maximum == 20
    assert balance_of(factory, "p2") == 100
    with factory() as session:
        assert list(session.scalars(select(BirthdayTipRecord))) == []


def test_nobody_can_tip_themselves(harness):
    repository, factory, _ = harness

    result = tip(repository, factory, "p1")

    assert result.status == "self_tip"
    assert balance_of(factory, "p1") == 100 + 20


def test_the_same_person_can_only_tip_once(harness):
    repository, factory, _ = harness
    tip(repository, factory, "p2", message_id="tip-a")

    again = tip(repository, factory, "p2", message_id="tip-b")

    assert again.status == "already_tipped"
    assert balance_of(factory, "p2") == 100 - 10


def test_a_replayed_message_does_not_transfer_twice(harness):
    repository, factory, _ = harness
    inbound(factory, "same-message", "p2")

    first = repository.tip_birthday(
        "p2", 10, NOW, platform_message_id="same-message"
    )
    second = repository.tip_birthday(
        "p2", 10, NOW, platform_message_id="same-message"
    )

    assert first.status == "tipped"
    assert second.status == "already_tipped"
    assert second.amount == 10
    assert balance_of(factory, "p2") == 100 - 10


def test_a_tip_after_the_window_is_refused(harness):
    repository, factory, _ = harness
    late = NOW + timedelta(hours=3)

    inbound(factory, "late-tip", "p2")
    result = repository.tip_birthday(
        "p2", 10, late, platform_message_id="late-tip"
    )

    assert result.status == "no_birthday"
    assert balance_of(factory, "p2") == 100


def test_a_poor_colleague_cannot_tip(harness):
    repository, factory, _ = harness
    with factory.begin() as session:
        session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "p2")
        ).balance = 3

    result = tip(repository, factory, "p2")

    assert result.status == "insufficient_balance"
    assert balance_of(factory, "p2") == 3


def test_the_settlement_fills_the_totals_and_announces_once(harness):
    repository, factory, _ = harness
    tip(repository, factory, "p2", amount=10, message_id="s-1")
    inbound(factory, "s-2", "p3")
    repository.tip_birthday("p3", 5, NOW, platform_message_id="s-2")
    with factory.begin() as session:
        session.query(OutboundRecord).delete()

    close_at = NOW + timedelta(minutes=61)
    repository.run_birthday_jobs(close_at)
    repository.run_birthday_jobs(close_at)

    with factory() as session:
        greeting = session.scalar(select(BirthdayGreetingRecord))
        texts = [record.text for record in session.scalars(select(OutboundRecord))]
    assert greeting is not None
    assert greeting.tips_count == 2
    assert greeting.tips_total == 15
    assert greeting.status == "settled"
    summaries = [text for text in texts if "随礼" in text and "收到" in text]
    assert len(summaries) == 1
    assert "2 位同事" in summaries[0]
    assert "15 摸鱼币" in summaries[0]


def test_tipping_stays_allowed_while_a_random_event_runs():
    from dzmm_bot.core.service import _RANDOM_EVENT_INDEPENDENT_COMMANDS

    assert "/随礼" in _RANDOM_EVENT_INDEPENDENT_COMMANDS


def test_the_tip_command_is_registered():
    from dzmm_bot.core.commands import _COMMANDS
    from dzmm_bot.core.reply_templates import template_definition

    assert "/随礼" in _COMMANDS
    assert template_definition("/随礼", "tipped") is not None

# ---------------------------------------------------------- 指令层（/随礼）

def command_harness(harness):
    from dzmm_bot.core.commands import GroupCommandHandler

    repository, factory, group = harness
    return GroupCommandHandler(repository), factory, group


def send_tip(handler, factory, group, platform_id, content, *, message_id):
    from dzmm_bot.runtime.contracts import InboundMessage

    inbound(factory, message_id, platform_id, content)
    reply = handler.handle(
        InboundMessage(
            message_id,
            platform_id,
            content,
            NOW,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )
    return "\n".join(reply) if isinstance(reply, list) else (reply or "")


def test_the_tip_command_transfers_and_replies(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(handler, factory, group, "p2", "/随礼 10", message_id="c-1")

    assert "已给 小明 随礼 10" in reply
    assert balance_of(factory, "p2") == 100 - 10
    assert balance_of(factory, "p1") == 120 + 10


def test_the_tip_command_needs_an_amount(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(handler, factory, group, "p2", "/随礼", message_id="c-2")

    assert "用法：/随礼 金额" in reply
    assert balance_of(factory, "p2") == 100


def test_the_tip_command_rejects_a_non_number(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(handler, factory, group, "p2", "/随礼 一点心意", message_id="c-3")

    assert "金额得是正整数" in reply
    assert balance_of(factory, "p2") == 100


def test_the_tip_command_rejects_an_amount_over_the_cap(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(handler, factory, group, "p2", "/随礼 50", message_id="c-4")

    assert "不超过 20" in reply
    assert balance_of(factory, "p2") == 100


def test_the_tip_command_refuses_a_second_tip_from_the_same_person(harness):
    handler, factory, group = command_harness(harness)
    send_tip(handler, factory, group, "p2", "/随礼 6", message_id="c-5")

    reply = send_tip(handler, factory, group, "p2", "/随礼 6", message_id="c-6")

    assert "已经给 小明 随过 6" in reply
    assert balance_of(factory, "p2") == 100 - 6


def test_the_tip_command_refuses_self_tipping(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(handler, factory, group, "p1", "/随礼 5", message_id="c-7")

    assert "自己给自己随礼" in reply


def test_the_tip_command_accepts_a_named_recipient(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(
        handler, factory, group, "p3", "/随礼 小明 8", message_id="c-8"
    )

    assert "已给 小明 随礼 8" in reply
    assert balance_of(factory, "p1") == 120 + 8


def test_the_tip_command_reports_a_stranger(harness):
    handler, factory, group = command_harness(harness)

    reply = send_tip(
        handler, factory, group, "p3", "/随礼 隔壁老王 8", message_id="c-9"
    )

    assert "没有这个名字" in reply
    assert balance_of(factory, "p3") == 100


def test_the_tip_command_says_so_when_nobody_is_celebrating(harness):
    handler, factory, group = command_harness(harness)
    late = NOW + timedelta(hours=5)
    inbound(factory, "c-10", "p2", "/随礼 5")

    reply = handler.handle(
        __import__("dzmm_bot.runtime.contracts", fromlist=["InboundMessage"]).InboundMessage(
            "c-10", "p2", "/随礼 5", late, source_type="group", chatroom_id=group.chatroom_id
        )
    )

    assert "没有人在过生日" in reply

