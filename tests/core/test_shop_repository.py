from datetime import UTC, datetime, timedelta
from random import Random
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    BEIJING,
    PRIMARY_GROUP_CHAT_ID,
    AdultCardParticipantRecord,
    AdultCardSessionRecord,
    AIAssistantSettingsRecord,
    AIRankQuotaRecord,
    Base,
    GroupChatRecord,
    ItemRecord,
    OutboundRecord,
    RankRecord,
    ShopCommonSenseStateRecord,
    ShopPurchaseRecord,
    ShopSceneJobRecord,
    TexasHoldemDailyStartRecord,
    TexasHoldemSettingsRecord,
    UserItemRecord,
    UserRecord,
)
from dzmm_bot.runtime.contracts import InboundMessage


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 25, 2, 0, tzinfo=UTC)


@pytest.fixture
def setup_repository(now):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory, shop_random=Random(0))
    repository.bootstrap_primary_group("https://www.aikda.com/chat?c=shop", now)
    return repository, factory


def _inbound(repository, platform_id, now, content="/购买 1"):
    record, inserted = repository.accept_inbound(
        InboundMessage(
            str(uuid4()),
            platform_id,
            content,
            now,
            source_type="group",
            chatroom_id="shop",
        ),
        PRIMARY_GROUP_CHAT_ID,
    )
    assert inserted
    return record.id


def _number(repository, key):
    return next(
        item.public_number
        for item in repository.list_active_items()
        if item.system_key == key
    )


