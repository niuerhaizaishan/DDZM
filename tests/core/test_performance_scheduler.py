from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core import schema
from dzmm_bot.core.repository import CoreRepository


BEIJING = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def scheduled_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    schema.Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    now = datetime(2026, 8, 26, 12, 0, tzinfo=BEIJING)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=performance-scheduler", now
    )
    repository.create_user("owner", "发起人", now, 100)
    repository.create_user("actor", "演员甲", now, 100)
    repository.upsert_direct_chats([("owner", "direct-owner")], now)
    with factory.begin() as session:
        session.get(schema.GroupChatRecord, group.id).performances_enabled = True
        owner = session.scalar(
            select(schema.UserRecord).where(schema.UserRecord.platform_id == "owner")
        )
        actor = session.scalar(
            select(schema.UserRecord).where(schema.UserRecord.platform_id == "actor")
        )
        reservation = schema.PerformanceReservationRecord(
            owner_user_id=owner.id,
            group_chat_id=group.id,
            title="夜航",
            introduction="一场夜间公演",
            scheduled_at=now + timedelta(hours=1),
            event_date=(now + timedelta(hours=1)).date(),
            cover_url="https://cdn.example/cover.webp",
            cover_alt="夜航封面",
            state="approved",
            submitted_at=now,
            reviewed_at=now,
            reviewed_by="admin:test",
        )
        session.add(reservation)
        session.flush()
        session.add(
            schema.PerformanceParticipantRecord(
                reservation_id=reservation.id, user_id=actor.id, display_order=1
            )
        )
    return repository, factory, group, reservation.id, now


def _outbounds(factory):
    with factory() as session:
        return list(
            session.scalars(
                select(schema.OutboundRecord).order_by(
                    schema.OutboundRecord.created_at,
                    schema.OutboundRecord.reply_index,
                )
            )
        )


def test_preview_is_sent_once_at_five_minutes(scheduled_context) -> None:
    repository, factory, _, reservation_id, now = scheduled_context

    repository.run_performance_jobs(now + timedelta(minutes=55))
    repository.run_performance_jobs(now + timedelta(minutes=56))

    texts = [item.text for item in _outbounds(factory)]
    assert sum("公演即将开始" in text for text in texts) == 1
    assert repository.performance_details(reservation_id).state == "previewed"


def test_opening_queues_text_before_cover(scheduled_context) -> None:
    repository, factory, _, reservation_id, now = scheduled_context

    repository.run_performance_jobs(now + timedelta(hours=1))

    outbounds = _outbounds(factory)
    opening = [item for item in outbounds if "演出开始" in item.text]
    images = [item for item in outbounds if item.content_type == "image"]
    assert len(opening) == 1
    assert len(images) == 1
    assert opening[0].reply_index < images[0].reply_index
    assert images[0].image_url == "https://cdn.example/cover.webp"
    assert repository.performance_details(reservation_id).state == "performing"


def test_pending_review_expires_at_preview_boundary(scheduled_context) -> None:
    repository, factory, _, reservation_id, now = scheduled_context
    with factory.begin() as session:
        session.get(schema.PerformanceReservationRecord, reservation_id).state = (
            "pending_review"
        )

    repository.run_performance_jobs(now + timedelta(minutes=55))

    assert repository.performance_details(reservation_id).state == "expired"
    assert any("审核未完成" in item.text for item in _outbounds(factory))


def test_tipping_settles_after_180_seconds_and_records_memory(scheduled_context) -> None:
    repository, factory, group, reservation_id, now = scheduled_context
    stage_time = now + timedelta(hours=1)
    repository.run_performance_jobs(stage_time)
    repository.end_performance("actor", group.id, stage_time)

    repository.run_performance_jobs(stage_time + timedelta(seconds=180))

    assert repository.performance_details(reservation_id).state == "completed"
    assert any(
        item.text.endswith("-------------------------演出结束-----------------------")
        for item in _outbounds(factory)
    )
    facts = repository.list_ai_activity_facts("actor")
    assert len(facts) == 1
    assert facts[0].activity_type == "performance"
