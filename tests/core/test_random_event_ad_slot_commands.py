from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage

BEIJING = __import__("zoneinfo").ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 9, 15, 16, 20, tzinfo=BEIJING)
TARGET_AT = NOW + timedelta(hours=3)
JOINED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=BEIJING)

_counter = {"value": 0}


@pytest.fixture
def harness():
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base, DirectChatRecord, RankRecord
    from dzmm_bot.core.service import CoreService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    repository.list_ranks()
    with factory.begin() as session:
        session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 1)
        ).multiplayer_game_limit = 999
    service = CoreService(repository, GroupCommandHandler(repository))
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=ad-slot", NOW
    )
    repository.create_user("author", "作者甲", NOW, 100)
    repository.create_user("other", "作者乙", NOW, 100)
    with factory.begin() as session:
        for platform_id, chatroom in (
            ("author", "direct-author"),
            ("other", "direct-other"),
        ):
            session.add(
                DirectChatRecord(
                    platform_user_id=platform_id,
                    chatroom_id=chatroom,
                    discovered_at=JOINED_AT,
                )
            )
    return service, repository, factory, group


def _add_scenes(session, names):
    from dzmm_bot.core.schema import (
        RandomEventSceneOpeningRecord,
        RandomEventSceneRecord,
        RandomEventSceneSeatRecord,
    )

    created = []
    for name in names:
        scene = RandomEventSceneRecord(
            name=name,
            signup_text=f"{name} 报名",
            reward=6,
            target_rounds=3,
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
        created.append(scene)
    return created


def _approve(session, scene, *, platform_id="author", number=1):
    from dzmm_bot.core.schema import RandomEventSubmissionRecord, UserRecord

    user_id = session.scalar(
        select(UserRecord.id).where(UserRecord.platform_id == platform_id)
    )
    session.add(
        RandomEventSubmissionRecord(
            number=number,
            user_id=user_id,
            status="approved",
            current_step="preview",
            content={},
            last_activity_at=JOINED_AT,
            created_at=JOINED_AT,
            updated_at=JOINED_AT,
            submitted_at=JOINED_AT,
            scene_id=scene.id,
        )
    )
    session.flush()


def _schedule(session, repository, *, when, scene_name=None):
    from dzmm_bot.core.schema import RandomEventScheduleRecord

    session.add(
        RandomEventScheduleRecord(
            group_chat_id=repository.list_group_chats()[0].id,
            event_date=when.date(),
            scheduled_at=when,
            status="pending",
            scene_name=scene_name,
        )
    )
    session.flush()


def _open_poll(
    repository,
    factory,
    *,
    works=("作者作品",),
    others=("甲", "乙", "丙", "丁"),
    approve_other=False,
):
    """把作者的作品"排给别的场次"，随机候选就会跳过它——这样用例不依赖随机。"""
    with factory.begin() as session:
        author_scenes = _add_scenes(session, works)
        _add_scenes(session, others)
        for index, scene in enumerate(author_scenes, start=1):
            _approve(session, scene, number=index)
        if approve_other:
            other_scene = session.scalar(
                select_scene(session, others[0])
            )
            _approve(session, other_scene, platform_id="other", number=99)
        for index, scene in enumerate(author_scenes):
            _schedule(
                session,
                repository,
                when=NOW + timedelta(minutes=30 + index),
                scene_name=scene.name,
            )
        if approve_other:
            other_scene = session.scalar(select_scene(session, others[0]))
            _schedule(
                session,
                repository,
                when=NOW + timedelta(minutes=40),
                scene_name=other_scene.name,
            )
        _schedule(session, repository, when=TARGET_AT)
    return repository.create_random_event_poll(NOW)


def select_scene(session, name):
    from dzmm_bot.core.schema import RandomEventSceneRecord

    return select(RandomEventSceneRecord).where(
        RandomEventSceneRecord.name == name
    )


def _card_number(repository):
    from dzmm_bot.core.schema import ItemRecord

    repository.list_shop_items()  # 触发系统商品补种
    with repository._session() as session:
        return session.scalar(
            select(ItemRecord.public_number).where(
                ItemRecord.system_key == "event_ad_slot"
            )
        )


def _card_count(repository, platform_id="author"):
    from dzmm_bot.core.schema import ItemRecord, UserItemRecord, UserRecord

    with repository._session() as session:
        item_id = session.scalar(
            select(ItemRecord.id).where(ItemRecord.system_key == "event_ad_slot")
        )
        user_id = session.scalar(
            select(UserRecord.id).where(UserRecord.platform_id == platform_id)
        )
        record = session.scalar(
            select(UserItemRecord).where(
                UserItemRecord.user_id == user_id,
                UserItemRecord.item_id == item_id,
            )
        )
        return 0 if record is None else record.quantity


def _buy_cards(repository, count, platform_id="author"):
    """走真实购买路径：先造入站记录，再调 `purchase_shop_item`。"""
    from dzmm_bot.core.schema import InboundRecord

    number = _card_number(repository)
    group_id = repository.list_group_chats()[0].id
    with repository.transaction():
        with repository._session() as session:
            for index in range(count):
                record = InboundRecord(
                    platform_message_id=f"buy-{platform_id}-{index}",
                    sender_platform_id=platform_id,
                    content=f"/购买 {number}",
                    received_at=NOW,
                    status="accepted",
                    source_type="group",
                    group_chat_id=group_id,
                    created_at=NOW,
                )
                session.add(record)
                session.flush()
                repository.purchase_shop_item(
                    record.id, platform_id, number, group_id, NOW
                )
    return number


def _purge(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory.begin() as session:
        session.query(OutboundRecord).delete()


def _reply(factory, chatroom_id=None):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        query = select(OutboundRecord.text).order_by(
            OutboundRecord.reply_index, OutboundRecord.created_at
        )
        if chatroom_id is not None:
            query = query.where(
                OutboundRecord.destination_chatroom_id == chatroom_id
            )
        texts = list(session.scalars(query))
    return None if not texts else "\n".join(texts)


def _send(service, group, sender, content, *, direct=False, now=NOW):
    _counter["value"] += 1
    _purge(service._repository._session_factory)
    service.receive_inbound(
        InboundMessage(
            f"m-{_counter['value']}",
            sender,
            content,
            now,
            source_type="direct" if direct else "group",
            chatroom_id=None if direct else group.chatroom_id,
        )
    )


def _slot_candidate(repository):
    report = repository.random_event_poll_report()
    return next(
        candidate for candidate in report.candidates if candidate.source == "ad_slot"
    )


# ------------------------------------------------------------------ 拒绝路径

def test_use_without_a_poll_keeps_the_card(harness):
    service, repository, factory, group = harness
    with factory.begin() as session:
        scene = _add_scenes(session, ("作者作品",))[0]
        _approve(session, scene)
    number = _buy_cards(repository, 1)

    _send(service, group, "author", f"/使用 {number}")

    assert "没有正在征集" in _reply(factory)
    assert _card_count(repository) == 1


def test_use_without_any_approved_work_keeps_the_card(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory, works=(), others=("甲", "乙", "丙", "丁"))
    number = _buy_cards(repository, 1)

    _send(service, group, "author", f"/使用 {number}")

    assert "还没有已审核通过的作品" in _reply(factory)
    assert _card_count(repository) == 1


def test_use_without_a_direct_room_keeps_the_card(harness):
    from dzmm_bot.core.schema import DirectChatRecord

    service, repository, factory, group = harness
    _open_poll(repository, factory)
    with factory.begin() as session:
        session.query(DirectChatRecord).delete()
    number = _buy_cards(repository, 1)

    _send(service, group, "author", f"/使用 {number}")

    assert "请先私聊总监事" in _reply(factory)
    assert _card_count(repository) == 1


def test_use_rejects_a_work_that_is_already_a_candidate(harness):
    """作品已经在随机候选里时，确认要被拒绝，且不消耗卡。"""
    service, repository, factory, group = harness
    with factory.begin() as session:
        scenes = _add_scenes(session, ("甲", "乙", "丙"))
        for index, scene in enumerate(scenes, start=1):
            _approve(session, scene, number=index)
        _schedule(session, repository, when=TARGET_AT)
    repository.create_random_event_poll(NOW)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")

    picked = repository.consume_random_event_ad_slot_draft(
        "author", "/选择 1", NOW
    )
    assert picked.status == "picked"
    result = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )

    assert result.status == "scene_taken"
    assert _card_count(repository) == 1


def test_the_second_author_is_rejected_after_the_slot_is_taken(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory, others=("甲", "乙", "丙", "丁"), approve_other=True)
    number = _buy_cards(repository, 1, "author")
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    first = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )
    assert first.status == "consumed", [
        (candidate.position, candidate.scene_name, candidate.source, candidate.vacant)
        for candidate in repository.random_event_poll_report().candidates
    ]

    number = _buy_cards(repository, 1, "other")
    _send(service, group, "other", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("other", "/选择 1", NOW)
    result = repository.consume_random_event_ad_slot_draft(
        "other", "/确认广告位", NOW
    )

    assert result.status == "slot_taken"
    assert _card_count(repository, "other") == 1


# ------------------------------------------------------------------ 向导

def test_wizard_picks_a_work_and_consumes_the_card(harness):
    service, repository, factory, group = harness
    view = _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    assert "作者作品" not in {c.scene_name for c in view.candidates}

    _send(service, group, "author", f"/使用 {number}")
    assert "作者作品" in _reply(factory)
    assert _card_count(repository) == 1

    _send(service, group, "author", "/选择 1", direct=True)
    assert "已选中" in _reply(factory)

    _send(service, group, "author", "/确认广告位", direct=True)

    assert "已放进本期投票的广告位" in _reply(factory)
    assert _card_count(repository) == 0
    candidate = _slot_candidate(repository)
    assert candidate.vacant is False
    assert candidate.scene_name == "作者作品"


def test_wizard_rejects_a_bad_pick(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")

    _send(service, group, "author", "/选择 9", direct=True)
    assert "没有这个序号" in _reply(factory)

    _send(service, group, "author", "/确认广告位", direct=True)
    assert "请先用 /选择" in _reply(factory)
    assert _card_count(repository) == 1


def test_draft_expires_without_consuming_the_card(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")

    _send(
        service,
        group,
        "author",
        "/选择 1",
        direct=True,
        now=NOW + timedelta(minutes=16),
    )

    assert "向导已经结束" in _reply(factory)
    assert _card_count(repository) == 1


# ------------------------------------------------------------------ 生效

def test_filling_the_slot_announces_it(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    _purge(factory)

    repository.consume_random_event_ad_slot_draft("author", "/确认广告位", NOW)

    text = _reply(factory)
    assert "【事件广告卡】" in text
    assert "作者作品" in text
    assert "/事件投票" in text


def test_the_filled_slot_can_be_voted_and_can_win(harness):
    from dzmm_bot.core.schema import RandomEventScheduleRecord

    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    assert (
        repository.consume_random_event_ad_slot_draft(
            "author", "/确认广告位", NOW
        ).status
        == "consumed"
    )
    slot = _slot_candidate(repository)
    assert slot.vacant is False

    recorded = repository.cast_random_event_vote("other", slot.position, NOW)

    assert recorded.status == "recorded"
    assert recorded.view.my_position == slot.position
    result = repository.close_random_event_poll(
        TARGET_AT - timedelta(minutes=10)
    )
    assert result.position == slot.position
    with repository._session() as session:
        schedule = session.scalar(
            select(RandomEventScheduleRecord).where(
                RandomEventScheduleRecord.scheduled_at == TARGET_AT
            )
        )
    assert schedule.scene_name == "作者作品"


def test_carry_over_keeps_the_filled_slot(harness):
    from dzmm_bot.core.schema import RandomEventScheduleRecord

    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    repository.consume_random_event_ad_slot_draft("author", "/确认广告位", NOW)
    repository.cast_random_event_vote("other", _slot_candidate(repository).position, NOW)
    later = TARGET_AT + timedelta(hours=2)
    with factory.begin() as session:
        _schedule(session, repository, when=later)
        target = session.scalar(
            select(RandomEventScheduleRecord).where(
                RandomEventScheduleRecord.scheduled_at == TARGET_AT
            )
        )
        target.status = "skipped"

    repository.run_random_event_jobs(NOW + timedelta(minutes=5))

    report = repository.random_event_poll_report()
    assert report.status == "open"
    assert report.total_votes == 1
    filled = next(
        candidate
        for candidate in report.candidates
        if candidate.source == "ad_slot"
    )
    assert filled.vacant is False
    assert filled.scene_name == "作者作品"

# ------------------------------------------------------------ 审计发现的漏洞

def _zero_the_card(repository, platform_id="author"):
    """把库存行清零，模拟"确认瞬间卡没了"。"""
    from dzmm_bot.core.schema import ItemRecord, UserItemRecord, UserRecord

    with repository.transaction():
        with repository._session() as session:
            item_id = session.scalar(
                select(ItemRecord.id).where(
                    ItemRecord.system_key == "event_ad_slot"
                )
            )
            user_id = session.scalar(
                select(UserRecord.id).where(UserRecord.platform_id == platform_id)
            )
            row = session.scalar(
                select(UserItemRecord).where(
                    UserItemRecord.user_id == user_id,
                    UserItemRecord.item_id == item_id,
                )
            )
            row.quantity = 0


def test_confirm_without_stock_leaves_the_slot_empty(harness):
    """库存不足在改动任何行之前就要拒绝：不能出现"位子被占、卡没扣"。"""
    from dzmm_bot.core.schema import RandomEventAdSlotRecord

    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    _zero_the_card(repository)
    _purge(factory)

    result = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )

    assert result.status == "item_missing"
    assert _slot_candidate(repository).vacant is True
    assert _slot_candidate(repository).scene_name is None
    with repository._session() as session:
        assert session.scalars(select(RandomEventAdSlotRecord)).all() == []
    assert _reply(factory) is None or "广告位" not in (_reply(factory) or "")


def test_confirm_is_refused_when_the_ad_slot_limit_is_zero(harness):
    """后台把广告位上限设成 0，就不该再有人能占位。"""
    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    repository.set_random_event_settings(
        ["20:00"], "{可选身份}", 15, 5, vote_ad_slot_limit=0
    )

    result = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )

    assert result.status == "slot_disabled"
    assert _card_count(repository) == 1
    assert _slot_candidate(repository).vacant is True


def test_confirm_is_refused_when_voting_is_turned_off(harness):
    service, repository, factory, group = harness
    _open_poll(repository, factory)
    number = _buy_cards(repository, 1)
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    repository.set_random_event_settings(
        ["20:00"], "{可选身份}", 15, 5, vote_enabled=False
    )

    result = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )

    assert result.status == "disabled"
    assert _card_count(repository) == 1
    assert _slot_candidate(repository).vacant is True


def test_a_refusal_is_answered_in_the_direct_chat(harness):
    """设计 §3.3：广告卡的拒绝提示写在私聊，不在群里刷屏。"""
    service, repository, factory, group = harness
    with factory.begin() as session:
        scene = _add_scenes(session, ("作者作品",))[0]
        _approve(session, scene)
    number = _buy_cards(repository, 1)

    _send(service, group, "author", f"/使用 {number}")

    assert "没有正在征集" in (_reply(factory, "direct-author") or "")
    assert "没有正在征集" not in (_reply(factory, group.chatroom_id) or "")


def test_two_ad_slots_let_two_authors_in(harness):
    """上限 2 时第二位作者也能占位，两张卡各扣一张。"""
    service, repository, factory, group = harness
    repository.set_random_event_settings(
        ["20:00"], "{可选身份}", 15, 5, vote_ad_slot_limit=2
    )
    _open_poll(
        repository, factory, others=("甲", "乙", "丙", "丁"), approve_other=True
    )

    number = _buy_cards(repository, 1, "author")
    _send(service, group, "author", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("author", "/选择 1", NOW)
    first = repository.consume_random_event_ad_slot_draft(
        "author", "/确认广告位", NOW
    )
    assert first.status == "consumed"

    number = _buy_cards(repository, 1, "other")
    _send(service, group, "other", f"/使用 {number}")
    repository.consume_random_event_ad_slot_draft("other", "/选择 1", NOW)
    second = repository.consume_random_event_ad_slot_draft(
        "other", "/确认广告位", NOW
    )

    assert second.status == "consumed", [
        (c.position, c.scene_name, c.source, c.vacant)
        for c in repository.random_event_poll_report().candidates
    ]
    slots = [
        candidate
        for candidate in repository.random_event_poll_report().candidates
        if candidate.source == "ad_slot"
    ]
    assert [candidate.position for candidate in slots] == [4, 5]
    assert all(not candidate.vacant for candidate in slots)
    assert _card_count(repository, "author") == 0
    assert _card_count(repository, "other") == 0
