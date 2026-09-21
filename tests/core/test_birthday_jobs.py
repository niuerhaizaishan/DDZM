from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.schema import (
    BalanceTransactionRecord,
    Base,
    BirthdayGreetingRecord,
    BirthdayPreviewRecord,
    EmployeeBirthdayRecord,
    GroupChatRecord,
    OutboundRecord,
    PRIMARY_GROUP_CHAT_ID,
    UserRecord,
)

BEIJING = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 17, 9, 0, tzinfo=BEIJING)
JOINED_AT = datetime(2024, 2, 10, 12, 0, tzinfo=BEIJING)
OTHER_GROUP_A = UUID("00000000-0000-0000-0000-0000000000a1")
OTHER_GROUP_B = UUID("00000000-0000-0000-0000-0000000000b2")


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def repository(session_factory):
    from dzmm_bot.core.repository import CoreRepository

    return CoreRepository(session_factory)


@pytest.fixture
def seeded(session_factory, repository):
    """一个主群 + 两个普通群，三个员工。"""
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=main", NOW
    )
    with session_factory.begin() as session:
        for group_id, name, chatroom in (
            (OTHER_GROUP_A, "二群", "room-a"),
            (OTHER_GROUP_B, "三群", "room-b"),
        ):
            session.add(
                GroupChatRecord(
                    id=group_id,
                    name=name,
                    chat_url=None,
                    chatroom_id=chatroom,
                    listening_enabled=True,
                    games_enabled=True,
                    random_events_enabled=False,
                    announcements_enabled=True,
                    adult_shop_enabled=False,
                    performances_enabled=False,
                    created_at=JOINED_AT,
                    updated_at=JOINED_AT,
                )
            )
        for index, name in enumerate(("小明", "小红", "小刚"), start=1):
            session.add(
                UserRecord(
                    platform_id=f"p{index}",
                    display_name=name,
                    employee_number=index,
                    balance=0,
                    joined_at=JOINED_AT,
                )
            )
    return session_factory


def enable(repository, **overrides):
    """把生日开关打开并按需改配置（设置是整份覆盖，所以先读再写）。"""
    updated = replace(repository.get_birthday_settings(), enabled=True, **overrides)
    repository.set_birthday_settings(**vars(updated))
    return updated


def give_birthday(session_factory, platform_id, month, day, *, visibility="public"):
    from sqlalchemy import select as sa_select

    with session_factory.begin() as session:
        user_id = session.scalar(
            sa_select(UserRecord.id).where(UserRecord.platform_id == platform_id)
        )
        session.add(
            EmployeeBirthdayRecord(
                user_id=user_id,
                month=month,
                day=day,
                visibility=visibility,
                edit_count=0,
                edit_count_year=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )


def outbound(session_factory):
    with session_factory() as session:
        return list(
            session.scalars(
                select(OutboundRecord).order_by(OutboundRecord.created_at)
            )
        )


def texts(session_factory):
    return [record.text for record in outbound(session_factory)]


def greetings(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(BirthdayGreetingRecord)))


def previews(session_factory):
    with session_factory() as session:
        return list(session.scalars(select(BirthdayPreviewRecord)))


def balance_of(session_factory, platform_id):
    with session_factory() as session:
        return session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == platform_id)
        )


# ------------------------------------------------------------------ 祝福

def test_the_greeting_fires_once_at_the_configured_time(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW - timedelta(minutes=1))
    assert texts(seeded) == []

    repository.run_birthday_jobs(NOW)
    for _ in range(3):
        repository.run_birthday_jobs(NOW)

    assert len(greetings(seeded)) == 1
    assert len(outbound(seeded)) == 3  # 三个群各一条
    assert balance_of(seeded, "p1") == 20


