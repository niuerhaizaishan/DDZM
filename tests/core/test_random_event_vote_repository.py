from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.company_lottery import BEIJING
from dzmm_bot.core.schema import (
    Base,
    GroupChatRecord,
    PRIMARY_GROUP_CHAT_ID,
    RandomEventPollCandidateRecord,
    RandomEventPollRecord,
    RandomEventPollVoteRecord,
    RandomEventRecord,
    RandomEventSceneOpeningRecord,
    RandomEventSceneRecord,
    RandomEventSceneSeatRecord,
    RandomEventScheduleRecord,
    RandomEventSubmissionRecord,
    UserRecord,
)

OTHER_GROUP_CHAT_ID = UUID("00000000-0000-0000-0000-0000000000fe")
NOW = datetime(2026, 9, 15, 16, 20, tzinfo=BEIJING)
TARGET_AT = datetime(2026, 9, 15, 20, 0, tzinfo=BEIJING)
CLOSE_AT = TARGET_AT - timedelta(minutes=10)
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
        add_group(session, PRIMARY_GROUP_CHAT_ID, "主群聊", "room-main")
        add_group(session, OTHER_GROUP_CHAT_ID, "闲置群", "room-other", enabled=False)
        for index, name in enumerate(("小明", "小红", "小刚"), start=1):
            add_user(session, f"p{index}", name, index)
    return session_factory


def add_group(session, group_id, name, chatroom_id, *, enabled=True):
    session.add(
        GroupChatRecord(
            id=group_id,
            name=name,
            chat_url=None,
            chatroom_id=chatroom_id,
            listening_enabled=True,
            games_enabled=True,
            random_events_enabled=enabled,
            announcements_enabled=True,
            created_at=JOINED_AT,
            updated_at=JOINED_AT,
        )
    )


def add_user(session, platform_id, display_name, employee_number):
    session.add(
        UserRecord(
            platform_id=platform_id,
            display_name=display_name,
            employee_number=employee_number,
            balance=100,
            joined_at=JOINED_AT,
        )
    )


def add_scene(session, name, *, events=("开场白",), seats=(("主持", 1),), reward=6,
              target_rounds=3, created_at=None):
    scene = RandomEventSceneRecord(
        name=name,
        signup_text=f"{name} 报名",
        reward=reward,
        target_rounds=target_rounds,
        enabled=True,
        created_at=created_at or JOINED_AT,
    )
    session.add(scene)
    session.flush()
    for position, content in enumerate(events, start=1):
        session.add(
            RandomEventSceneOpeningRecord(
                scene_id=scene.id,
                position=position,
                name=f"{name} 事件{position}",
                content=content,
            )
        )
    for role, capacity in seats:
        session.add(
            RandomEventSceneSeatRecord(
                scene_id=scene.id, role=role, capacity=capacity
            )
        )
    return scene


def add_schedule(session, *, when=TARGET_AT, scene_name=None, status="pending",
                 group_chat_id=PRIMARY_GROUP_CHAT_ID):
    record = RandomEventScheduleRecord(
        group_chat_id=group_chat_id,
        event_date=when.date(),
        scheduled_at=when,
        status=status,
        scene_name=scene_name,
    )
    session.add(record)
    session.flush()
    return record


def add_performed(session, scene_name, *, when=TARGET_AT - timedelta(hours=4)):
    record = RandomEventRecord(
        group_chat_id=PRIMARY_GROUP_CHAT_ID,
        schedule_id=add_schedule(session, when=when, scene_name=scene_name,
                                 status="ended").id,
        group_key="default",
        state="ended",
        scene_name=scene_name,
        event_name=f"{scene_name} 事件1",
        signup_text="报名",
        formal_opening_text="开场",
        reward=6,
        target_rounds=3,
        signup_deadline=when,
        started_at=when,
        ended_at=when,
    )
    session.add(record)
    session.flush()
    return record


def add_submission(session, scene_id, *, number, submitted_at):
    user_id = session.scalar(
        select(UserRecord.id).where(UserRecord.platform_id == "p1")
    )
    record = RandomEventSubmissionRecord(
        number=number,
        user_id=user_id,
        status="approved",
        current_step="preview",
        content={},
        last_activity_at=submitted_at,
        created_at=submitted_at,
        updated_at=submitted_at,
        submitted_at=submitted_at,
        scene_id=scene_id,
    )
    session.add(record)
    session.flush()
    return record


def poll_row(session) -> RandomEventPollRecord:
    return session.scalar(select(RandomEventPollRecord))


