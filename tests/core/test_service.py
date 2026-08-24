from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage


class _FixedNumberBombRandom:
    def choice(self, values):
        assert 12 in values
        return 12


@pytest.fixture
def session_factory():
    from dzmm_bot.core.schema import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def inbound():
    return InboundMessage(
        "platform-1",
        "sender-1",
        "hello",
        datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
    )


def test_noop_service_accepts_message_without_creating_reply(session_factory, inbound):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.core.service import CoreService

    service = CoreService(CoreRepository(session_factory))

    result = service.receive_inbound(inbound)

    assert result.inserted is True
    with session_factory() as session:
        assert session.scalar(select(OutboundRecord)) is None


def test_duplicate_message_does_not_invoke_handler_twice(session_factory, inbound):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.service import CoreService

    class CountingHandler:
        def __init__(self):
            self.calls = 0

        def handle(self, message):
            self.calls += 1
            return "reply"

    handler = CountingHandler()
    service = CoreService(CoreRepository(session_factory), handler)

    first = service.receive_inbound(inbound)
    second = service.receive_inbound(inbound)

    assert first.inserted is True
    assert second.inserted is False
    assert second.message_id == first.message_id
    assert handler.calls == 1


def test_group_reply_inherits_source_group_and_disabled_group_is_rejected(
    session_factory,
):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.core.service import CoreService

    class ReplyHandler:
        def handle(self, message):
            return "reply"

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    primary = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-a", now
    )
    repository.create_group_chat(
        "停用群",
        "https://www.aikda.com/chat?c=group-b",
        False,
        True,
        True,
        True,
        now,
    )
    service = CoreService(repository, ReplyHandler())

    accepted = service.receive_inbound(
        InboundMessage("m-a", "p1", "hello", now, chatroom_id="group-a")
    )
    rejected = service.receive_inbound(
        InboundMessage("m-b", "p1", "hello", now, chatroom_id="group-b")
    )

    with session_factory() as session:
        outbound = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == accepted.message_id
            )
        )
    assert outbound.group_chat_id == primary.id
    assert outbound.destination_chatroom_id == "group-a"
    assert outbound.delivery_key == "group-a"
    assert rejected.inserted is False


def test_same_platform_message_id_is_unique_per_enabled_group(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-a", now
    )
    repository.create_group_chat(
        "第二群",
        "https://www.aikda.com/chat?c=group-b",
        True,
        True,
        True,
        True,
        now,
    )
    service = CoreService(repository)

    first = service.receive_inbound(
        InboundMessage("same-id", "p1", "hello", now, chatroom_id="group-a")
    )
    second = service.receive_inbound(
        InboundMessage("same-id", "p1", "hello", now, chatroom_id="group-b")
    )
    duplicate = service.receive_inbound(
        InboundMessage("same-id", "p1", "hello", now, chatroom_id="group-a")
    )

    assert first.inserted is True
    assert second.inserted is True
    assert duplicate.inserted is False
    assert duplicate.message_id == first.message_id


def test_service_queues_multiple_replies_for_one_inbound_in_order(session_factory, inbound):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.core.service import CoreService

    class MultiReplyHandler:
        def handle(self, message):
            return ["第一条", "第二条"]

    service = CoreService(CoreRepository(session_factory), MultiReplyHandler())
    result = service.receive_inbound(inbound)
    duplicate = service.receive_inbound(inbound)

    with session_factory() as session:
        replies = list(
            session.scalars(
                select(OutboundRecord)
                .where(OutboundRecord.inbound_message_id == result.message_id)
                .order_by(OutboundRecord.reply_index)
            )
        )
    assert [reply.text for reply in replies] == ["第一条", "第二条"]
    assert [reply.reply_index for reply in replies] == [0, 1]
    assert duplicate.inserted is False