def test_the_greeting_is_broadcast_per_group_but_paid_once(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW)
    assert len(outbound(seeded)) == 3  # 第一天三个群都收到

    with seeded.begin() as session:
        session.query(OutboundRecord).delete()  # 只看关了 B 群之后那一批
        session.scalar(
            select(GroupChatRecord).where(GroupChatRecord.id == OTHER_GROUP_B)
        ).birthdays_enabled = False
    give_birthday(seeded, "p2", 9, 18)
    repository.run_birthday_jobs(NOW + timedelta(days=1))

    per_group = {}
    for record in outbound(seeded):
        per_group.setdefault(record.group_chat_id, []).append(record.text)
    assert set(per_group) == {PRIMARY_GROUP_CHAT_ID, OTHER_GROUP_A}
    assert len(greetings(seeded)) == 2
    assert balance_of(seeded, "p1") == 20
    assert balance_of(seeded, "p2") == 20


def test_the_greeting_text_lists_the_perks(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW)

    text = texts(seeded)[0]
    assert "【生日祝福】" in text
    assert "小明" in text
    assert "生日礼金 20 摸鱼币" in text
    assert "8 折" in text
    assert "打卡 2 倍" in text
    assert "前 5 注公司买单" in text
    assert "/随礼" in text
    assert "入职 2 年 7 个月" in text


def test_a_private_birthday_stays_private(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17, visibility="private")

    repository.run_birthday_jobs(NOW)

    assert outbound(seeded) == []
    assert greetings(seeded) == []
    assert balance_of(seeded, "p1") == 0


def test_two_birthdays_share_one_message(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)
    give_birthday(seeded, "p2", 9, 17)

    repository.run_birthday_jobs(NOW)

    assert len(greetings(seeded)) == 2
    assert balance_of(seeded, "p1") == 20
    assert balance_of(seeded, "p2") == 20
    assert len(outbound(seeded)) == 3  # 仍然是每群一条
    assert "小明、小红" in texts(seeded)[0]


def test_the_greeting_is_backfilled_later_the_same_day(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW + timedelta(hours=13))

    assert len(greetings(seeded)) == 1


def test_backfill_can_be_turned_off(repository, seeded):
    enable(repository, same_day_backfill=False)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW + timedelta(hours=13))

    assert greetings(seeded) == []


def test_the_master_switch_keeps_everything_silent(repository, seeded):
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW)

    assert outbound(seeded) == []
    assert greetings(seeded) == []
    assert balance_of(seeded, "p1") == 0


def test_the_gift_counts_into_today_income(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_birthday_jobs(NOW)

    with seeded() as session:
        sources = {
            record.source
            for record in session.scalars(select(BalanceTransactionRecord))
        }
    assert sources == {"birthday_gift"}
    with seeded() as session:
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )
    assert repository.today_income(user_id, NOW) == 20


def test_the_daily_job_runs_the_birthday_task(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 17)

    repository.run_daily_jobs(NOW)

    assert len(greetings(seeded)) == 1


def test_a_leap_day_birthday_is_greeted_on_feb_28(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 2, 29)
    leap_now = datetime(2027, 2, 28, 9, 0, tzinfo=BEIJING)

    repository.run_birthday_jobs(leap_now)

    assert len(greetings(seeded)) == 1
    assert "小明" in texts(seeded)[0]


# ------------------------------------------------------------------ 预告

def test_the_preview_warns_the_day_before(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 18)

    repository.run_birthday_jobs(NOW)
    assert "【生日预告】" not in "".join(texts(seeded))

    evening = NOW + timedelta(hours=11)  # 20:00
    repository.run_birthday_jobs(evening)
    repository.run_birthday_jobs(evening)

    warnings = [text for text in texts(seeded) if "【生日预告】" in text]
    assert len(warnings) == 3  # 每群一条，但每人每年只播一次
    assert len(previews(seeded)) == 1
    assert "明天是 小明 的生日" in warnings[0]


def test_the_preview_can_be_switched_off(repository, seeded):
    enable(repository, preview_enabled=False)
    give_birthday(seeded, "p1", 9, 18)

    repository.run_birthday_jobs(NOW + timedelta(hours=11))

    assert previews(seeded) == []
    assert [text for text in texts(seeded) if "预告" in text] == []


def test_the_preview_is_not_repeated_the_next_evening(repository, seeded):
    enable(repository)
    give_birthday(seeded, "p1", 9, 18)

    repository.run_birthday_jobs(NOW + timedelta(hours=11))
    repository.run_birthday_jobs(NOW + timedelta(days=1, hours=11))

    assert len(previews(seeded)) == 1
