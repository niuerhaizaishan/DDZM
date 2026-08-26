from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from dzmm_bot.core import schema
from dzmm_bot.core.performance import parse_postponement
from dzmm_bot.core.repository import CoreRepository


BEIJING = ZoneInfo("Asia/Shanghai")


def _group(now: datetime):
    return schema.GroupChatRecord(
        id=uuid4(),
        name=f"公演群-{uuid4()}",
        chat_url=f"https://www.aikda.com/chat?c={uuid4()}",
        chatroom_id=str(uuid4()),
        listening_enabled=True,
        games_enabled=True,
        enabled_game_types=[],
        random_events_enabled=True,
        announcements_enabled=True,
        adult_shop_enabled=False,
        created_at=now,
        updated_at=now,
    )


def _user(name: str, employee_number: int, now: datetime):
    return schema.UserRecord(
        id=uuid4(),
        platform_id=f"platform-{name}",
        display_name=name,
        employee_number=employee_number,
        balance=100,
        joined_at=now,
    )


def test_performance_schema_enforces_one_live_date() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema.Base.metadata.create_all(engine)
    now = datetime(2026, 8, 26, 12, 0, tzinfo=BEIJING)
    with Session(engine) as session:
        group = _group(now)
        owner_a = _user("演员甲", 1, now)
        owner_b = _user("演员乙", 2, now)
        session.add_all((group, owner_a, owner_b))
        session.flush()
        session.add(
            schema.PerformanceReservationRecord(
                owner_user_id=owner_a.id,
                group_chat_id=group.id,
                title="夜航",
                introduction="第一场",
                scheduled_at=now,
                event_date=date(2026, 8, 27),
                state="pending_review",
                submitted_at=now,
            )
        )
        session.flush()
        session.add(
            schema.PerformanceReservationRecord(
                owner_user_id=owner_b.id,
                group_chat_id=group.id,
                title="晨光",
                introduction="第二场",
                scheduled_at=now,
                event_date=date(2026, 8, 27),
                state="approved",
                submitted_at=now,
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_performance_schema_allows_reusing_a_terminal_date() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema.Base.metadata.create_all(engine)
    now = datetime(2026, 8, 26, 12, 0, tzinfo=BEIJING)
    with Session(engine) as session:
        group = _group(now)
        owner_a = _user("演员甲", 1, now)
        owner_b = _user("演员乙", 2, now)
        session.add_all((group, owner_a, owner_b))
        session.flush()
        for owner, state in ((owner_a, "completed"), (owner_b, "pending_review")):
            session.add(
                schema.PerformanceReservationRecord(
                    owner_user_id=owner.id,
                    group_chat_id=group.id,
                    title=f"{owner.display_name}公演",
                    introduction="介绍",
                    scheduled_at=now,
                    event_date=date(2026, 8, 27),
                    state=state,
                    submitted_at=now,
                )
            )
        session.flush()


def test_performance_schema_exposes_required_records() -> None:
    expected = {
        "PerformanceSettingsRecord",
        "PerformanceReservationRecord",
        "PerformanceParticipantRecord",
        "PerformanceDraftRecord",
        "PerformanceExtensionRequestRecord",
        "PerformanceMessageRecord",
        "PerformanceTipRecord",
    }
    assert expected <= set(vars(schema))
    assert "performances_enabled" in schema.GroupChatRecord.__table__.columns
    assert "deferred_by_performance_id" in schema.OutboundRecord.__table__.columns
    assert "performance_defer_key" in schema.OutboundRecord.__table__.columns


@pytest.fixture
def repository() -> CoreRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema.Base.metadata.create_all(engine)
    return CoreRepository(sessionmaker(engine, expire_on_commit=False))


@pytest.fixture
def reservation_context(repository: CoreRepository):
    now = datetime(2026, 8, 26, 12, 0, tzinfo=BEIJING)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=performance-room", now
    )
    with repository._session_factory.begin() as session:
        session.get(schema.GroupChatRecord, group.id).performances_enabled = True
    repository.create_user("owner", "发起人", now, 100)
    repository.create_user("actor-a", "演员甲", now, 100)
    repository.create_user("actor-b", "演员乙", now, 100)
    repository.upsert_direct_chats([("owner", "direct-owner")], now)
    return repository, group, now


def _complete_draft(repository, group, now, *, title="夜航", day_offset=1):
    assert repository.begin_performance_draft("owner", group.id, now).status == "started"
    assert repository.consume_performance_draft_input(
        "owner", uuid4(), now, text=title
    ).current_step == "introduction"
    assert repository.consume_performance_draft_input(
        "owner", uuid4(), now, text="一场夜间公演"
    ).current_step == "scheduled_at"
    scheduled = now + timedelta(days=day_offset)
    assert repository.consume_performance_draft_input(
        "owner", uuid4(), now, text=scheduled.strftime("%Y/%m/%d-%H:%M:%S")
    ).current_step == "participants"
    assert repository.consume_performance_draft_input(
        "owner", uuid4(), now, text="演员甲、演员乙"
    ).current_step == "cover"
    assert repository.consume_performance_draft_input(
        "owner", uuid4(), now, text="/跳过"
    ).current_step == "confirm"
    return repository.consume_performance_draft_input(
        "owner", uuid4(), now, text="/确认"
    )


def test_confirmed_draft_locks_the_date_and_owner(reservation_context) -> None:
    repository, group, now = reservation_context

    result = _complete_draft(repository, group, now)

    assert result.status == "submitted"
    assert result.reservation is not None
    assert result.reservation.state == "pending_review"
    assert result.reservation.event_date == (now + timedelta(days=1)).date()
    assert result.reservation.participant_names == ("演员甲", "演员乙")
    assert repository.begin_performance_draft("owner", group.id, now).status == "owner_busy"


def test_confirm_revalidates_reservation_time(reservation_context) -> None:
    repository, group, now = reservation_context
    repository.begin_performance_draft("owner", group.id, now)
    for value in (
        "夜航",
        "一场夜间公演",
        (now + timedelta(minutes=31)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
        "/跳过",
    ):
        repository.consume_performance_draft_input("owner", uuid4(), now, text=value)

    result = repository.consume_performance_draft_input(
        "owner", uuid4(), now + timedelta(minutes=2), text="/确认"
    )

    assert result.status == "schedule_invalid"
    assert result.current_step == "scheduled_at"
    assert repository.performance_draft_step(
        "owner", now + timedelta(minutes=2)
    ) == "scheduled_at"


def test_second_draft_cannot_occupy_same_date(reservation_context) -> None:
    repository, group, now = reservation_context
    _complete_draft(repository, group, now)
    repository.create_user("owner-b", "另一发起人", now, 100)
    repository.upsert_direct_chats([("owner-b", "direct-owner-b")], now)
    assert repository.begin_performance_draft("owner-b", group.id, now).status == "started"
    for value in (
        "晨光",
        "另一场公演",
        (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
        "/跳过",
    ):
        repository.consume_performance_draft_input("owner-b", uuid4(), now, text=value)

    result = repository.consume_performance_draft_input(
        "owner-b", uuid4(), now, text="/确认"
    )

    assert result.status == "date_taken"


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(minutes=29, seconds=59), "invalid"),
        (timedelta(minutes=30), "advanced"),
        (timedelta(days=30), "advanced"),
        (timedelta(days=30, seconds=1), "invalid"),
    ],
)
def test_performance_time_boundary(reservation_context, delta, expected) -> None:
    repository, group, now = reservation_context
    repository.begin_performance_draft("owner", group.id, now)
    repository.consume_performance_draft_input("owner", uuid4(), now, text="标题")
    repository.consume_performance_draft_input("owner", uuid4(), now, text="简介")

    result = repository.consume_performance_draft_input(
        "owner",
        uuid4(),
        now,
        text=(now + delta).strftime("%Y/%m/%d-%H:%M:%S"),
    )

    assert result.status == expected