def test_service_records_an_accepted_joined_message_once(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    received_at = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    repository.create_user("sender-1", "小明", received_at, 0)
    service = CoreService(repository)
    message = InboundMessage(
        "platform-activity-1", "sender-1", "一二三四五六七八九十", received_at
    )

    service.receive_inbound(message)
    service.receive_inbound(message)

    assert repository.personal_activity("sender-1", received_at).level == 1


def test_direct_number_bomb_reports_are_isolated_and_destination_aware(session_factory):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import InboundRecord, OutboundRecord
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(
        session_factory,
        preserve_long_group_messages=True,
        number_bomb_random=_FixedNumberBombRandom(),
    )
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    for index in range(1, 4):
        repository.create_user(f"direct-p{index}", f"私聊{index}", now, 0)
    repository.upsert_direct_chats(
        [(f"direct-p{index}", f"direct-room-{index}") for index in range(1, 4)],
        now,
    )
    repository.start_number_bomb_game("direct-p1", now)
    repository.join_number_bomb_game("direct-p2", now)
    repository.join_number_bomb_game("direct-p3", now)
    repository.start_number_bomb_round("direct-p1", now)
    service = CoreService(repository, GroupCommandHandler(repository))

    for index, number in ((1, 10), (2, 50), (3, 90)):
        service.receive_inbound(InboundMessage(
            f"direct-inbound-{index}", f"direct-p{index}", f"/报数 {number}", now,
            source_type="direct", chatroom_id=f"direct-room-{index}",
        ))

    with session_factory() as session:
        inbound = session.scalar(select(InboundRecord).where(
            InboundRecord.platform_message_id == "direct-inbound-1"
        ))
        last = session.scalar(select(InboundRecord).where(
            InboundRecord.platform_message_id == "direct-inbound-3"
        ))
        replies = list(session.scalars(
            select(OutboundRecord)
            .where(OutboundRecord.inbound_message_id == last.id)
            .order_by(OutboundRecord.reply_index)
        ))
    assert (inbound.source_type, inbound.chatroom_id, inbound.ai_memory_eligible) == (
        "direct", "direct-room-1", False,
    )
    assert len(replies) == 2
    assert (replies[0].destination_chatroom_id, replies[0].delivery_kind) == (
        "direct-room-3", "number_bomb_private",
    )
    assert "报数成功" in replies[0].text
    assert {
        (reply.destination_chatroom_id, reply.delivery_kind)
        for reply in replies[1:]
    } == {(None, "group")}
    result_text = replies[1].text
    assert "第 1 轮 - 真心话" in result_text
    assert "本轮随机倍率：×1.2" in result_text
    assert "最终数 F：平均值 × 1.2 = 60.00" in result_text
    assert replies[0].reference_message_id == "direct-inbound-3"
    assert {reply.reference_message_id for reply in replies[1:]} == {None}

    continued = service.receive_inbound(InboundMessage(
        "direct-continue",
        "direct-p1",
        "/继续",
        now + timedelta(seconds=1),
        source_type="direct",
        chatroom_id="direct-room-1",
    ))
    with session_factory() as session:
        continued_replies = list(session.scalars(
            select(OutboundRecord)
            .where(OutboundRecord.inbound_message_id == continued.message_id)
            .order_by(OutboundRecord.reply_index)
        ))
    assert (continued_replies[0].destination_chatroom_id, continued_replies[0].delivery_kind) == (
        None, "group",
    )
    assert continued_replies[0].reference_message_id is None
    assert all(
        reply.destination_chatroom_id is not None
        for reply in continued_replies[1:]
    )


def test_direct_profile_text_and_image_stay_in_the_direct_chat(session_factory):
    """Fails if structured direct replies silently fall back to the group room."""
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
    repository.create_user("profile-direct", "档案玩家", now, 0)
    repository.set_personal_profile_by_admin("profile-direct", "喜欢桌游")
    repository.set_profile_image_by_admin(
        "profile-direct", "https://cdn.example.com/profile.webp"
    )
    service = CoreService(repository, GroupCommandHandler(repository))

    result = service.receive_inbound(InboundMessage(
        "profile-direct-message",
        "profile-direct",
        "/我的档案",
        now,
        source_type="direct",
        chatroom_id="profile-direct-room",
    ))

    with session_factory() as session:
        replies = list(session.scalars(
            select(OutboundRecord)
            .where(OutboundRecord.inbound_message_id == result.message_id)
            .order_by(OutboundRecord.reply_index)
        ))
    assert [reply.content_type for reply in replies] == ["text", "image"]
    assert {
        (reply.destination_chatroom_id, reply.delivery_kind)
        for reply in replies
    } == {("profile-direct-room", "direct")}


@pytest.mark.parametrize("content", ["/发红包 2 2", "/抢红包"])
def test_red_packet_commands_in_direct_chat_only_redirect_to_group(
    session_factory, content
):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("direct-packet", "私聊玩家", now, 10)
    service = CoreService(repository, GroupCommandHandler(repository))

    result = service.receive_inbound(
        InboundMessage(
            f"direct-{content}",
            "direct-packet",
            content,
            now,
            source_type="direct",
            chatroom_id="direct-packet-room",
        )
    )

    with session_factory() as session:
        reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == result.message_id
            )
        )
    assert "请回到群里" in reply.text
    assert (reply.destination_chatroom_id, reply.delivery_kind) == (
        "direct-packet-room",
        "direct",
    )
    assert repository.find_user("direct-packet").balance == 10


