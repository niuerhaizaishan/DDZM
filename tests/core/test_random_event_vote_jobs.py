from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.company_lottery import BEIJING
from dzmm_bot.core.schema import (
    Base,
    GroupChatRecord,
    OutboundRecord,
    PRIMARY_GROUP_CHAT_ID,
    RandomEventPollRecord,
    RandomEventRecord,
    RandomEventSceneOpeningRecord,
    RandomEventSceneRecord,
    RandomEventSceneSeatRecord,
    RandomEventScheduleRecord,
    UserRecord,
)

NOW = datetime(2026, 9, 15, 16, 20, tzinfo=BEIJING)
#: 目标场次 3 小时后，投票窗口 ≈2 小时 50 分钟
TARGET_AT = NOW + timedelta(hours=3)
JOINED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING)


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
def seeded(session_factory):
    with session_factory.begin() as session:
        session.add(
            GroupChatRecord(
                id=PRIMARY_GROUP_CHAT_ID,
                name="主群聊",
                chat_url=None,
                chatroom_id="room-main",
                listening_enabled=True,
                games_enabled=True,
                random_events_enabled=True,
                announcements_enabled=True,
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
                    balance=100,
                    joined_at=JOINED_AT,
                )
            )
    return session_factory


def add_scene(session, name, *, reward=6, target_rounds=3):
    scene = RandomEventSceneRecord(
        name=name,
        signup_text=f"{name} 报名",
        reward=reward,
        target_rounds=target_rounds,
        enabled=True,
        created_at=JOINED_AT,
    )
    session.add(scene)
    session.flush()
    session.add(
        RandomEventSceneOpeningRecord(
            scene_id=scene.id, position=1, name=f"{name} 事件", content="开场"
        )
    )
    session.add(
        RandomEventSceneSeatRecord(scene_id=scene.id, role="主持", capacity=1)
    )
    return scene


def add_schedule(session, when, *, status="pending", scene_name=None):
    record = RandomEventScheduleRecord(
        group_chat_id=PRIMARY_GROUP_CHAT_ID,
        event_date=when.date(),
        scheduled_at=when,
        status=status,
        scene_name=scene_name,
    )
    session.add(record)
    session.flush()
    return record


def add_active_event(session, *, state="in_progress"):
    """造一场还在进行中的随机事件，用来验证"上一场没结束就先不开投"。"""
    schedule = add_schedule(session, NOW - timedelta(hours=1), status=state)
    schedule.scene_name = "占用中"
    event = RandomEventRecord(
        group_chat_id=PRIMARY_GROUP_CHAT_ID,
        schedule_id=schedule.id,
        group_key="default",
        state=state,
        scene_name="占用中",
        event_name="占用中 事件",
        signup_text="报名",
        formal_opening_text="开场",
        reward=6,
        target_rounds=3,
        signup_deadline=NOW - timedelta(minutes=30),
        started_at=NOW - timedelta(hours=1),
    )
    session.add(event)
    session.flush()
    return event


def seed_scenes(session, names=("甲", "乙", "丙")):
    for name in names:
        add_scene(session, name)


def outbound_texts(repository, group_chat_id=PRIMARY_GROUP_CHAT_ID):
    with repository._session() as session:
        return [
            row.text
            for row in session.scalars(
                select(OutboundRecord)
                .where(OutboundRecord.group_chat_id == group_chat_id)
                .order_by(OutboundRecord.created_at, OutboundRecord.reply_index)
            )
        ]


def open_polls(repository):
    with repository._session() as session:
        return list(
            session.scalars(
                select(RandomEventPollRecord).order_by(
                    RandomEventPollRecord.created_at
                )
            )
        )


# ------------------------------------------------------------------ 开投

def test_poll_opens_after_the_previous_event_is_over(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)

    repository.run_random_event_jobs(NOW)

    polls = open_polls(repository)
    assert len(polls) == 1
    assert polls[0].status == "open"
    assert polls[0].announced_at is not None
    assert polls[0].closes_at == TARGET_AT - timedelta(minutes=10)
    texts = outbound_texts(repository)
    assert any("【事件投票】" in text for text in texts)
    assert any("/事件投票" in text for text in texts)


def test_poll_waits_while_an_event_is_still_running(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_active_event(session)
        add_schedule(session, TARGET_AT)

    repository.run_random_event_jobs(NOW)

    assert open_polls(repository) == []


def test_poll_opens_inside_the_fallback_window_even_if_an_event_runs(
    repository, seeded
):
    """离下一场只剩 20 分钟时不能再等上一场结束，否则来不及投票。"""
    with seeded.begin() as session:
        seed_scenes(session)
        add_active_event(session)
        add_schedule(session, NOW + timedelta(minutes=20))

    repository.run_random_event_jobs(NOW)

    assert len(open_polls(repository)) == 1


def test_poll_does_not_open_when_there_is_no_time_left_to_vote(repository, seeded):
    """目标场次只剩 5 分钟（截止时刻已过）就不投票了，交给开演时的旧随机路径。"""
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, NOW + timedelta(minutes=5))

    repository.run_random_event_jobs(NOW)

    assert open_polls(repository) == []


def test_poll_is_only_announced_once(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)

    repository.run_random_event_jobs(NOW)
    repository.run_random_event_jobs(NOW + timedelta(seconds=1))
    repository.run_random_event_jobs(NOW + timedelta(seconds=2))

    texts = outbound_texts(repository)
    assert sum(1 for text in texts if "【事件投票】" in text) == 1


# ------------------------------------------------------------------ 播报