def outbound_texts(repository) -> list[str]:
    from dzmm_bot.core.schema import OutboundRecord

    with repository._session() as session:
        return list(
            session.scalars(
                select(OutboundRecord.text).order_by(OutboundRecord.created_at)
            )
        )


def schedule_row(session) -> RandomEventScheduleRecord:
    return session.scalar(
        select(RandomEventScheduleRecord).where(
            RandomEventScheduleRecord.status == "pending"
        )
    )


# --------------------------------------------------------------------- 建投票

def test_create_poll_picks_three_distinct_scenes_plus_a_vacant_slot(
    repository, seeded
):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙", "丁", "戊"):
            add_scene(session, name)
        add_schedule(session)

    view = repository.create_random_event_poll(NOW)

    assert view is not None
    assert [candidate.position for candidate in view.candidates] == [1, 2, 3, 4]
    assert all(not c.vacant for c in view.candidates[:3])
    assert {c.source for c in view.candidates[:3]} == {"random"}
    assert len({c.scene_name for c in view.candidates[:3]}) == 3
    assert view.candidates[3].vacant is True
    assert view.candidates[3].source == "ad_slot"
    assert view.candidates[3].scene_name is None
    assert view.closes_at == TARGET_AT - timedelta(minutes=10)


def test_create_poll_follows_the_existing_tier_preference(repository, seeded):
    """优先没演过且今天没排过的：演过的和排过的都不该进候选。"""
    with seeded.begin() as session:
        for name in ("演过的", "排过的", "新的甲", "新的乙", "新的丙"):
            add_scene(session, name)
        add_performed(session, "演过的")
        add_schedule(session, when=TARGET_AT - timedelta(hours=2), scene_name="排过的",
                     status="ended")
        add_schedule(session)

    view = repository.create_random_event_poll(NOW)

    assert {c.scene_name for c in view.candidates[:3]} == {"新的甲", "新的乙", "新的丙"}


def test_create_poll_carries_over_when_the_top_tier_is_short(repository, seeded):
    """第一档只剩 1 个时，从第二档（演过但没排过）补齐到 3 个。"""
    with seeded.begin() as session:
        for name in ("演过的", "排过的", "只此一个新"):
            add_scene(session, name)
        add_performed(session, "演过的")
        add_schedule(session, when=TARGET_AT - timedelta(hours=2), scene_name="排过的",
                     status="ended")
        add_schedule(session)

    view = repository.create_random_event_poll(NOW)

    assert {c.scene_name for c in view.candidates[:3]} == {
        "只此一个新",
        "演过的",
        "排过的",
    }


def test_create_poll_is_idempotent(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        add_schedule(session)

    first = repository.create_random_event_poll(NOW)
    second = repository.create_random_event_poll(NOW)

    with seeded() as session:
        count = len(session.scalars(select(RandomEventPollRecord)).all())
        candidates = len(
            session.scalars(select(RandomEventPollCandidateRecord)).all()
        )

    assert first.id == second.id
    assert count == 1
    assert candidates == 4


def test_poll_keeps_the_target_schedule_pending_until_it_closes(repository, seeded):
    """定稿前场次必须还是 pending 且没有场景——否则旧的随机逻辑会抢先冻住它。"""
    with seeded.begin() as session:
        add_scene(session, "甲")
        add_schedule(session)

    repository.create_random_event_poll(NOW)

    with seeded() as session:
        schedule = schedule_row(session)

    assert schedule.status == "pending"
    assert schedule.scene_name is None
    assert schedule.event_name is None


def test_create_poll_returns_none_without_a_pending_schedule(repository, seeded):
    with seeded.begin() as session:
        add_scene(session, "甲")

    assert repository.create_random_event_poll(NOW) is None


def test_create_poll_skips_groups_without_random_events(repository, seeded):
    with seeded.begin() as session:
        add_scene(session, "甲")
        add_schedule(session, group_chat_id=OTHER_GROUP_CHAT_ID)

    assert repository.create_random_event_poll(NOW) is None


def test_scheduling_leaves_the_scene_unfrozen_while_voting_is_on(repository, seeded):
    """投票开着时，排期不能抢先冻结场景——否则投票就白投了。"""
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)

    repository.schedule_random_events(NOW)

    with seeded() as session:
        schedules = list(
            session.scalars(
                select(RandomEventScheduleRecord).where(
                    RandomEventScheduleRecord.status == "pending"
                )
            )
        )
    assert schedules
    assert all(record.scene_name is None for record in schedules)