def test_performance_draft_expires_without_reserving_date(reservation_context) -> None:
    repository, group, now = reservation_context
    repository.begin_performance_draft("owner", group.id, now)

    result = repository.consume_performance_draft_input(
        "owner", uuid4(), now + timedelta(minutes=30), text="太迟了"
    )

    assert result.status == "expired"
    assert repository.begin_performance_draft(
        "owner", group.id, now + timedelta(minutes=30)
    ).status == "started"


def test_cancel_and_query_performance(reservation_context) -> None:
    repository, group, now = reservation_context
    submitted = _complete_draft(repository, group, now)
    assert repository.own_performance("owner", now).id == submitted.reservation.id
    assert repository.upcoming_performances(group.id, now) == ()

    cancelled = repository.cancel_own_performance("owner", now)

    assert cancelled.status == "cancelled"
    assert repository.own_performance("owner", now) is None


def test_latest_own_performance_keeps_terminal_reason(reservation_context) -> None:
    repository, group, now = reservation_context
    submitted = _complete_draft(repository, group, now)
    repository.review_performance(
        submitted.reservation.id, False, "admin:a", now, "标题不符合规范"
    )

    view = repository.latest_own_performance("owner")

    assert view.state == "rejected"
    assert view.rejection_reason == "标题不符合规范"


@pytest.mark.parametrize(
    ("raw", "minutes"), (("30m", 30), ("1h", 60), ("1d", 1440))
)
def test_parse_postponement(raw, minutes) -> None:
    assert parse_postponement(raw) == timedelta(minutes=minutes)


@pytest.mark.parametrize("raw", ("", "0m", "1H", "1.5h", "30", "-1d"))
def test_postponement_rejects_invalid_duration(raw) -> None:
    with pytest.raises(ValueError, match="延期格式"):
        parse_postponement(raw)


def test_approved_postponement_moves_calendar_atomically(reservation_context) -> None:
    repository, group, now = reservation_context
    submitted = _complete_draft(repository, group, now)
    repository.review_performance(submitted.reservation.id, True, "admin:a", now)

    requested = repository.request_performance_postponement(
        "owner", timedelta(days=1), now
    )
    reviewed = repository.review_performance_postponement(
        requested.request.id, True, "admin:a", now
    )

    assert reviewed.status == "approved"
    assert reviewed.reservation.event_date == (now + timedelta(days=2)).date()
    assert reviewed.reservation.pre_notice_sent_at is None


def test_only_one_postponement_can_be_pending(reservation_context) -> None:
    repository, group, now = reservation_context
    submitted = _complete_draft(repository, group, now)
    repository.review_performance(submitted.reservation.id, True, "admin:a", now)

    first = repository.request_performance_postponement(
        "owner", timedelta(hours=1), now
    )
    second = repository.request_performance_postponement(
        "owner", timedelta(hours=2), now
    )

    assert first.status == "requested"
    assert second.status == "already_pending"


def test_game_creation_rechecks_performance_gate_inside_transaction(
    reservation_context,
) -> None:
    repository, group, now = reservation_context
    submitted = _complete_draft(repository, group, now)
    repository.review_performance(submitted.reservation.id, True, "admin:a", now)
    repository.upsert_direct_chats([("actor-a", "direct-actor-a")], now)
    repository.run_performance_jobs(now + timedelta(days=1, minutes=-5))

    result = repository.start_number_bomb_game("actor-a", now, group.id)

    assert result.status == "multiplayer_active"
