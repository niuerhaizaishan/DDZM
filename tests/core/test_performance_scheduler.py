from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core import schema
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.runtime.contracts import InboundMessage


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
    assert any("简介：一场夜间公演" in text for text in texts)
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


def test_board_force_end_then_force_settle_preserves_performance_flow(
    scheduled_context,
) -> None:
    repository, _, group, reservation_id, now = scheduled_context
    stage_time = now + timedelta(hours=1)
    repository.run_performance_jobs(stage_time)

    tipping = repository.cancel_performance_by_admin(
        reservation_id, "board", "后台强制结束演出", stage_time, force=True
    )
    settled = repository.cancel_performance_by_admin(
        reservation_id,
        "board",
        "后台强制结束打赏",
        stage_time + timedelta(seconds=1),
        force=True,
    )

    assert tipping.state == "tipping"
    assert settled.state == "completed"
    assert repository.active_performance_state(group.id) is None


def test_restart_opens_only_one_overdue_performance_per_group(
    scheduled_context,
) -> None:
    repository, factory, group, reservation_id, now = scheduled_context
    repository.create_user("owner-2", "发起人二", now, 100)
    repository.create_user("actor-2", "演员乙", now, 100)
    with factory.begin() as session:
        owner = session.scalar(
            select(schema.UserRecord).where(
                schema.UserRecord.platform_id == "owner-2"
            )
        )
        actor = session.scalar(
            select(schema.UserRecord).where(
                schema.UserRecord.platform_id == "actor-2"
            )
        )
        second = schema.PerformanceReservationRecord(
            owner_user_id=owner.id,
            group_chat_id=group.id,
            title="次日场",
            introduction="第二场",
            scheduled_at=now + timedelta(days=1),
            event_date=(now + timedelta(days=1)).date(),
            state="approved",
            submitted_at=now,
        )
        session.add(second)
        session.flush()
        second_id = second.id
        session.add(
            schema.PerformanceParticipantRecord(
                reservation_id=second.id, user_id=actor.id, display_order=1
            )
        )

    repository.run_performance_jobs(now + timedelta(days=2))

    assert repository.performance_details(reservation_id).state == "performing"
    assert repository.performance_details(second_id).state == "waiting"


def test_performance_history_exposes_audit_and_tip_ledger(
    scheduled_context,
) -> None:
    repository, factory, group, reservation_id, now = scheduled_context
    stage_time = now + timedelta(hours=1)
    repository.run_performance_jobs(stage_time)
    with factory.begin() as session:
        fan = schema.UserRecord(
            id=uuid4(),
            platform_id="fan",
            display_name="观众",
            employee_number=99,
            balance=100,
            joined_at=now,
        )
        session.add(fan)
        session.flush()
        inbound = schema.InboundRecord(
            platform_message_id="tip-history",
            sender_platform_id="fan",
            content="/打赏 演员甲 5",
            source_type="group",
            chatroom_id=group.chatroom_id,
            group_chat_id=group.id,
            received_at=stage_time,
        )
        session.add(inbound)
        session.add(
            schema.AuditEventRecord(
                event_type="performance_approved",
                actor="admin:test",
                payload={"performance_id": str(reservation_id)},
                created_at=now,
            )
        )
    repository.end_performance("actor", group.id, stage_time)
    repository.tip_performance(
        "fan", "演员甲", 5, "tip-history", stage_time, group.id
    )
    repository.run_performance_jobs(stage_time + timedelta(seconds=180))

    view = repository.performance_details(reservation_id)

    assert view.reviewed_by == "admin:test"
    assert len(view.tips) == 1
    assert view.tips[0].sender_display_name == "观众"
    assert view.tips[0].recipient_display_name == "演员甲"
    assert view.tips[0].amount == 5
    assert any(item.event_type == "performance_approved" for item in view.audit_events)


def test_same_group_system_notice_waits_until_performance_settlement(
    scheduled_context,
) -> None:
    repository, factory, group, reservation_id, now = scheduled_context
    stage_time = now + timedelta(hours=1)
    repository.run_performance_jobs(stage_time)

    held = repository.enqueue_system_outbound(
        "暗网成交公告",
        group_chat_id=group.id,
        destination_chatroom_id=group.chatroom_id,
        performance_defer_key="dark-market:listing-1",
    )

    with factory() as session:
        assert session.get(schema.OutboundRecord, held.id).status == "held_performance"
    repository.end_performance("actor", group.id, stage_time)
    repository.run_performance_jobs(stage_time + timedelta(seconds=180))
    with factory() as session:
        notice = session.get(schema.OutboundRecord, held.id)
        settlement = session.scalar(
            select(schema.OutboundRecord)
            .where(schema.OutboundRecord.text.like("公演打赏结束%"))
            .order_by(schema.OutboundRecord.created_at.desc())
        )
        assert notice.status == "pending"
        assert (settlement.created_at, settlement.reply_index) < (
            notice.created_at,
            notice.reply_index,
        )


def test_latest_keyed_performance_notice_replaces_held_text(scheduled_context) -> None:
    repository, factory, group, _, now = scheduled_context
    repository.run_performance_jobs(now + timedelta(hours=1))

    first = repository.enqueue_system_outbound(
        "报价 5",
        group_chat_id=group.id,
        destination_chatroom_id=group.chatroom_id,
        performance_defer_key="dark-market:listing-2",
    )
    second = repository.enqueue_system_outbound(
        "报价 8",
        group_chat_id=group.id,
        destination_chatroom_id=group.chatroom_id,
        performance_defer_key="dark-market:listing-2",
    )

    assert first.id == second.id
    with factory() as session:
        assert session.get(schema.OutboundRecord, first.id).text == "报价 8"


def test_ai_job_completed_during_performance_waits_for_settlement(
    scheduled_context,
) -> None:
    repository, factory, group, _, now = scheduled_context
    stage_time = now + timedelta(hours=1)
    repository.get_ai_assistant_settings()
    with factory.begin() as session:
        session.get(schema.AIAssistantSettingsRecord, 1).enabled = True
    inbound, _ = repository.accept_inbound(
        InboundMessage(
            "performance-ai-inbound",
            "owner",
            "@总监事 介绍一下今晚公演",
            stage_time - timedelta(seconds=1),
            source_type="group",
            chatroom_id=group.chatroom_id,
        ),
        group.id,
    )
    assert repository.try_enqueue_ai_request(
        inbound.id,
        "owner",
        "介绍一下今晚公演",
        stage_time - timedelta(seconds=1),
    ).state == "queued"
    claim = repository.claim_ai_request(
        "ai-worker", stage_time - timedelta(seconds=1), 90
    )
    repository.run_performance_jobs(stage_time)

    assert repository.complete_ai_request(
        claim.id, "ai-worker", claim.lease_token, "AI 延迟回复", stage_time
    )
    with factory() as session:
        reply = session.scalar(
            select(schema.OutboundRecord).where(
                schema.OutboundRecord.text == "AI 延迟回复"
            )
        )
        assert reply.status == "held_performance"

    repository.end_performance("actor", group.id, stage_time)
    repository.run_performance_jobs(stage_time + timedelta(seconds=180))
    with factory() as session:
        assert session.get(schema.OutboundRecord, reply.id).status == "pending"