def _grant_multiplayer_bonus(repository, platform_id, now):
    number = _number(repository, "multiplayer_quota")
    assert (
        repository.purchase_shop_item(
            _inbound(repository, platform_id, now),
            platform_id,
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "purchased"
    )
    assert (
        repository.use_ordinary_shop_item(
            _inbound(repository, platform_id, now, "/使用"),
            platform_id,
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "completed"
    )


def test_catalog_hides_adult_items_until_group_switch_is_enabled(
    setup_repository, now
) -> None:
    repository, factory = setup_repository

    assert len(repository.list_shop_items()) == 9
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True

    assert len(repository.list_shop_items()) == 22


def test_purchase_is_atomic_numbered_and_idempotent(setup_repository, now) -> None:
    repository, factory = setup_repository
    repository.create_user("buyer", "买家", now, 100)
    inbound_id = _inbound(repository, "buyer", now)
    number = _number(repository, "scratch_a")

    first = repository.purchase_shop_item(
        inbound_id, "buyer", number, PRIMARY_GROUP_CHAT_ID, now
    )
    repeated = repository.purchase_shop_item(
        inbound_id, "buyer", number, PRIMARY_GROUP_CHAT_ID, now
    )

    assert first.status == repeated.status == "purchased"
    assert first.balance == repeated.balance == 95
    assert first.quantity == repeated.quantity == 1
    with factory.begin() as session:
        assert session.scalar(select(UserItemRecord.quantity)) == 1
        assert len(list(session.scalars(select(ShopPurchaseRecord)))) == 1
    activity = repository.list_shop_admin_activity()
    assert activity["purchases"][0]["user_name"] == "买家"
    assert activity["purchases"][0]["item_number"] == number


def test_purchase_enforces_shared_daily_limit_rank_stock_and_adult_switch(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    user, _ = repository.create_user("buyer", "买家", now, 500)
    with factory.begin() as session:
        row = session.get(UserRecord, user.id)
        row.rank_id = session.scalar(
            select(RankRecord.id).where(RankRecord.sort_order == 11)
        )
    for key in ("gift_basic", "gift_intermediate"):
        result = repository.purchase_shop_item(
            _inbound(repository, "buyer", now),
            "buyer",
            _number(repository, key),
            PRIMARY_GROUP_CHAT_ID,
            now,
        )
        assert result.status == "purchased"
    limited = repository.purchase_shop_item(
        _inbound(repository, "buyer", now),
        "buyer",
        _number(repository, "gift_advanced"),
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    assert limited.status == "daily_limit"

    adult = repository.purchase_shop_item(
        _inbound(repository, "buyer", now),
        "buyer",
        _number(repository, "adult_m"),
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    assert adult.status == "adult_disabled"

    custom = repository.add_item("限量章", "限量", 1, 1)
    assert (
        repository.purchase_shop_item(
            _inbound(repository, "buyer", now),
            "buyer",
            custom.public_number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "purchased"
    )
    assert (
        repository.purchase_shop_item(
            _inbound(repository, "buyer", now),
            "buyer",
            custom.public_number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "out_of_stock"
    )


def test_ordinary_cards_apply_effects_and_keep_generic_item(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    owner, _ = repository.create_user("owner", "持有人", now, 500)
    target, _ = repository.create_user("target", "接收人", now, 0)
    with factory.begin() as session:
        rank_id = session.scalar(
            select(RankRecord.id).where(RankRecord.sort_order == 11)
        )
        session.get(UserRecord, owner.id).rank_id = rank_id
    gift_number = _number(repository, "gift_basic")
    scratch_number = _number(repository, "scratch_a")
    for number in (gift_number, scratch_number):
        assert (
            repository.purchase_shop_item(
                _inbound(repository, "owner", now),
                "owner",
                number,
                PRIMARY_GROUP_CHAT_ID,
                now,
            ).status
            == "purchased"
        )

    gift = repository.use_ordinary_shop_item(
        _inbound(repository, "owner", now, "/使用"),
        "owner",
        gift_number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="target",
    )
    scratch = repository.use_ordinary_shop_item(
        _inbound(repository, "owner", now, "/使用"),
        "owner",
        scratch_number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert (gift.status, gift.reward, gift.target_display_name) == (
        "completed",
        2,
        "接收人",
    )
    assert scratch.status == "completed"
    assert 1 <= scratch.reward <= 10
    with factory.begin() as session:
        assert session.get(UserRecord, target.id).balance == 2
        assert all(row.quantity == 0 for row in session.scalars(select(UserItemRecord)))

    custom = repository.add_item("纪念品", "无效果", 1, 2)
    repository.purchase_shop_item(
        _inbound(repository, "owner", now),
        "owner",
        custom.public_number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    assert (
        repository.use_ordinary_shop_item(
            _inbound(repository, "owner", now, "/使用"),
            "owner",
            custom.public_number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "no_effect"
    )


def test_disabled_owned_system_card_can_still_be_used(setup_repository, now) -> None:
    repository, factory = setup_repository
    repository.create_user("disabled-owner", "停用持有人", now, 100)
    number = _number(repository, "scratch_a")
    assert (
        repository.purchase_shop_item(
            _inbound(repository, "disabled-owner", now),
            "disabled-owner",
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "purchased"
    )
    repository.update_shop_item(
        number,
        description="随机获得 1–10 摸鱼币",
        enabled=False,
        minimum_rank_order=None,
        unlimited_stock=True,
        stock=0,
    )

    result = repository.use_ordinary_shop_item(
        _inbound(repository, "disabled-owner", now, "/使用"),
        "disabled-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert result.status == "completed"
    with factory.begin() as session:
        assert session.scalar(select(UserItemRecord.quantity)) == 0


def test_ai_quota_card_is_used_only_after_base_quota(setup_repository, now) -> None:
    repository, factory = setup_repository
    user, _ = repository.create_user("ai-user", "对话者", now, 20)
    repository.get_ai_assistant_settings()
    with factory.begin() as session:
        session.get(AIAssistantSettingsRecord, 1).enabled = True
        session.get(AIRankQuotaRecord, user.rank_id).daily_limit = 0
    number = _number(repository, "ai_quota")
    repository.purchase_shop_item(
        _inbound(repository, "ai-user", now),
        "ai-user",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    repository.use_ordinary_shop_item(
        _inbound(repository, "ai-user", now, "/使用"),
        "ai-user",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    first_ai = _inbound(repository, "ai-user", now, "@总监事 你好")
    second_ai = _inbound(repository, "ai-user", now, "@总监事 再见")

    assert (
        repository.try_enqueue_ai_request(first_ai, "ai-user", "你好", now).state
        == "queued"
    )
    assert (
        repository.try_enqueue_ai_request(second_ai, "ai-user", "再见", now).state
        == "over_limit"
    )


@pytest.mark.parametrize(
    ("game", "expected_status"),
    (
        ("memory", "waiting_opponent"),
        ("undercover", "signup_started"),
        ("number_bomb", "signup_started"),
        ("blame", "signup_started"),
    ),
)
def test_multiplayer_quota_card_extends_each_rank_limited_game(
    setup_repository, now, game, expected_status
) -> None:
    repository, factory = setup_repository
    user, _ = repository.create_user("starter", "发起人", now, 100)
    repository.upsert_direct_chats([("starter", "direct-starter")], now)
    with factory.begin() as session:
        session.get(RankRecord, user.rank_id).multiplayer_game_limit = 0
    if game == "blame":
        repository.create_blame_incident_card("事故", "测试事故", ["测试"])

    def start():
        if game == "memory":
            return repository.start_memory_assessment_duel("starter", now)
        if game == "undercover":
            return repository.start_undercover_signup("starter", 4, now)
        if game == "number_bomb":
            return repository.start_number_bomb_game("starter", now)
        return repository.start_blame_game("starter", 2, now)

    assert start().status == "daily_limit"
    _grant_multiplayer_bonus(repository, "starter", now)
    assert start().status == expected_status


def test_multiplayer_quota_card_extends_texas_holdem_limit(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    creator, _ = repository.create_user("texas-owner", "牌桌发起人", now, 100)
    repository.create_user("texas-guest", "牌桌玩家", now, 100)
    repository.upsert_direct_chats(
        [("texas-owner", "direct-owner"), ("texas-guest", "direct-guest")], now
    )
    repository.get_texas_holdem_settings()
    with factory.begin() as session:
        settings = session.get(TexasHoldemSettingsRecord, 1)
        settings.minimum_players = 2
        settings.minimum_buy_in = 1
        settings.maximum_buy_in = 100
        settings.daily_start_limit = 1
        session.add(
            TexasHoldemDailyStartRecord(
                user_id=creator.id,
                play_date=now.astimezone(BEIJING).date(),
                count=1,
            )
        )

    assert (
        repository.start_texas_holdem_signup("texas-owner", 10, now).status
        == "daily_limit"
    )
    _grant_multiplayer_bonus(repository, "texas-owner", now)
    assert (
        repository.start_texas_holdem_signup("texas-owner", 10, now).status == "created"
    )
    assert repository.join_texas_holdem("texas-guest", now).status == "joined"
    assert repository.start_texas_holdem_hand("texas-owner", now).status == "dealing"


def test_adult_card_requires_switch_direct_room_and_reserves_until_scene(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    owner, _ = repository.create_user("adult-owner", "发起人", now, 200)
    repository.create_user("adult-target", "接收人", now, 0)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_flirt")
    repository.purchase_shop_item(
        _inbound(repository, "adult-owner", now),
        "adult-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    missing_room = repository.start_adult_shop_item(
        _inbound(repository, "adult-owner", now, "/使用"),
        "adult-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="adult-target",
    )
    assert missing_room.status == "direct_chat_required"

    repository.upsert_direct_chats([("adult-owner", "direct-owner")], now)
    started = repository.start_adult_shop_item(
        _inbound(repository, "adult-owner", now, "/使用"),
        "adult-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="adult-target",
    )
    assert started.status == "scene_required"
    assert started.direct_chatroom_id == "direct-owner"
    assert repository.direct_inbound_chatroom_ids(now) == ("direct-owner",)
    assert repository.direct_inbound_chatroom_ids(
        now + timedelta(minutes=30)
    ) == ()
    with factory.begin() as session:
        inventory = session.scalar(
            select(UserItemRecord).where(UserItemRecord.user_id == owner.id)
        )
        assert inventory.quantity == 0

    scene = repository.consume_adult_card_scene(
        "adult-owner", "办公室里的虚构场景", now
    )
    assert scene.status == "awaiting_consent"
    with factory.begin() as session:
        card_session = session.scalar(select(AdultCardSessionRecord))
        participant = session.scalar(select(AdultCardParticipantRecord))
        assert card_session.state == "awaiting_consent"
        assert participant.authorization_outbound_id is not None


def test_m_card_count_keeps_direct_room_subscribed_until_setup_deadline(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("m-owner", "M卡发起人", now, 100)
    repository.upsert_direct_chats([("m-owner", "direct-m-owner")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_m")
    assert repository.purchase_shop_item(
        _inbound(repository, "m-owner", now),
        "m-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    ).status == "purchased"
    assert repository.start_adult_shop_item(
        _inbound(repository, "m-owner", now, "/使用"),
        "m-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    ).status == "scene_required"
    assert repository.consume_adult_card_scene(
        "m-owner", "自愿参与的虚构场景", now
    ).status == "m_count_required"

    assert repository.direct_inbound_chatroom_ids(now) == ("direct-m-owner",)
    assert repository.direct_inbound_chatroom_ids(
        now + timedelta(minutes=30)
    ) == ()


def test_multi_adult_card_collects_unique_participants_and_can_cancel(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("multi-owner", "多人发起", now, 300)
    repository.create_user("target-a", "甲", now, 0)
    repository.create_user("target-b", "乙", now, 0)
    repository.upsert_direct_chats([("multi-owner", "direct-multi")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_three")
    repository.purchase_shop_item(
        _inbound(repository, "multi-owner", now),
        "multi-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    started = repository.start_adult_shop_item(
        _inbound(repository, "multi-owner", now, "/使用"),
        "multi-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="target-a",
    )
    assert (
        repository.consume_adult_card_scene("multi-owner", "三人虚构场景", now).status
        == "participants_required"
    )
    assert (
        repository.invite_adult_card_participant(
            "multi-owner", "target-a", started.session_number, now
        ).status
        == "duplicate_target"
    )
    assert (
        repository.invite_adult_card_participant(
            "multi-owner", "target-b", started.session_number, now
        ).status
        == "awaiting_consent"
    )

    number_m = _number(repository, "adult_m")
    repository.purchase_shop_item(
        _inbound(repository, "multi-owner", now),
        "multi-owner",
        number_m,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    cancellable = repository.start_adult_shop_item(
        _inbound(repository, "multi-owner", now, "/使用"),
        "multi-owner",
        number_m,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    assert (
        repository.cancel_adult_card_session(
            "multi-owner", cancellable.session_number, now
        ).status
        == "cancelled"
    )


def test_adult_participant_invite_enforces_persisted_setup_deadline(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    owner, _ = repository.create_user("late-invite-owner", "超时发起", now, 200)
    repository.create_user("late-invite-a", "超时甲", now, 0)
    repository.create_user("late-invite-b", "超时乙", now, 0)
    repository.upsert_direct_chats([("late-invite-owner", "direct-late-invite")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_three")
    repository.purchase_shop_item(
        _inbound(repository, "late-invite-owner", now),
        "late-invite-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    started = repository.start_adult_shop_item(
        _inbound(repository, "late-invite-owner", now, "/使用"),
        "late-invite-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="late-invite-a",
    )
    assert (
        repository.consume_adult_card_scene(
            "late-invite-owner", "等待第二名参与者", now
        ).status
        == "participants_required"
    )

    result = repository.invite_adult_card_participant(
        "late-invite-owner",
        "late-invite-b",
        started.session_number,
        now + timedelta(minutes=31),
    )

    assert result.status == "expired"
    with factory.begin() as session:
        card_session = session.scalar(select(AdultCardSessionRecord))
        inventory = session.scalar(
            select(UserItemRecord).where(UserItemRecord.user_id == owner.id)
        )
        assert card_session.state == "cancelled"
        assert inventory.quantity == 1


def test_adult_followup_actions_are_bound_to_source_group(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("group-owner", "群隔离发起", now, 200)
    repository.create_user("group-target-a", "群隔离甲", now, 0)
    repository.create_user("group-target-b", "群隔离乙", now, 0)
    repository.upsert_direct_chats([("group-owner", "direct-group-owner")], now)
    second = repository.create_group_chat(
        "第二群",
        "https://www.aikda.com/chat?c=shop-second",
        True,
        True,
        True,
        True,
        now,
        adult_shop_enabled=False,
    )
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_three")
    repository.purchase_shop_item(
        _inbound(repository, "group-owner", now),
        "group-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    started = repository.start_adult_shop_item(
        _inbound(repository, "group-owner", now, "/使用"),
        "group-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="group-target-a",
    )
    repository.consume_adult_card_scene("group-owner", "来源群隔离场景", now)

    assert (
        repository.invite_adult_card_participant(
            "group-owner",
            "group-target-b",
            started.session_number,
            now,
            group_chat_id=second.id,
        ).status
        == "wrong_group"
    )
    assert (
        repository.cancel_adult_card_session(
            "group-owner",
            started.session_number,
            now,
            group_chat_id=second.id,
        ).status
        == "wrong_group"
    )
    assert (
        repository.invite_adult_card_participant(
            "group-owner",
            "group-target-b",
            started.session_number,
            now,
            group_chat_id=PRIMARY_GROUP_CHAT_ID,
        ).status
        == "awaiting_consent"
    )
    with factory.begin() as session:
        participant = session.scalar(
            select(AdultCardParticipantRecord)
            .join(UserRecord, UserRecord.id == AdultCardParticipantRecord.user_id)
            .where(UserRecord.platform_id == "group-target-a")
        )
        session.get(
            OutboundRecord, participant.authorization_outbound_id
        ).platform_sent_id = "group-auth"
    assert (
        repository.decide_adult_card_consent(
            "group-target-a",
            "group-auth",
            True,
            now,
            group_chat_id=second.id,
        ).status
        == "wrong_group"
    )


def test_m_card_collects_scene_then_expected_participant_count(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("m-owner", "M卡发起人", now, 100)
    repository.upsert_direct_chats([("m-owner", "direct-m")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_m")
    repository.purchase_shop_item(
        _inbound(repository, "m-owner", now),
        "m-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    repository.start_adult_shop_item(
        _inbound(repository, "m-owner", now, "/使用"),
        "m-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )

    assert (
        repository.consume_adult_card_scene("m-owner", "自愿参与的虚构场景", now).status
        == "m_count_required"
    )
    assert (
        repository.consume_adult_card_scene("m-owner", "0", now).status
        == "invalid_m_count"
    )
    completed = repository.consume_adult_card_scene("m-owner", "3", now)

    assert completed.status == "m_completed"
    assert "期望人数：3 人" in completed.public_message


def test_owner_cannot_open_two_ambiguous_adult_card_setup_flows(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("setup-owner", "并行发起人", now, 100)
    repository.upsert_direct_chats([("setup-owner", "direct-setup")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_m")
    for index in range(2):
        assert (
            repository.purchase_shop_item(
                _inbound(repository, "setup-owner", now + timedelta(seconds=index)),
                "setup-owner",
                number,
                PRIMARY_GROUP_CHAT_ID,
                now + timedelta(seconds=index),
            ).status
            == "purchased"
        )

    assert (
        repository.start_adult_shop_item(
            _inbound(repository, "setup-owner", now, "/使用 first"),
            "setup-owner",
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        ).status
        == "scene_required"
    )
    assert (
        repository.start_adult_shop_item(
            _inbound(
                repository,
                "setup-owner",
                now + timedelta(seconds=2),
                "/使用 second",
            ),
            "setup-owner",
            number,
            PRIMARY_GROUP_CHAT_ID,
            now + timedelta(seconds=2),
        ).status
        == "setup_active"
    )

    with factory.begin() as session:
        inventory = session.scalar(
            select(UserItemRecord).where(
                UserItemRecord.user_id
                == session.scalar(
                    select(UserRecord.id).where(UserRecord.platform_id == "setup-owner")
                ),
                UserItemRecord.item_id
                == session.scalar(
                    select(ItemRecord.id).where(ItemRecord.public_number == number)
                ),
            )
        )
        assert inventory.quantity == 1


def test_adult_consent_refusal_compensates_and_all_approval_creates_job(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("consent-owner", "授权发起", now, 300)
    repository.create_user("consent-target", "授权目标", now, 0)
    repository.upsert_direct_chats([("consent-owner", "direct-consent")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_flirt")

    def start_session(label):
        repository.purchase_shop_item(
            _inbound(repository, "consent-owner", now, f"/购买 {label}"),
            "consent-owner",
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
        )
        started = repository.start_adult_shop_item(
            _inbound(repository, "consent-owner", now, f"/使用 {label}"),
            "consent-owner",
            number,
            PRIMARY_GROUP_CHAT_ID,
            now,
            target_platform_id="consent-target",
        )
        repository.consume_adult_card_scene("consent-owner", f"场景 {label}", now)
        with factory.begin() as session:
            participant = session.scalar(
                select(AdultCardParticipantRecord)
                .join(AdultCardSessionRecord)
                .where(AdultCardSessionRecord.public_number == started.session_number)
            )
            outbound = session.get(
                OutboundRecord, participant.authorization_outbound_id
            )
            outbound.platform_sent_id = f"auth-{label}"
        return started

    start_session("reject")
    before_reject = repository.find_user("consent-owner").balance
    assert (
        repository.decide_adult_card_consent(
            "consent-target", "auth-reject", False, now
        ).status
        == "rejected"
    )
    assert repository.find_user("consent-owner").balance == before_reject + 10

    approved = start_session("approve")
    assert (
        repository.decide_adult_card_consent(
            "consent-target", "auth-approve", True, now
        ).status
        == "all_approved"
    )
    with factory.begin() as session:
        card_session = session.scalar(
            select(AdultCardSessionRecord).where(
                AdultCardSessionRecord.public_number == approved.session_number
            )
        )
        assert card_session.state == "generating"
        assert (
            session.scalar(
                select(ShopSceneJobRecord).where(
                    ShopSceneJobRecord.session_id == card_session.id
                )
            )
            is not None
        )
    claim = repository.claim_shop_scene_job("ai-worker", now, 90)
    assert claim is not None
    assert "发骚卡" in claim.user_content
    assert (
        repository.fail_shop_scene_job(
            claim.id, "ai-worker", claim.lease_token, "temporary", now
        )
        is True
    )
    assert repository.claim_shop_scene_job("ai-worker", now, 90) is None
    claim = repository.claim_shop_scene_job(
        "ai-worker", now + timedelta(seconds=31), 90
    )
    assert claim is not None
    assert (
        repository.complete_shop_scene_job(
            claim.id,
            "ai-worker",
            claim.lease_token,
            "同意后的场景结果",
            now + timedelta(seconds=31),
        )
        is True
    )
    with factory.begin() as session:
        assert (
            session.scalar(
                select(OutboundRecord.text).where(
                    OutboundRecord.text == "同意后的场景结果"
                )
            )
            == "同意后的场景结果"
        )


def test_adult_consent_enforces_persisted_authorization_deadline(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("late-consent-owner", "授权超时发起", now, 100)
    repository.create_user("late-consent-target", "授权超时目标", now, 0)
    repository.upsert_direct_chats([("late-consent-owner", "direct-late-consent")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_flirt")
    repository.purchase_shop_item(
        _inbound(repository, "late-consent-owner", now),
        "late-consent-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    started = repository.start_adult_shop_item(
        _inbound(repository, "late-consent-owner", now, "/使用"),
        "late-consent-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="late-consent-target",
    )
    repository.consume_adult_card_scene("late-consent-owner", "授权绝对截止测试", now)
    with factory.begin() as session:
        participant = session.scalar(
            select(AdultCardParticipantRecord)
            .join(AdultCardSessionRecord)
            .where(AdultCardSessionRecord.public_number == started.session_number)
        )
        session.get(
            OutboundRecord, participant.authorization_outbound_id
        ).platform_sent_id = "late-consent-auth"
    before = repository.find_user("late-consent-owner").balance

    result = repository.decide_adult_card_consent(
        "late-consent-target",
        "late-consent-auth",
        True,
        now + timedelta(minutes=11),
    )

    assert result.status == "expired"
    assert repository.find_user("late-consent-owner").balance == before + 10
    with factory.begin() as session:
        card_session = session.scalar(select(AdultCardSessionRecord))
        assert card_session.state == "voided"
        assert session.scalar(select(ShopSceneJobRecord)) is None


def test_common_sense_card_creates_and_admin_can_end_source_group_state(
    setup_repository, now
) -> None:
    repository, factory = setup_repository
    repository.create_user("common-owner", "设定发起人", now, 100)
    repository.create_user("common-target", "设定目标", now, 0)
    repository.upsert_direct_chats([("common-owner", "direct-common")], now)
    with factory.begin() as session:
        session.get(GroupChatRecord, PRIMARY_GROUP_CHAT_ID).adult_shop_enabled = True
    number = _number(repository, "adult_common_1h")
    repository.purchase_shop_item(
        _inbound(repository, "common-owner", now),
        "common-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
    )
    started = repository.start_adult_shop_item(
        _inbound(repository, "common-owner", now, "/使用"),
        "common-owner",
        number,
        PRIMARY_GROUP_CHAT_ID,
        now,
        target_platform_id="common-target",
    )
    assert (
        repository.consume_adult_card_scene(
            "common-owner", "目标暂时相信办公室没有星期一", now
        ).status
        == "awaiting_consent"
    )
    with factory.begin() as session:
        participant = session.scalar(
            select(AdultCardParticipantRecord)
            .join(AdultCardSessionRecord)
            .where(AdultCardSessionRecord.public_number == started.session_number)
        )
        session.get(
            OutboundRecord, participant.authorization_outbound_id
        ).platform_sent_id = "common-auth"
    assert (
        repository.decide_adult_card_consent(
            "common-target", "common-auth", True, now
        ).status
        == "all_approved"
    )
    with factory.begin() as session:
        state = session.scalar(select(ShopCommonSenseStateRecord))
        state_id = state.id
        assert state.state == "active"

    assert (
        repository.force_end_shop_common_state(state_id, now + timedelta(minutes=5))
        is True
    )
    assert (
        repository.force_end_shop_common_state(state_id, now + timedelta(minutes=6))
        is True
    )
    with factory.begin() as session:
        assert session.get(ShopCommonSenseStateRecord, state_id).state == "forced_end"