def test_commands_and_parenthesized_messages_are_not_memory_eligible(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import InboundRecord
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    repository.create_user("player", "玩家", now, 0)
    service = CoreService(repository)

    service.receive_inbound(InboundMessage("command", "player", "/打卡", now))
    service.receive_inbound(
        InboundMessage("observer", "player", "（围观）", now + timedelta(seconds=1))
    )
    service.receive_inbound(
        InboundMessage("ordinary", "player", "今天群里很热闹", now + timedelta(seconds=2))
    )

    with session_factory() as session:
        rows = list(
            session.scalars(select(InboundRecord).order_by(InboundRecord.received_at))
        )
    assert [row.ai_memory_eligible for row in rows] == [False, False, True]


def test_active_blame_dialogue_is_excluded_until_the_game_ends(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import (
        BlameGamePlayerRecord,
        BlameGameRecord,
        InboundRecord,
    )
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    user, _ = repository.create_user("blame-player", "甩锅玩家", now, 100)
    with session_factory.begin() as session:
        game = BlameGameRecord(
            state="active",
            active_key="global",
            creator_user_id=user.id,
            target_player_count=2,
            signup_deadline=now + timedelta(minutes=1),
            settlement_complete=False,
            created_at=now,
        )
        session.add(game)
        session.flush()
        session.add(
            BlameGamePlayerRecord(
                game_id=game.id,
                user_id=user.id,
                signup_order=1,
                seat_number=1,
                state="joined",
                guarantee_amount=0,
                guarantee_state="held",
                joined_at=now,
            )
        )
    service = CoreService(repository)

    service.receive_inbound(
        InboundMessage("blame-dialogue", user.platform_id, "这个锅不是我的", now)
    )
    with session_factory.begin() as session:
        game = session.scalar(select(BlameGameRecord))
        game.state = "finished"
        game.active_key = None
        game.finished_at = now + timedelta(seconds=1)
    service.receive_inbound(
        InboundMessage(
            "after-blame", user.platform_id, "这局终于结束了", now + timedelta(seconds=2)
        )
    )

    with session_factory() as session:
        rows = list(
            session.scalars(select(InboundRecord).order_by(InboundRecord.received_at))
        )
    assert [row.ai_memory_eligible for row in rows] == [False, True]


def test_service_queues_only_non_command_bot_mentions(session_factory):
    """Fails if commands or ordinary text are routed to the model queue."""
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import (
        AIAssistantSettingsRecord,
        AIRankQuotaRecord,
        AIMemoryJobRecord,
        AIRequestRecord,
        InboundRecord,
    )
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    repository = CoreRepository(session_factory)
    repository.create_user("sender-1", "小明", now, 0)
    repository.get_ai_assistant_settings()
    with session_factory.begin() as session:
        settings = session.get(AIAssistantSettingsRecord, 1)
        settings.enabled = True
        settings.trigger_prefixes = ["@总监事", "/总监事", "/饭饭", "/余额"]
        for quota in session.scalars(select(AIRankQuotaRecord)):
            quota.daily_limit = 10
    service = CoreService(repository)

    service.receive_inbound(InboundMessage("ai-command", "sender-1", "/余额", now))
    service.receive_inbound(InboundMessage("ai-plain", "sender-1", "@总监事 今天适合摸鱼吗？", now))
    service.receive_inbound(InboundMessage("ai-slash", "sender-1", "/饭饭 明天呢？", now))
    service.receive_inbound(InboundMessage("ai-boundary", "sender-1", "/饭饭堂 不应命中", now))
    service.receive_inbound(InboundMessage("ai-empty", "sender-1", "@总监事   ", now))
    service.receive_inbound(InboundMessage("ai-platform-empty", "sender-1", "@总监事「Bot」", now))

    with session_factory() as session:
        request_message_ids = set(
            session.scalars(
                select(InboundRecord.platform_message_id)
                .join(AIRequestRecord, AIRequestRecord.inbound_message_id == InboundRecord.id)
            )
        )
        memory_job = session.scalar(select(AIMemoryJobRecord))
    assert request_message_ids == {"ai-plain", "ai-slash"}
    assert memory_job is None


def test_service_strips_platform_bot_label_from_ai_mention(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import AIAssistantSettingsRecord, AIRequestRecord
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)
    repository = CoreRepository(session_factory)
    repository.create_user("sender-1", "小明", now, 0)
    repository.get_ai_assistant_settings()
    with session_factory.begin() as session:
        session.get(AIAssistantSettingsRecord, 1).enabled = True
    service = CoreService(repository)

    service.receive_inbound(
        InboundMessage("ai-platform-label", "sender-1", "@总监事「Bot」 今天适合摸鱼吗？", now)
    )

    with session_factory() as session:
        assert session.scalar(select(AIRequestRecord)) is not None
    request = repository.claim_ai_request("ai-worker", now, 30)
    assert request is not None
    assert request.user_content == "今天适合摸鱼吗？"


def test_service_uses_random_event_block_message_for_unwrapped_observer(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import BEIJING, InboundRecord, OutboundRecord
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository = CoreRepository(session_factory)
    repository.create_random_event_scene(
        "茶水间", "快点加入吧。", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(["10:00"], "{可选身份}", 15, 5)
    repository.create_user("player", "小明", now, 0)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("player", "员工", now) == "started"
    service = CoreService(repository)

    result = service.receive_inbound(
        InboundMessage("observer-message", "observer", "你好，你们在干什么", now)
    )

    with session_factory() as session:
        warning = session.scalar(
            select(OutboundRecord).where(OutboundRecord.inbound_message_id == result.message_id)
        )
        inbound = session.get(InboundRecord, result.message_id)
    assert warning.text == "当前有随机事件发生，监事不会处理。"
    assert inbound.ai_memory_eligible is False


def test_service_allows_ordinary_chat_during_random_event_tipping(session_factory):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import BEIJING, InboundRecord, OutboundRecord
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository = CoreRepository(session_factory)
    repository.create_random_event_scene(
        "茶水间", "快点加入吧。", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        ["10:00"], "{可选身份}", 15, 5, tipping_duration_seconds=120
    )
    repository.create_user("tipping-chat", "聊天玩家", now, 0)
    schedule = repository.schedule_random_events(now)[0]
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("tipping-chat", "员工", now) == "started"
    assert repository.leave_random_event("tipping-chat", now) == "left_without_reward"
    service = CoreService(repository)

    result = service.receive_inbound(
        InboundMessage(
            "tipping-ordinary-chat",
            "tipping-chat",
            "剧情结束后正常聊天",
            now + timedelta(seconds=1),
        )
    )

    with session_factory() as session:
        inbound = session.get(InboundRecord, result.message_id)
        reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == result.message_id
            )
        )
    assert reply is None
    assert inbound.ai_memory_eligible is True
    assert repository.list_random_event_details(schedule.id) == []


def test_red_packet_commands_bypass_active_random_event_gate(session_factory):
    from random import Random

    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import BEIJING, OutboundRecord
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    repository = CoreRepository(session_factory, red_packet_random=Random(1))
    repository.create_random_event_scene(
        "茶水间", "快点加入吧。", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(["10:00"], "{可选身份}", 15, 5)
    repository.create_user("event-packet", "事件玩家", now, 10)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("event-packet", "员工", now) == "started"
    service = CoreService(repository, GroupCommandHandler(repository))

    result = service.receive_inbound(
        InboundMessage(
            "event-red-packet", "event-packet", "/发红包 2 2", now
        )
    )

    with session_factory() as session:
        reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == result.message_id
            )
        )
    assert reply.text.startswith("【随机运气红包】事件玩家发出")
    assert repository.find_user("event-packet").balance == 8


@pytest.mark.parametrize("content", ["（围观一下）", "(围观一下)"])
def test_service_allows_parenthesized_observer_during_random_event_signup(
    session_factory, content
):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import BEIJING, OutboundRecord
    from dzmm_bot.core.service import CoreService

    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository = CoreRepository(session_factory)
    repository.create_random_event_scene(
        "茶水间", "快点加入吧。", ["正式开始。"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(["10:00"], "{可选身份}", 15, 5)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    service = CoreService(repository)

    result = service.receive_inbound(
        InboundMessage("signup-observer-message", "observer", content, now)
    )

    with session_factory() as session:
        assert session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == result.message_id
            )
        ) is None


def test_enqueue_failure_rolls_back_inbound(session_factory, inbound):
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import InboundRecord, WorkerCommandRecord
    from dzmm_bot.core.service import CoreService

    class ReplyHandler:
        def handle(self, message):
            repository.enqueue_worker_command("restart_browser")
            return "reply"

    repository = CoreRepository(session_factory)
    service = CoreService(repository, ReplyHandler())
    original_enqueue = repository.enqueue_outbound

    def fail_enqueue(message_id, reply, reply_index=0, **kwargs):
        raise RuntimeError("enqueue failed")

    repository.enqueue_outbound = fail_enqueue
    with pytest.raises(RuntimeError, match="enqueue failed"):
        service.receive_inbound(inbound)
    repository.enqueue_outbound = original_enqueue

    with session_factory() as session:
        assert session.scalar(select(InboundRecord)) is None
        assert session.scalar(select(WorkerCommandRecord)) is None


def test_direct_plain_text_advances_only_the_senders_dark_market_draft(
    session_factory,
):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import OutboundRecord, PRIMARY_GROUP_CHAT_ID
    from dzmm_bot.core.service import CoreService

    repository = CoreRepository(session_factory)
    now = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=dark-service", now
    )
    for platform_id, name in (("draft-a", "草稿甲"), ("draft-b", "草稿乙")):
        repository.create_user(platform_id, name, now, 100)
    settings = repository.get_dark_market_settings()
    repository.set_dark_market_settings(
        enabled=True,
        announcement_group_id=PRIMARY_GROUP_CHAT_ID,
        duration_hours=3,
        fee_percent=5,
        rank_limits={item.rank_id: item.daily_limit for item in settings.rank_limits},
        expected_version=settings.version,
    )
    service = CoreService(repository, GroupCommandHandler(repository))
    for platform_id in ("draft-a", "draft-b"):
        service.receive_inbound(
            InboundMessage(
                f"start-{platform_id}",
                platform_id,
                "/上架暗网",
                now,
                source_type="direct",
                chatroom_id=f"direct-{platform_id}",
            )
        )

    advanced = service.receive_inbound(
        InboundMessage(
            "draft-a-name",
            "draft-a",
            "甲的商品",
            now,
            source_type="direct",
            chatroom_id="direct-draft-a",
        )
    )
    unrelated = service.receive_inbound(
        InboundMessage(
            "no-draft-plain",
            "no-draft",
            "普通私聊",
            now,
            source_type="direct",
            chatroom_id="direct-no-draft",
        )
    )

    assert repository.dark_market_draft_step("draft-a", now) == "purpose"
    assert repository.dark_market_draft_step("draft-b", now) == "name"
    with session_factory() as session:
        reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == advanced.message_id
            )
        )
        no_reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.inbound_message_id == unrelated.message_id
            )
        )
    assert "用途" in reply.text
    assert no_reply is None