def test_scheduling_still_freezes_when_voting_is_off(repository, seeded):
    """关掉投票就回到老行为：排期时随机冻结。"""
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
    repository.set_random_event_settings(
        ["20:00"], "{可选身份}", 15, 5, vote_enabled=False
    )

    repository.schedule_random_events(NOW)

    with seeded() as session:
        record = schedule_row(session)
    assert record.scene_name is not None


# --------------------------------------------------------------------- 投票

def _open_poll(repository, session):
    add_schedule(session)
    return repository.create_random_event_poll(NOW)


def test_vote_is_recorded_and_can_be_changed(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        poll = _open_poll(repository, session)

    result = repository.cast_random_event_vote("p1", 1, NOW)
    assert result.status == "recorded"
    assert result.view.my_position == 1
    assert result.view.total_votes == 1

    changed = repository.cast_random_event_vote("p1", 2, NOW)

    assert changed.status == "changed"
    assert changed.view.my_position == 2
    assert changed.view.total_votes == 1
    with seeded() as session:
        votes = session.scalars(select(RandomEventPollVoteRecord)).all()
    assert len(votes) == 1
    assert votes[0].candidate_id == poll.candidates[1].id


def test_vote_rejects_the_vacant_slot(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    assert repository.cast_random_event_vote("p1", 4, NOW).status == "vacant"


def test_vote_rejects_unknown_position_and_unknown_employee(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    assert repository.cast_random_event_vote("p1", 9, NOW).status == "no_candidate"
    assert repository.cast_random_event_vote("nobody", 1, NOW).status == "not_joined"


def test_vote_rejects_when_there_is_no_open_poll(repository, seeded):
    assert repository.cast_random_event_vote("p1", 1, NOW).status == "no_poll"


def test_poll_view_reports_the_tally(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    repository.cast_random_event_vote("p1", 1, NOW)
    repository.cast_random_event_vote("p2", 1, NOW)
    repository.cast_random_event_vote("p3", 2, NOW)

    view = repository.random_event_poll_view("p3")

    assert view.total_votes == 3
    assert [c.votes for c in view.candidates] == [2, 1, 0, 0]
    assert view.my_position == 2


# --------------------------------------------------------------------- 定稿

def test_close_poll_freezes_the_winner_onto_the_schedule(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name, seats=(("主持", 1), ("观众", 2)), reward=9,
                      target_rounds=4)
        poll = _open_poll(repository, session)
    winner_name = poll.candidates[1].scene_name

    repository.cast_random_event_vote("p1", 2, NOW)
    repository.cast_random_event_vote("p2", 2, NOW)
    repository.cast_random_event_vote("p3", 1, NOW)

    result = repository.close_random_event_poll(CLOSE_AT)

    assert result.status == "closed"
    assert result.position == 2
    assert result.fallback_reason is None
    with seeded() as session:
        schedule = schedule_row(session)
        assert schedule.scene_name == winner_name
        assert schedule.event_name == f"{winner_name} 事件1"
        assert schedule.reward == 9
        assert schedule.target_rounds == 4
        assert schedule.signup_text == f"{winner_name} 报名"
        assert schedule.seats == [
            {"role": "主持", "capacity": 1},
            {"role": "观众", "capacity": 2},
        ]
        assert schedule_row(session).status == "pending"


def test_close_poll_refuses_before_the_deadline(repository, seeded):
    with seeded.begin() as session:
        add_scene(session, "甲")
        _open_poll(repository, session)

    assert repository.close_random_event_poll(NOW).status == "not_due"


def test_close_poll_falls_back_to_random_when_nobody_votes(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    result = repository.close_random_event_poll(CLOSE_AT)

    assert result.status == "closed"
    assert result.fallback_reason == "no_votes"
    assert result.position in {1, 2, 3}


def test_close_poll_breaks_a_tie_by_fewest_performances(repository, seeded):
    with seeded.begin() as session:
        add_scene(session, "常演")
        add_scene(session, "冷门")
        add_scene(session, "凑数")
        for index in range(3):
            add_performed(
                session,
                "常演",
                when=TARGET_AT - timedelta(hours=6 + index),
            )
        poll = _open_poll(repository, session)
    popular = next(c for c in poll.candidates if c.scene_name == "常演")
    rare = next(c for c in poll.candidates if c.scene_name == "冷门")

    repository.cast_random_event_vote("p1", popular.position, NOW)
    repository.cast_random_event_vote("p2", rare.position, NOW)

    result = repository.close_random_event_poll(CLOSE_AT)

    assert result.fallback_reason == "tie"
    assert result.position == rare.position


def test_close_poll_breaks_a_tie_by_the_later_submission(repository, seeded):
    with seeded.begin() as session:
        early = add_scene(session, "早投的")
        late = add_scene(session, "晚投的")
        add_scene(session, "凑数")
        add_submission(
            session,
            early.id,
            number=1,
            submitted_at=datetime(2026, 9, 1, tzinfo=BEIJING),
        )
        add_submission(
            session,
            late.id,
            number=2,
            submitted_at=datetime(2026, 9, 10, tzinfo=BEIJING),
        )
        poll = _open_poll(repository, session)
    early_position = next(c for c in poll.candidates if c.scene_name == "早投的").position
    late_position = next(c for c in poll.candidates if c.scene_name == "晚投的").position

    repository.cast_random_event_vote("p1", early_position, NOW)
    repository.cast_random_event_vote("p2", late_position, NOW)

    result = repository.close_random_event_poll(CLOSE_AT)

    assert result.fallback_reason == "tie"
    assert result.position == late_position


def test_close_poll_supports_an_admin_override(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    result = repository.close_random_event_poll(NOW, winner_position=3)

    assert result.status == "closed"
    assert result.position == 3
    assert result.fallback_reason == "manual"


def test_close_poll_is_idempotent(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    first = repository.close_random_event_poll(CLOSE_AT)
    second = repository.close_random_event_poll(CLOSE_AT + timedelta(minutes=1))

    assert first.status == "closed"
    assert second.status in {"no_poll", "already_closed"}


def test_close_poll_without_a_poll_reports_no_poll(repository, seeded):
    assert repository.close_random_event_poll(NOW).status == "no_poll"


# --------------------------------------------------------------------- 后台

def test_poll_report_lists_candidates_voters_and_the_ad_slot(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    repository.cast_random_event_vote("p1", 1, NOW)
    repository.cast_random_event_vote("p2", 1, NOW)
    repository.cast_random_event_vote("p3", 2, NOW)

    report = repository.random_event_poll_report()

    assert report.status == "open"
    assert report.total_votes == 3
    assert report.winner_position is None
    assert report.group_name == "主群聊"
    assert [candidate.position for candidate in report.candidates] == [1, 2, 3, 4]
    assert [candidate.votes for candidate in report.candidates] == [2, 1, 0, 0]
    assert report.candidates[0].voters == ("小明", "小红")
    assert report.candidates[2].source == "random"
    assert report.candidates[3].vacant is True
    assert report.candidates[3].source == "ad_slot"
    assert report.candidates[0].scene_name is not None


def test_poll_report_reports_the_winner_after_closing(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)
    repository.cast_random_event_vote("p1", 2, NOW)

    repository.close_random_event_poll(CLOSE_AT)

    report = repository.random_event_poll_report()
    assert report.status == "closed"
    assert report.winner_position == 2
    assert report.closed_at == CLOSE_AT


def test_admin_can_close_early(repository, seeded):
    """票数不够或快到点了，管理员可以立刻截止。"""
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    result = repository.close_random_event_poll(NOW, force=True)

    assert result.status == "closed"
    assert result.fallback_reason == "no_votes"


def test_admin_can_designate_a_winner_after_closing(repository, seeded):
    """改判：已经定稿但场次还没开始时，管理员可以重新指定当选者。"""
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        poll = _open_poll(repository, session)
    other_name = poll.candidates[2].scene_name
    repository.close_random_event_poll(CLOSE_AT)

    result = repository.close_random_event_poll(CLOSE_AT, winner_position=3)

    assert result.status == "closed"
    assert result.position == 3
    assert result.fallback_reason == "manual"
    with seeded() as session:
        assert schedule_row(session).scene_name == other_name


def test_admin_cannot_designate_once_the_event_started(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)
    with seeded.begin() as session:
        schedule_row(session).status = "in_progress"

    result = repository.close_random_event_poll(CLOSE_AT, winner_position=2)

    assert result.status == "no_poll"


def test_admin_can_cancel_the_poll(repository, seeded):
    with seeded.begin() as session:
        for name in ("甲", "乙", "丙"):
            add_scene(session, name)
        _open_poll(repository, session)

    assert repository.cancel_random_event_poll(NOW) == "cancelled"

    report = repository.random_event_poll_report()
    assert report.status == "cancelled"
    assert any("取消" in text for text in outbound_texts(repository))


def test_admin_cancel_without_a_poll(repository, seeded):
    assert repository.cancel_random_event_poll(NOW) == "no_poll"
