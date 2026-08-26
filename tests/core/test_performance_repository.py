from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from dzmm_bot.core import schema


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