def test_tally_is_broadcast_once_per_interval(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)
    repository.run_random_event_jobs(NOW)

    repository.run_random_event_jobs(NOW + timedelta(seconds=1))
    repository.run_random_event_jobs(NOW + timedelta(seconds=2))
    assert sum(1 for text in outbound_texts(repository) if "票型" in text) == 0

    repository.run_random_event_jobs(NOW + timedelta(minutes=30))
    assert sum(1 for text in outbound_texts(repository) if "票型" in text) == 1

    repository.run_random_event_jobs(NOW + timedelta(minutes=31))
    assert sum(1 for text in outbound_texts(repository) if "票型" in text) == 1

    repository.run_random_event_jobs(NOW + timedelta(minutes=61))
    assert sum(1 for text in outbound_texts(repository) if "票型" in text) == 2


# ------------------------------------------------------------------ 定稿

def test_poll_closes_at_the_deadline_and_freezes_the_winner(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)
    repository.run_random_event_jobs(NOW)
    with repository._session() as session:
        vote_position = 2

    repository.cast_random_event_vote("p1", vote_position, NOW)
    repository.cast_random_event_vote("p2", vote_position, NOW)
    repository.run_random_event_jobs(TARGET_AT - timedelta(minutes=10))

    polls = open_polls(repository)
    assert polls[0].status == "closed"
    with repository._session() as session:
        schedule = session.scalar(
            select(RandomEventScheduleRecord).where(
                RandomEventScheduleRecord.scheduled_at == TARGET_AT
            )
        )
    assert schedule.scene_name is not None
    assert schedule.status == "pending"
    texts = outbound_texts(repository)
    assert any("【事件投票·结果】" in text for text in texts)


def test_poll_closes_before_the_pre_notice_in_the_same_tick(repository, seeded):
    """截止（T−10）与预告（T−5）之间只差 5 分钟，但同一 tick 内也必须先定稿。"""
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)
    repository.run_random_event_jobs(NOW)

    repository.run_random_event_jobs(TARGET_AT - timedelta(minutes=5))

    texts = outbound_texts(repository)
    result_index = next(
        index for index, text in enumerate(texts) if "【事件投票·结果】" in text
    )
    notice_index = next(
        index for index, text in enumerate(texts) if "【随机事件预告】" in text
    )
    assert result_index < notice_index
    assert open_polls(repository)[0].status == "closed"


def test_closed_poll_is_not_reopened_for_the_same_schedule(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)
    repository.run_random_event_jobs(NOW)
    repository.run_random_event_jobs(TARGET_AT - timedelta(minutes=10))

    repository.run_random_event_jobs(TARGET_AT - timedelta(minutes=9))

    assert len(open_polls(repository)) == 1


# ------------------------------------------------------------------ 顺延

def test_poll_carries_over_when_the_target_schedule_is_skipped(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        first = add_schedule(session, TARGET_AT)
        second = add_schedule(session, TARGET_AT + timedelta(hours=2))
    repository.run_random_event_jobs(NOW)
    repository.cast_random_event_vote("p1", 1, NOW)
    with seeded.begin() as session:
        session.get(RandomEventScheduleRecord, first.id).status = "skipped"

    repository.run_random_event_jobs(NOW + timedelta(minutes=5))

    polls = open_polls(repository)
    assert len(polls) == 1
    assert polls[0].target_schedule_id == second.id
    assert polls[0].closes_at == second.scheduled_at - timedelta(minutes=10)
    with repository._session() as session:
        assert (
            len(
                session.scalars(
                    select(RandomEventPollRecord).where(
                        RandomEventPollRecord.target_schedule_id == first.id
                    )
                ).all()
            )
            == 0
        )
    texts = outbound_texts(repository)
    assert any("顺延" in text for text in texts)


def test_poll_is_cancelled_when_there_is_nothing_to_carry_over(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        only = add_schedule(session, TARGET_AT)
    repository.run_random_event_jobs(NOW)
    with seeded.begin() as session:
        session.get(RandomEventScheduleRecord, only.id).status = "cancelled"

    repository.run_random_event_jobs(NOW + timedelta(minutes=5))

    polls = open_polls(repository)
    assert polls[0].status == "cancelled"
    assert any("作废" in text for text in outbound_texts(repository))


def test_vote_jobs_do_nothing_when_voting_is_disabled(repository, seeded):
    with seeded.begin() as session:
        seed_scenes(session)
        add_schedule(session, TARGET_AT)
    repository.set_random_event_settings(
        ["20:00"], "{可选身份}", 15, 5, vote_enabled=False
    )

    repository.run_random_event_jobs(NOW)

    assert open_polls(repository) == []


def test_candidate_intro_shows_the_author(repository, seeded):
    """候选一行要带作者：投稿作品显示投稿人，后台自建的显示「官方」，名字长了截断。"""
    from dzmm_bot.core.schema import (
        RandomEventSubmissionRecord,
        UserRecord,
    )

    with seeded.begin() as session:
        submitted = add_scene(session, "投稿作品")
        add_scene(session, "后台自建")
        add_scene(session, "第三个")
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == "p1")
        )
        long_name = "名字特别特别长的投稿人"
        session.scalar(
            select(UserRecord).where(UserRecord.id == user_id)
        ).display_name = long_name
        session.add(
            RandomEventSubmissionRecord(
                number=1,
                user_id=user_id,
                status="approved",
                current_step="preview",
                content={},
                last_activity_at=JOINED_AT,
                created_at=JOINED_AT,
                updated_at=JOINED_AT,
                submitted_at=JOINED_AT,
                scene_id=submitted.id,
            )
        )
        add_schedule(session, TARGET_AT)

    repository.run_random_event_jobs(NOW)

    text = "\n".join(outbound_texts(repository))
    assert "by 名字特别特别长的…" in text
    assert "by 官方" in text