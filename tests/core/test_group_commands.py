from datetime import UTC, datetime, timedelta
from random import Random
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.runtime.contracts import InboundMessage, MessageReference


BEIJING = ZoneInfo("Asia/Shanghai")


def _service(*, red_packet_random=None, number_bomb_random=None):
    from dzmm_bot.core.commands import GroupCommandHandler
    from dzmm_bot.core.repository import CoreRepository
    from dzmm_bot.core.schema import Base
    from dzmm_bot.core.service import CoreService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(
        factory,
        red_packet_random=red_packet_random,
        number_bomb_random=number_bomb_random,
    )
    return CoreService(repository, GroupCommandHandler(repository)), repository, factory


def _receive(service, message_id, sender, content, received_at):
    return service.receive_inbound(
        InboundMessage(message_id, sender, content, received_at)
    )


def _latest_reply(factory):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        latest = session.scalar(
            select(OutboundRecord).order_by(OutboundRecord.created_at.desc())
        )
        if latest is None:
            return None
        if latest.inbound_message_id is None:
            return latest.text
        return "\n".join(
            session.scalars(
                select(OutboundRecord.text)
                .where(OutboundRecord.inbound_message_id == latest.inbound_message_id)
                .order_by(OutboundRecord.reply_index)
            )
        )


def test_group_game_switch_blocks_only_new_game_creation():
    service, repository, factory = _service()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=BEIJING)
    repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main", now
    )
    group = repository.create_group_chat(
        "休息群",
        "https://www.aikda.com/chat?c=group-rest",
        True,
        False,
        True,
        True,
        now,
    )
    repository.create_user("switch-player", "开关玩家", now, 0)

    service.receive_inbound(
        InboundMessage(
            "switch-create",
            "switch-player",
            "/蹦蹦数字炸弹",
            now,
            source_type="group",
            chatroom_id=group.chatroom_id,
        )
    )

    assert _latest_reply(factory) == "蹦蹦数字炸弹当前未开放。"
    assert repository.active_gameplay_summary(
        "switch-player", now, group.id
    ).game_type is None


def _replies_for(factory, inbound_id):
    from dzmm_bot.core.schema import OutboundRecord

    with factory() as session:
        return list(
            session.scalars(
                select(OutboundRecord.text)
                .where(OutboundRecord.inbound_message_id == inbound_id)
                .order_by(OutboundRecord.reply_index)
            )
        )


def _prepare_group_tip_event(repository, now):
    repository.create_random_event_scene(
        "打赏命令场", "报名", ["开始"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        ["12:00"], "{可选身份}", 15, 5, tipping_duration_seconds=120
    )
    repository.create_user("group-tip-target", "收款 员工", now, 0)
    repository.create_user("group-tip-donor", "热心员工", now, 10)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("group-tip-target", "员工", now) == "started"
    assert repository.leave_random_event("group-tip-target", now) == "left_without_reward"


def test_random_event_tip_command_parses_spaced_name_and_replies_to_source():
    service, repository, factory = _service()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=BEIJING)
    _prepare_group_tip_event(repository, now)

    result = _receive(
        service,
        "group-tip-success",
        "group-tip-donor",
        "/打赏 收款 员工 5",
        now,
    )

    assert _replies_for(factory, result.message_id) == [
        "热心员工 向 收款 员工 打赏了 5 摸鱼币。"
    ]
    assert repository.find_user("group-tip-donor").balance == 5
    assert repository.find_user("group-tip-target").balance == 5

    current = _receive(
        service,
        "group-tip-current",
        "group-tip-donor",
        "/当前游戏",
        now,
    )
    current_reply = _replies_for(factory, current.message_id)[0]
    assert "当前游戏：随机事件" in current_reply
    assert "状态：打赏中" in current_reply
    assert "可用指令：/打赏 员工名称 金额" in current_reply


def test_random_event_tip_command_reaches_business_validation_before_tipping():
    service, repository, factory = _service()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=BEIJING)
    repository.create_random_event_scene(
        "进行中场景", "报名", ["开始"], 1, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(["12:00"], "{可选身份}", 15, 5)
    repository.create_user("in-progress-player", "进行中玩家", now, 10)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("in-progress-player", "员工", now) == "started"

    result = _receive(
        service,
        "tip-before-phase",
        "in-progress-player",
        "/打赏 进行中玩家 1",
        now,
    )

    assert _replies_for(factory, result.message_id) == [
        "当前不在随机事件打赏阶段。"
    ]
    assert repository.find_user("in-progress-player").balance == 10


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/打赏", "请用 /打赏 员工名称 金额。"),
        ("/打赏 收款 员工", "打赏金额必须是正整数。"),
        ("/打赏 收款 员工 ０", "打赏金额必须是正整数。"),
        ("/打赏 收款 员工 -1", "打赏金额必须是正整数。"),
        ("/打赏 不存在 1", "未找到该员工。"),
    ],
)
def test_random_event_tip_command_reports_validation(content, expected):
    service, repository, factory = _service()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=BEIJING)
    _prepare_group_tip_event(repository, now)

    _receive(service, f"group-tip-invalid-{content}", "group-tip-donor", content, now)

    assert _latest_reply(factory) == expected


def test_lucky_red_packet_commands_create_claim_complete_and_are_idempotent():
    service, repository, factory = _service(red_packet_random=Random(1))
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("packet-issuer", "发包人", now, 10)
    repository.create_user("packet-other", "抢包人", now, 0)

    _receive(service, "packet-create", "packet-issuer", "/发红包 2 2", now)
    assert _latest_reply(factory) == (
        "【随机运气红包】发包人发出 2 份共 2 摸鱼币的红包，"
        "10 分钟内发送 /抢红包。"
    )

    first = _receive(
        service, "packet-claim-1", "packet-issuer", "/抢红包", now
    )
    duplicate = _receive(
        service, "packet-claim-1", "packet-issuer", "/抢红包", now
    )
    assert first.inserted is True
    assert duplicate.inserted is False
    assert len(_replies_for(factory, first.message_id)) == 1

    second = _receive(
        service, "packet-claim-2", "packet-other", "/抢红包", now
    )
    replies = _replies_for(factory, second.message_id)
    assert len(replies) == 2
    assert "抢包人抢到" in replies[0]
    assert "剩余 0/2 份" in replies[0]
    assert "手气最佳" in replies[1]
    assert "手气最差" in replies[1]
    assert "空包" in replies[1]
    assert sum(user.balance for user in repository.list_users()) == 10


@pytest.mark.parametrize(
    "content",
    (
        "/发红包",
        "/发红包 ２ 2",
        "/发红包 2 2.0",
        "/发红包 1 2",
        "/发红包 51 51",
        "/发红包 3 2",
        "/发红包 2 100000",
    ),
)
def test_lucky_red_packet_rejects_invalid_creation_syntax(content):
    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("packet-invalid", "参数玩家", now, 100000)

    _receive(service, f"invalid-{content}", "packet-invalid", content, now)

    reply = _latest_reply(factory)
    assert reply in {
        "请用 /发红包 人数 总金额 创建红包。",
        "红包人数必须是 2–50，总金额必须是人数至 99999 的半角整数。",
    }
    assert repository.find_user("packet-invalid").balance == 100000


def test_lucky_red_packet_reports_business_rejections_and_help():
    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("packet-poor", "穷玩家", now, 1)

    _receive(service, "packet-poor-create", "packet-poor", "/发红包 2 2", now)
    assert _latest_reply(factory) == "余额不足，无法发出这个红包。"
    _receive(service, "packet-no-active", "packet-poor", "/抢红包", now)
    assert _latest_reply(factory) == "当前没有可以领取的红包。"
    _receive(service, "packet-help", "packet-poor", "/帮助 基础", now)
    reply = _latest_reply(factory)
    assert "/发红包 人数 总金额" in reply
    assert "/抢红包" in reply


def test_join_registers_employee_with_zero_balance_and_beijing_timestamp():
    from dzmm_bot.core.schema import UserRecord

    service, repository, factory = _service()
    received_at = datetime(2026, 8, 5, 1, 5, tzinfo=UTC)

    _receive(service, "message-1", "platform-xiaoming", "/入职 小明", received_at)

    with factory() as session:
        employee = session.scalar(select(UserRecord))
        assert employee.platform_id == "platform-xiaoming"
        assert employee.display_name == "小明"
        assert employee.employee_number == 1
        assert employee.balance == 0
        assert employee.joined_at == received_at.astimezone(BEIJING)
    assert _latest_reply(factory) == (
        "小明，欢迎入职摸鱼公司。你的工号：#0001。"
        "当前余额：0 摸鱼币。"
    )

    me = _receive(service, "message-me", "platform-xiaoming", "/我", received_at)
    assert "工号：#0001" in _replies_for(factory, me.message_id)[0]
    balance = _receive(
        service, "message-balance", "platform-xiaoming", "/余额", received_at
    )
    assert "#0001" not in _replies_for(factory, balance.message_id)[0]


def test_join_and_rename_commands_reject_occupied_names():
    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("rename-1", "甲", now, 10)
    repository.create_user("rename-2", "乙", now, 20)

    join_conflict = _receive(
        service, "join-conflict", "rename-3", "/入职 乙", now
    )
    rename_conflict = _receive(
        service, "rename-conflict", "rename-1", "/修改名称 乙", now
    )
    existing_platform = _receive(
        service, "join-existing", "rename-1", "/入职 乙", now
    )

    assert _replies_for(factory, join_conflict.message_id) == ["名称已被占用。"]
    assert _replies_for(factory, rename_conflict.message_id) == ["名称已被占用。"]
    assert _replies_for(factory, existing_platform.message_id) == [
        "甲已经在职，当前余额：10 摸鱼币。"
    ]
    employee = repository.find_user("rename-1")
    assert employee.display_name == "甲"
    assert employee.employee_number == 1
    assert employee.balance == 10


def test_rename_command_reports_usage_validation_membership_and_no_change():
    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
    repository.create_user("rename-errors", "原名", now, 0)

    cases = (
        ("rename-usage", "rename-errors", "/修改名称", "请用 /修改名称 新名称 修改自己的名称。"),
        (
            "rename-long",
            "rename-errors",
            f"/修改名称 {'名' * 65}",
            "名称长度必须为 1–64 个字符。",
        ),
        ("rename-missing", "missing", "/修改名称 新名", "请先用 /入职 名字 加入摸鱼公司。"),
        ("rename-same", "rename-errors", "/修改名称 原名", "名称没有变化。"),
    )
    for message_id, sender, content, expected in cases:
        result = _receive(service, message_id, sender, content, now)
        assert _replies_for(factory, result.message_id) == [expected]

    help_result = _receive(
        service, "rename-help", "rename-errors", "/帮助 基础", now
    )
    assert "/修改名称 新名称" in _replies_for(factory, help_result.message_id)[0]


def test_personal_profile_commands_edit_and_show_only_profile_text():
    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    repository.create_user("profile-player", "档案玩家", now, 20)

    _receive(service, "profile-edit", "profile-player", "/编辑档案 喜欢桌游\n住在上海", now)
    assert _latest_reply(factory) == "个人档案已更新。"
    _receive(service, "profile-show", "profile-player", "/我的档案", now)
    assert _latest_reply(factory) == "喜欢桌游\n住在上海"
    assert repository.find_user("profile-player").balance == 10
    assert repository.get_profile_settings().shared_labor == 4

    help_result = _receive(
        service, "profile-help", "profile-player", "/帮助 基础", now
    )
    help_reply = _replies_for(factory, help_result.message_id)[0]
    assert "/编辑档案 档案内容" in help_reply
    assert "/我的档案" in help_reply


def test_personal_profile_commands_validate_membership_length_and_empty_state():
    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    repository.create_user("profile-player", "档案玩家", now, 20)

    cases = (
        ("profile-missing", "missing", "/编辑档案 内容", "请先用 /入职 名字 加入摸鱼公司。"),
        ("profile-usage", "profile-player", "/编辑档案", "请用 /编辑档案 档案内容 更新个人档案。"),
        ("profile-long", "profile-player", f"/编辑档案 {'字' * 801}", "个人档案不能超过 800 个字符。"),
        ("profile-empty", "profile-player", "/我的档案", "你还没有填写个人档案，请发送 /编辑档案 档案内容"),
    )
    for message_id, sender, content, expected in cases:
        _receive(service, message_id, sender, content, now)
        assert _latest_reply(factory) == expected

    _receive(service, "profile-max", "profile-player", f"/编辑档案 {'字' * 800}", now)
    assert _latest_reply(factory) == "个人档案已更新。"


def test_personal_profile_unchanged_and_resource_failures_do_not_partially_charge():
    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    repository.create_user("profile-player", "档案玩家", now, 10)

    _receive(service, "profile-first", "profile-player", "/编辑档案 第一版", now)
    _receive(service, "profile-same", "profile-player", "/编辑档案 第一版", now)
    assert _latest_reply(factory) == "档案内容没有变化。"
    assert repository.get_profile_settings().shared_labor == 4

    _receive(service, "profile-poor", "profile-player", "/编辑档案 第二版", now)
    assert _latest_reply(factory) == "余额不足，编辑档案需要 10 摸鱼币。"
    assert repository.get_profile_settings().shared_labor == 4

    repository.set_profile_settings(0, 0, expected_version=0)
    _receive(service, "profile-no-labor", "profile-player", "/编辑档案 第二版", now)
    assert _latest_reply(factory) == "当前公共人力不足，暂时无法编辑档案。"
    assert repository.get_personal_profile("profile-player") == "第一版"


def test_profile_image_command_validates_reference_and_profile_prerequisite():
    service, repository, _ = _service()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    repository.create_user("image-player", "形象玩家", now, 20)
    handler = service._command_handler

    assert handler.handle(InboundMessage(
        "image-usage", "image-player", "/编辑档案形象", now
    )) == "请先完成个人档案，再设置档案形象。"
    reference = MessageReference(
        "source-image", "other", "image", "https://cdn.example.com/profile.png"
    )
    assert handler.handle(InboundMessage(
        "image-no-profile", "image-player", "/编辑档案形象", now,
        reference=reference,
    )) == "请先完成个人档案，再设置档案形象。"
    assert handler.handle(InboundMessage(
        "image-not-joined", "missing", "/编辑档案形象", now,
        reference=reference,
    )) == "请先用 /入职 名字 加入摸鱼公司。"

    repository.set_personal_profile_by_admin("image-player", "个人介绍")
    assert handler.handle(InboundMessage(
        "image-invalid-url", "image-player", "/编辑档案形象", now,
        reference=MessageReference("invalid", "other", "image", "not-a-url"),
    )) == "请回复一张图片后发送 /编辑档案形象。"
    assert repository.find_user("image-player").balance == 20


def test_basic_help_lists_profile_image_command():
    service, repository, factory = _service()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    repository.create_user("image-player", "形象玩家", now, 20)

    _receive(service, "profile-image-help", "image-player", "/帮助 基础", now)

    assert "/编辑档案形象（回复一张图片）" in _latest_reply(factory)


def test_profile_image_command_updates_and_my_profile_returns_optional_image_reply():
    from dzmm_bot.core.service import CommandReply

    service, repository, _ = _service()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    repository.create_user("image-player", "形象玩家", now, 30)
    repository.set_personal_profile_by_admin("image-player", "喜欢桌游")
    handler = service._command_handler
    image_url = "https://cdn.example.com/profile.webp"
    reference = MessageReference("source-image", "other", "image", image_url)

    assert handler.handle(InboundMessage(
        "image-update", "image-player", "/编辑档案形象", now,
        reference=reference,
    )) == "档案形象已更新。"
    shown = handler.handle(InboundMessage(
        "image-show", "image-player", "/我的档案", now
    ))

    assert shown == [
        CommandReply("喜欢桌游"),
        CommandReply("", content_type="image", image_url=image_url, image_alt="档案形象"),
    ]
    assert repository.find_user("image-player").balance == 20
    assert repository.get_profile_settings().shared_labor == 4


def test_my_profile_service_queues_text_then_image():
    from dzmm_bot.core.schema import OutboundRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    repository.create_user("image-player", "形象玩家", now, 30)
    repository.set_personal_profile_by_admin("image-player", "喜欢桌游")
    repository.set_profile_image_by_admin(
        "image-player", "https://cdn.example.com/profile.webp"
    )

    result = _receive(service, "image-show-service", "image-player", "/我的档案", now)

    with factory() as session:
        replies = list(session.scalars(
            select(OutboundRecord)
            .where(OutboundRecord.inbound_message_id == result.message_id)
            .order_by(OutboundRecord.reply_index)
        ))
    assert [reply.content_type for reply in replies] == ["text", "image"]
    assert [reply.text for reply in replies] == ["喜欢桌游", ""]
    assert replies[1].image_url == "https://cdn.example.com/profile.webp"


def test_profile_image_command_unchanged_and_resource_failures_are_reported():
    service, repository, _ = _service()
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    repository.create_user("image-player", "形象玩家", now, 10)
    repository.set_personal_profile_by_admin("image-player", "个人介绍")
    handler = service._command_handler
    first_url = "https://cdn.example.com/a.png"

    assert handler.handle(InboundMessage(
        "image-first", "image-player", "/编辑档案形象", now,
        reference=MessageReference("a", "other", "image", first_url),
    )) == "档案形象已更新。"
    assert handler.handle(InboundMessage(
        "image-same", "image-player", "/编辑档案形象", now,
        reference=MessageReference("a", "other", "image", first_url),
    )) == "档案形象没有变化。"
    assert handler.handle(InboundMessage(
        "image-poor", "image-player", "/编辑档案形象", now,
        reference=MessageReference("b", "other", "image", "https://cdn.example.com/b.png"),
    )) == "余额不足，编辑档案形象需要 10 摸鱼币。"

    repository.set_profile_settings(0, 0, expected_version=0)
    assert handler.handle(InboundMessage(
        "image-no-labor", "image-player", "/编辑档案形象", now,
        reference=MessageReference("c", "other", "image", "https://cdn.example.com/c.png"),
    )) == "当前公共人力不足，暂时无法编辑档案形象。"


def test_number_bomb_group_commands_start_join_and_reject_group_reports():
    service, repository, factory = _service(number_bomb_random=Random(5))
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    for index in range(1, 4):
        _receive(service, f"join-{index}", f"bomb-p{index}", f"/入职 炸弹{index}", now)
    repository.upsert_direct_chats(
        [(f"bomb-p{index}", f"direct-bomb-p{index}") for index in range(1, 4)],
        now,
    )

    _receive(service, "bad-start", "bomb-p1", "/蹦蹦数字炸弹 6", now)
    assert _latest_reply(factory) == "请直接发送 /蹦蹦数字炸弹 创建报名局。"
    _receive(service, "start", "bomb-p1", "/蹦蹦数字炸弹", now)
    assert "炸弹1 发起了报名，当前 1 人" in _latest_reply(factory)
    _receive(service, "add-2", "bomb-p2", "/加入", now)
    assert "当前 2 人" in _latest_reply(factory)
    _receive(service, "add-3", "bomb-p3", "/加入", now)
    assert "当前 3 人" in _latest_reply(factory)
    _receive(service, "manual-start", "bomb-p2", "/开始", now)
    started = _latest_reply(factory)
    assert "第 1 轮 - 真心话" in started
    assert "参与者：炸弹1、炸弹2、炸弹3" in started
    assert started.count("请按这个格式报数给我 /报数 数字") == 3
    assert "倍率" not in started
    assert "×1.2" not in started

    reminder = repository.run_number_bomb_jobs(now + timedelta(seconds=15))[0]
    assert "倍率" not in reminder
    assert "×1.2" not in reminder

    _receive(service, "group-report", "bomb-p1", "/报数 29", now)
    assert _latest_reply(factory) == "请私聊总监事发送 /报数 1-100，群内报数不会生效。"


def test_current_game_reports_number_bomb_and_next_commands():
    service, repository, factory = _service()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    repository.create_user("current-p1", "甲", now, 20)
    repository.upsert_direct_chats([("current-p1", "direct-current-p1")], now)
    repository.start_number_bomb_game("current-p1", now)

    _receive(service, "current-game", "current-p1", "/当前游戏", now)

    reply = _latest_reply(factory)
    assert "蹦蹦数字炸弹" in reply
    assert "报名中" in reply
    assert "/开始" in reply


def test_number_bomb_skip_command_removes_targets_from_entire_game():
    service, repository, factory = _service()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    for index in range(1, 6):
        repository.create_user(f"skip-command-p{index}", f"跳过玩家{index}", now, 0)
        repository.upsert_direct_chats(
            [(f"skip-command-p{index}", f"direct-skip-command-p{index}")], now
        )
    repository.start_number_bomb_game("skip-command-p1", now)
    for index in range(2, 6):
        repository.join_number_bomb_game(f"skip-command-p{index}", now)
    repository.start_number_bomb_round("skip-command-p1", now)

    _receive(service, "skip-early", "skip-command-p1", "/跳过 2", now)
    assert "首次未报数提醒后" in _latest_reply(factory)
    repository.run_number_bomb_jobs(now + timedelta(seconds=15))
    _receive(service, "skip-batch", "skip-command-p1", "/跳过 2 4", now)

    reply = _latest_reply(factory)
    assert "2号 跳过玩家2" in reply
    assert "4号 跳过玩家4" in reply
    assert "已从整场移除" in reply
    assert [(player.roster_order, player.state) for player in repository.number_bomb_game_summary().players] == [
        (1, "current"), (3, "current"), (5, "current")
    ]


def test_skip_without_a_matching_game_reports_unavailable():
    service, _, factory = _service()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)

    _receive(service, "skip-no-game", "outsider", "/跳过 2", now)

    assert _latest_reply(factory) == "当前没有可执行跳过的游戏。"


def test_end_game_hits_waiting_memory_duel_instead_of_undercover_fallback():
    service, repository, factory = _service()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    repository.create_user("memory-host", "甲", now, 20)
    repository.start_memory_assessment_duel("memory-host", now)

    _receive(service, "end-memory", "memory-host", "/结束游戏", now)

    reply = _latest_reply(factory)
    assert "记忆考核" in reply
    assert "谁是卧底" not in reply
    assert repository.active_gameplay_summary("memory-host", now).game_type is None


def test_generic_exit_cancels_waiting_memory_duel_immediately():
    service, repository, factory = _service()
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    repository.create_user("memory-exit-host", "甲", now, 20)
    repository.start_memory_assessment_duel("memory-exit-host", now)

    _receive(service, "exit-memory", "memory-exit-host", "/退出", now)

    assert "已取消" in _latest_reply(factory)
    assert repository.active_gameplay_summary("memory-exit-host", now).game_type is None
    assert repository.find_user("memory-exit-host").balance == 20


def test_board_member_can_force_end_another_players_memory_assessment():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
    repository.create_user("memory-player", "记忆玩家", now, 0)
    repository.create_user("board", "董事", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        board = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "board")
        )
        assert board_rank is not None
        assert board is not None
        board.rank_id = board_rank.id
    repository.start_memory_assessment_single("memory-player", now)

    _receive(service, "board-force-end", "board", "/结束游戏", now)

    assert repository.active_gameplay_summary("board", now).game_type is None
    assert _latest_reply(factory) == "【记忆考核】管理员已强制结束当前游戏。"


def test_nonboard_group_manager_cannot_force_end_another_players_game():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
    repository.create_user("memory-player", "记忆玩家", now, 0)
    repository.create_user("manager", "负责人", now, 0)
    with factory.begin() as session:
        manager_rank = session.scalar(
            select(RankRecord).where(
                RankRecord.has_group_management.is_(True),
                RankRecord.is_board.is_(False),
            )
        )
        manager = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "manager")
        )
        assert manager_rank is not None
        assert manager is not None
        manager.rank_id = manager_rank.id
    repository.start_memory_assessment_single("memory-player", now)

    _receive(service, "manager-force-end", "manager", "/结束游戏", now)

    assert _latest_reply(factory) == (
        "已命中当前记忆考核；对战开始后请发送 /退出 执行投降，"
        "等待对手阶段可直接取消。"
    )
    assert (
        repository.active_gameplay_summary("manager", now).game_type
        == "memory_single"
    )


def test_board_member_force_end_is_not_blocked_by_random_event_rules():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    repository.create_user("board", "董事", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        board = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "board")
        )
        assert board_rank is not None
        assert board is not None
        board.rank_id = board_rank.id
    repository.create_random_event_scene(
        "会议室", "临时会议开始。", ["正式开始。"], 4, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        ["10:00"], "可选身份：{可选身份}", 15, 5
    )
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)

    _receive(service, "board-force-end-event", "board", "/结束游戏", now)

    assert repository.active_gameplay_summary("board", now).game_type is None
    assert _latest_reply(factory) == "【随机事件】管理员已强制结束当前游戏。"


def test_board_member_force_end_settles_random_event_tipping_phase():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    repository.create_user("tipping-board", "打赏董事", now, 0)
    repository.create_user("tipping-player", "事件玩家", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        board = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "tipping-board")
        )
        assert board_rank is not None
        assert board is not None
        board.rank_id = board_rank.id
    repository.create_random_event_scene(
        "强制结算场", "报名", ["正式开始。"], 4, 1, [("员工", 1)]
    )
    repository.set_random_event_settings(
        ["10:00"], "可选身份：{可选身份}", 15, 5
    )
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert repository.join_random_event("tipping-player", "员工", now) == "started"
    assert repository.leave_random_event("tipping-player", now) == "left_without_reward"

    _receive(
        service,
        "board-force-end-tipping",
        "tipping-board",
        "/结束游戏",
        now,
    )

    assert repository.active_gameplay_summary("tipping-board", now).game_type is None
    assert _latest_reply(factory).startswith("【随机事件打赏已强制结束】")


def test_board_bonus_command_grants_single_and_all_employees():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    board, _ = repository.create_user("board", "董事", now, 0)
    repository.create_user("recipient", "苏  白", now, 0)
    repository.create_user("other", "其他员工", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        assert board_rank is not None
        session.get(UserRecord, board.id).rank_id = board_rank.id

    _receive(service, "single-bonus", "board", "/发奖金 苏  白 10", now)

    assert _latest_reply(factory) == "【奖金】董事向苏  白发放 10 摸鱼币。"
    assert repository.find_user("recipient").balance == 10

    _receive(service, "all-bonus", "board", "/发奖金 全部 7", now)

    assert _latest_reply(factory) == "【奖金】董事向全体 3 名员工每人发放 7 摸鱼币。"
    assert {user.platform_id: user.balance for user in repository.list_users()} == {
        "board": 7,
        "recipient": 17,
        "other": 7,
    }


def test_board_bonus_all_target_precedes_name_lookup_and_is_idempotent():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    board, _ = repository.create_user("board", "董事", now, 0)
    repository.create_user("reserved-name", "全部", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        assert board_rank is not None
        session.get(UserRecord, board.id).rank_id = board_rank.id

    first = _receive(service, "same-bonus", "board", "/发奖金 全部 7", now)
    duplicate = _receive(service, "same-bonus", "board", "/发奖金 全部 7", now)

    assert first.inserted is True
    assert duplicate.inserted is False
    assert _latest_reply(factory) == "【奖金】董事向全体 2 名员工每人发放 7 摸鱼币。"
    assert {user.platform_id: user.balance for user in repository.list_users()} == {
        "board": 7,
        "reserved-name": 7,
    }


def test_board_bonus_command_rejects_nonboard_and_missing_targets():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    board, _ = repository.create_user("board", "董事", now, 0)
    manager, _ = repository.create_user("manager", "负责人", now, 0)
    repository.create_user("target", "目标员工", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        manager_rank = session.scalar(
            select(RankRecord).where(
                RankRecord.has_group_management.is_(True),
                RankRecord.is_board.is_(False),
            )
        )
        assert board_rank is not None
        assert manager_rank is not None
        session.get(UserRecord, board.id).rank_id = board_rank.id
        session.get(UserRecord, manager.id).rank_id = manager_rank.id

    _receive(service, "unauthorized-bonus", "manager", "/发奖金 目标员工 10", now)
    assert _latest_reply(factory) == "只有核心董事会成员可以发放奖金。"
    _receive(service, "missing-bonus", "board", "/发奖金 不存在 10", now)
    assert _latest_reply(factory) == "未找到该员工，请检查员工名。"
    assert all(user.balance == 0 for user in repository.list_users())

    _receive(service, "numbered-bonus", "board", "/发奖金 #0003 10", now)
    assert _latest_reply(factory) == "【奖金】董事向目标员工发放 10 摸鱼币。"
    assert repository.find_user("target").balance == 10


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("/发奖金", "请用 /发奖金 员工名 金额 或 /发奖金 全部 金额。"),
        ("/发奖金 苏白", "请用 /发奖金 员工名 金额 或 /发奖金 全部 金额。"),
        ("/发奖金 苏白 0", "奖金金额必须是 1–99999 的整数。"),
        ("/发奖金 苏白 -1", "奖金金额必须是 1–99999 的整数。"),
        ("/发奖金 苏白 1.5", "奖金金额必须是 1–99999 的整数。"),
        ("/发奖金 苏白 １００", "奖金金额必须是 1–99999 的整数。"),
        ("/发奖金 苏白 100000", "奖金金额必须是 1–99999 的整数。"),
    ],
)
def test_board_bonus_command_rejects_invalid_syntax_and_amounts(content, expected):
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)
    board, _ = repository.create_user("board", "董事", now, 0)
    repository.create_user("recipient", "苏白", now, 0)
    with factory.begin() as session:
        board_rank = session.scalar(
            select(RankRecord).where(RankRecord.is_board.is_(True))
        )
        assert board_rank is not None
        session.get(UserRecord, board.id).rank_id = board_rank.id

    _receive(service, f"invalid-bonus-{content}", "board", content, now)

    assert _latest_reply(factory) == expected
    assert all(user.balance == 0 for user in repository.list_users())


def test_help_basic_lists_board_bonus_command():
    service, _, factory = _service()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=BEIJING)

    _receive(service, "bonus-help", "viewer", "/帮助 基础", now)

    assert "/发奖金 员工名 金额；/发奖金 全部 金额：仅核心董事会发放" in _latest_reply(factory)


def test_checkin_awards_five_once_per_beijing_date_and_uses_beijing_dates():
    from dzmm_bot.core.schema import DailyCheckinRecord, UserRecord

    service, _, factory = _service()
    _receive(
        service,
        "message-1",
        "platform-xiaoming",
        "/入职 小明",
        datetime(2026, 8, 5, 15, 0, tzinfo=UTC),
    )

    _receive(
        service,
        "message-2",
        "platform-xiaoming",
        "/打卡",
        datetime(2026, 8, 5, 15, 30, tzinfo=UTC),
    )
    assert _latest_reply(factory) == "打卡成功，领取 5 摸鱼币。当前余额：5 摸鱼币。"

    _receive(
        service,
        "message-3",
        "platform-xiaoming",
        "/打卡",
        datetime(2026, 8, 5, 15, 45, tzinfo=UTC),
    )
    assert _latest_reply(factory) == "今天已经打过卡啦，明天再来。"

    _receive(
        service,
        "message-4",
        "platform-xiaoming",
        "/打卡",
        datetime(2026, 8, 5, 16, 0, tzinfo=UTC),
    )
    assert _latest_reply(factory) == "打卡成功，领取 5 摸鱼币。当前余额：10 摸鱼币。"

    with factory() as session:
        employee = session.scalar(select(UserRecord))
        checkins = session.scalars(
            select(DailyCheckinRecord).order_by(DailyCheckinRecord.checkin_date)
        ).all()
        assert employee.balance == 10
        assert [record.checkin_date.isoformat() for record in checkins] == [
            "2026-08-05",
            "2026-08-06",
        ]
        assert checkins[0].checked_in_at.tzinfo == BEIJING


def test_updated_economy_applies_to_future_join_and_checkin_only():
    service, repository, factory = _service()
    repository.set_game_settings("工分", 3, 7, 5)
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "join", "platform-xiaoming", "/入职 小明", received_at)
    assert _latest_reply(factory) == (
        "小明，欢迎入职摸鱼公司。你的工号：#0001。当前余额：3 工分。"
    )

    _receive(service, "checkin", "platform-xiaoming", "/打卡", received_at)
    assert _latest_reply(factory) == "打卡成功，领取 7 工分。当前余额：10 工分。"

    _receive(service, "help", "platform-xiaoming", "/帮助 基础", received_at)
    assert "/打卡：每日领取 7 工分" in _latest_reply(factory)


def test_balance_inventory_and_shop_require_employee_and_return_persisted_data():
    service, repository, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "message-1", "platform-xiaoming", "/余额", received_at)
    assert _latest_reply(factory) == "请先用 /入职 名字 加入摸鱼公司。"

    _receive(service, "message-2", "platform-xiaoming", "/入职 小明", received_at)
    _receive(service, "message-3", "platform-xiaoming", "/我的物品", received_at)
    assert _latest_reply(factory) == "小明的物品：\n暂时空空如也。"

    repository.add_item("工位午睡券", "允许正大光明眯十分钟。", 5, 3)
    _receive(service, "message-4", "platform-xiaoming", "/商店", received_at)
    assert _latest_reply(factory) == "总监事小卖部：\n工位午睡券（5 摸鱼币，库存 3）"


def test_me_alias_shows_balance_level_and_today_income_without_count():
    service, repository, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    repository.set_game_settings("摸鱼币", 3, 5, 5)

    _receive(service, "join", "platform-xiaoming", "/入职 小明", received_at)
    _receive(
        service,
        "activity",
        "platform-xiaoming",
        "一二三四五六七八九十",
        received_at,
    )
    _receive(service, "me", "platform-xiaoming", "/me", received_at)

    reply = _latest_reply(factory)
    assert "小明" in reply
    assert "3 摸鱼币" in reply
    assert "LV1" in reply
    assert "今日收益：3 摸鱼币" in reply
    assert "连续打卡：0 天" in reply
    assert "10" not in reply


def test_undercover_group_commands_signup_deal_vote_and_settle():
    from dzmm_bot.core.schema import (
        UndercoverGamePlayerRecord,
        UndercoverGameRecord,
        UndercoverWordSetRecord,
        UserRecord,
    )

    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    platform_ids = ["undercover-1", "undercover-2", "undercover-3", "undercover-4"]
    for number, platform_id in enumerate(platform_ids, start=1):
        _receive(service, f"join-{number}", platform_id, f"/入职 员工{number}", now)
    with factory.begin() as session:
        session.add(
            UndercoverWordSetRecord(
                category="测试",
                civilian_word="咖啡",
                undercover_word="奶茶",
                enabled=True,
                created_at=now,
            )
        )
    repository.upsert_direct_chats(
        [(platform_id, f"direct-{platform_id}") for platform_id in platform_ids], now
    )

    _receive(service, "undercover-start", platform_ids[0], "/谁是卧底 4", now)
    assert "报名开启" in _latest_reply(factory)
    for index, platform_id in enumerate(platform_ids[1:], start=2):
        _receive(service, f"undercover-join-{index}", platform_id, "/加入", now)
    assert "正在私聊发放身份" in _latest_reply(factory)

    with factory() as session:
        game = session.scalar(select(UndercoverGameRecord))
        assert game is not None
        players = list(
            session.execute(
                select(
                    UserRecord.platform_id,
                    UndercoverGamePlayerRecord.role,
                    UndercoverGamePlayerRecord.seat_number,
                )
                .join(UserRecord, UserRecord.id == UndercoverGamePlayerRecord.user_id)
                .where(UndercoverGamePlayerRecord.game_id == game.id)
            )
        )
    for platform_id in platform_ids:
        repository.record_undercover_card_delivery(game.id, platform_id, True, now)
    undercover_seat = next(seat for _, role, seat in players if role == "undercover")
    seat_by_platform_id = {platform_id: seat for platform_id, _, seat in players}

    _receive(service, "undercover-exit-next", platform_ids[0], "/退出", now)
    exit_reply = _latest_reply(factory)
    assert "下一轮退出" in exit_reply
    assert "员工1" in exit_reply
    assert repository.undercover_session_summary().state == "speaking"

    _receive(service, "undercover-vote", platform_ids[0], "/开始投票", now)
    assert "投票开始" in _latest_reply(factory)
    _receive(
        service,
        "undercover-ballot-1",
        platform_ids[0],
        f"/投票 {undercover_seat}",
        now,
    )
    assert (
        f"{seat_by_platform_id[platform_ids[0]]}号 员工1 已投票（1/4）"
        in _latest_reply(factory)
    )
    _receive(
        service,
        "undercover-skip-3",
        platform_ids[1],
        f"/跳过 {seat_by_platform_id[platform_ids[2]]}",
        now,
    )
    skip_reply = _latest_reply(factory)
    assert (
        f"{seat_by_platform_id[platform_ids[2]]}号 员工3 本轮弃票（2/4"
        in skip_reply
    )
    assert "已投票 1 人、弃票 1 人" in skip_reply
    _receive(
        service,
        "undercover-abstained-ballot",
        platform_ids[2],
        f"/投票 {undercover_seat}",
        now,
    )
    assert "本轮已经弃票" in _latest_reply(factory)
    for index, platform_id in ((2, platform_ids[1]), (4, platform_ids[3])):
        _receive(
            service,
            f"undercover-ballot-{index}",
            platform_id,
            f"/投票 {undercover_seat}",
            now,
        )
    final_reply = _latest_reply(factory)
    assert "平民阵营获胜" in final_reply
    assert "平民词：咖啡" in final_reply
    assert "卧底词：奶茶" in final_reply
    assert "全部身份：" in final_reply
    for number in range(1, 5):
        assert f"员工{number}" in final_reply
    assert "手动弃票：" in final_reply
    assert "员工3" in final_reply
    assert "下一轮退出：员工1" in final_reply
    assert repository.undercover_session_summary().state == "awaiting_continue"


def test_help_lists_undercover_commands():
    service, _, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "help-undercover", "employee", "/帮助 谁是卧底", now)

    reply = _latest_reply(factory)
    assert "/谁是卧底 人数：" in reply
    assert "/开始投票：" in reply
    assert "/退出：" in reply
    assert "/退出谁是卧底：" not in reply


def test_blame_group_commands_create_join_transfer_and_end():
    from dzmm_bot.core.schema import RankRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    repository.create_user("blame-1", "甲", now, 100)
    repository.create_user("blame-2", "乙", now, 100)
    repository.create_blame_incident_card(
        "咖啡事故", "咖啡泼到了报表", ["咖啡", "报表"]
    )
    with factory.begin() as session:
        rank = session.scalar(select(RankRecord).where(RankRecord.sort_order == 1))
        rank.multiplayer_game_limit = 3

    _receive(service, "blame-start", "blame-1", "/甩锅游戏 2", now)
    assert "报名" in _latest_reply(factory)
    _receive(service, "blame-join", "blame-2", "/加入", now)
    start_reply = _latest_reply(factory)
    assert "咖啡事故" in start_reply
    assert "咖啡、报表" in start_reply

    summary = repository.blame_game_summary(now)
    holder = next(
        player for player in summary.players if player.seat_number == summary.current_holder_number
    )
    target = next(player for player in summary.players if player.platform_id != holder.platform_id)
    _receive(
        service,
        "blame-transfer",
        holder.platform_id,
        f"/甩锅 {target.seat_number} 咖啡弄脏了报表",
        now,
    )
    assert f"{target.display_name}" in _latest_reply(factory)
    assert "温热" in _latest_reply(factory)

    _receive(service, "blame-end", target.platform_id, "/结束游戏", now)
    assert "已结束" in _latest_reply(factory)


def _start_three_player_blame_group(service, repository, factory, now):
    from dzmm_bot.core.schema import RankRecord

    for platform_id, display_name in (("blame-a", "甲"), ("blame-b", "乙"), ("blame-c", "丙")):
        repository.create_user(platform_id, display_name, now, 100)
    repository.create_blame_incident_card(
        "咖啡事故", "咖啡泼到了报表", ["咖啡", "报表"]
    )
    with factory.begin() as session:
        rank = session.scalar(select(RankRecord).where(RankRecord.sort_order == 1))
        rank.multiplayer_game_limit = 3
    _receive(service, "blame-start-complete", "blame-a", "/甩锅游戏 3", now)
    _receive(service, "blame-join-b-complete", "blame-b", "/加入", now)
    _receive(service, "blame-join-c-complete", "blame-c", "/加入", now)


def test_generic_exit_hits_active_blame_game():
    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _start_three_player_blame_group(service, repository, factory, now)

    _receive(service, "blame-generic-exit", "blame-a", "/退出", now)

    assert "甲 主动退出并背锅" in _latest_reply(factory)


def test_blame_active_leave_complete_settlement_notice_includes_net_results():
    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _start_three_player_blame_group(service, repository, factory, now)

    _receive(service, "blame-leave-complete", "blame-a", "/退出甩锅", now)

    assert _latest_reply(factory) == (
        "【甩锅游戏】甲 主动退出并背锅，扣除 2 摸鱼币；"
        "乙、丙 获胜，每人获得 1 摸鱼币。"
    )


def test_blame_due_transfer_complete_settlement_notice_keeps_timeout_reason():
    from dzmm_bot.core.schema import BlameGamePlayerRecord, BlameGameRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _start_three_player_blame_group(service, repository, factory, now)
    with factory.begin() as session:
        game = session.scalar(select(BlameGameRecord))
        players = list(
            session.scalars(
                select(BlameGamePlayerRecord)
                .where(BlameGamePlayerRecord.game_id == game.id)
                .order_by(BlameGamePlayerRecord.seat_number)
            )
        )
        game.current_holder_user_id = players[0].user_id
        game.explosion_deadline = now.astimezone(BEIJING) + timedelta(seconds=30)
        game.turn_deadline = now.astimezone(BEIJING)

    _receive(
        service,
        "blame-transfer-due-complete",
        "blame-a",
        "/甩锅 2 咖啡碰到报表",
        now + timedelta(seconds=1),
    )

    assert _latest_reply(factory) == (
        "【甩锅游戏】操作超时，甲 背锅，扣除 2 摸鱼币；"
        "乙、丙 获胜，每人获得 1 摸鱼币。"
    )


def test_department_join_application_keeps_employee_in_default_department_until_approved():
    service, _, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "join", "platform-xiaoming", "/入职 小明", now)
    _receive(service, "department", "platform-xiaoming", "/加入部门 核心技术部", now)
    assert "已提交加入核心技术部申请" in _latest_reply(factory)

    _receive(service, "me", "platform-xiaoming", "/我", now)
    reply = _latest_reply(factory)
    assert "职位：实习生（LV1）" in reply
    assert "部门：未分配部门" in reply


def test_department_commands_apply_only_after_target_department_approval():
    from dzmm_bot.core.schema import DepartmentRecord, RankRecord, UserRecord

    service, _, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    with factory.begin() as session:
        target = session.scalar(
            select(DepartmentRecord).where(DepartmentRecord.name == "核心技术部")
        )
        rank_two = session.scalar(select(RankRecord).where(RankRecord.sort_order == 2))
        approver = session.scalar(select(UserRecord).where(UserRecord.platform_id == "u2"))
        assert target is not None
        assert rank_two is not None
        assert approver is not None
        approver.department_id = target.id
        approver.rank_id = rank_two.id

    _receive(service, "apply", "u1", "/加入部门 核心技术部", now)
    assert _latest_reply(factory) == "小明已提交加入核心技术部申请，等待该部门更高职位成员审批。"
    _receive(service, "list", "u2", "/部门申请列表", now)
    assert "1. 小明：未分配部门 → 核心技术部" in _latest_reply(factory)
    _receive(service, "approve", "u2", "/同意部门 1", now)
    assert _latest_reply(factory) == "小明已加入核心技术部。"
    _receive(service, "departments", "u1", "/部门", now)
    assert "核心技术部" in _latest_reply(factory)


def test_department_headcount_commands_show_totals_and_rank_counts_only():
    from dzmm_bot.core.schema import DepartmentRecord, RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    for platform_id, name in (
        ("mine", "查询人"),
        ("default", "未分配同事"),
        ("tech-1", "技术甲"),
        ("tech-2", "技术乙"),
    ):
        repository.create_user(platform_id, name, now, 0)
    with factory.begin() as session:
        tech = session.scalar(
            select(DepartmentRecord).where(DepartmentRecord.name == "核心技术部")
        )
        rank_two = session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 2)
        )
        assert tech is not None
        assert rank_two is not None
        for platform_id in ("mine", "tech-1", "tech-2"):
            session.scalar(
                select(UserRecord).where(UserRecord.platform_id == platform_id)
            ).department_id = tech.id
        session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "tech-2")
        ).rank_id = rank_two.id

    all_result = _receive(service, "all-counts", "mine", "/部门人数", now)
    all_reply = _replies_for(factory, all_result.message_id)[0]
    assert all_reply == (
        "【部门人数统计】\n"
        "未分配部门：共 1 人\n实习生：1 人\n"
        "最高职位者：实习生 未分配同事\n\n"
        "核心技术部：共 3 人\n实习生：2 人\n正式员工：1 人\n"
        "最高职位者：正式员工 技术乙"
    )
    assert "查询人" not in all_reply
    assert "技术甲" not in all_reply

    mine_result = _receive(
        service, "mine-counts", "mine", "/我的部门人数", now
    )
    assert _replies_for(factory, mine_result.message_id) == [
        "【我的部门人数统计】\n"
        "核心技术部：共 3 人\n实习生：2 人\n正式员工：1 人\n"
        "最高职位者：正式员工 技术乙"
    ]


def test_department_headcount_shows_all_tied_highest_rank_members():
    from dzmm_bot.core.schema import DepartmentRecord, RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    repository.create_user("viewer", "查询人", now, 0)
    repository.create_user("highest-1", "最高甲", now, 0)
    repository.create_user("highest-2", "最高乙", now, 0)
    with factory.begin() as session:
        tech = session.scalar(
            select(DepartmentRecord).where(DepartmentRecord.name == "核心技术部")
        )
        rank_two = session.scalar(
            select(RankRecord).where(RankRecord.sort_order == 2)
        )
        assert tech is not None
        assert rank_two is not None
        for platform_id in ("viewer", "highest-1", "highest-2"):
            session.scalar(
                select(UserRecord).where(UserRecord.platform_id == platform_id)
            ).department_id = tech.id
        for platform_id in ("highest-1", "highest-2"):
            session.scalar(
                select(UserRecord).where(UserRecord.platform_id == platform_id)
            ).rank_id = rank_two.id

    result = _receive(service, "duplicate-heads", "viewer", "/部门人数", now)
    reply = _replies_for(factory, result.message_id)[0]

    assert "最高职位者：正式员工 最高甲、最高乙" in reply
    assert "查询人 #" not in reply


@pytest.mark.parametrize("command", ("/部门人数", "/我的部门人数"))
def test_department_headcount_commands_require_employment(command):
    service, _, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    result = _receive(service, f"outsider-{command}", "outsider", command, now)

    assert _replies_for(factory, result.message_id) == [
        "请先用 /入职 名字 加入摸鱼公司。"
    ]


def test_department_headcount_command_honors_template_disable_and_help():
    service, repository, factory = _service()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
    repository.create_user("employee", "员工", now, 0)
    repository.set_reply_template("/部门人数", "shown", "统计如下：\n{部门统计}")

    customized = _receive(service, "custom-counts", "employee", "/部门人数", now)
    assert _replies_for(factory, customized.message_id)[0].startswith(
        "统计如下：\n未分配部门：共 1 人"
    )

    help_result = _receive(service, "department-help", "employee", "/帮助 部门", now)
    help_reply = _replies_for(factory, help_result.message_id)[0]
    assert "/部门人数：查看全部非空部门人数与职位分布" in help_reply
    assert "/我的部门人数：查看自己部门人数与职位分布" in help_reply

    repository.set_command_enabled("/部门人数", False)
    disabled = _receive(service, "disabled-counts", "employee", "/部门人数", now)
    assert _replies_for(factory, disabled.message_id) == []


def test_board_members_can_directly_change_departments_and_review_all_requests():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, _, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "board", "/入职 董事", now)
    with factory.begin() as session:
        board_rank = session.scalar(select(RankRecord).where(RankRecord.is_board.is_(True)))
        board = session.scalar(select(UserRecord).where(UserRecord.platform_id == "board"))
        assert board_rank is not None
        assert board is not None
        board.rank_id = board_rank.id

    _receive(service, "board-change", "board", "/加入部门 核心技术部", now)
    assert _latest_reply(factory) == "董事已直接加入核心技术部。"
    _receive(service, "board-switch", "board", "/切换部门 学院", now)
    assert _latest_reply(factory) == "董事已直接切换至学院。"
    _receive(service, "apply", "u1", "/加入部门 核心技术部", now)
    _receive(service, "list", "board", "/部门申请列表", now)
    assert "1. 小明：未分配部门 → 核心技术部" in _latest_reply(factory)


def test_promotion_request_list_and_numbered_approval():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    applicant = repository.find_user("u1")
    assert applicant is not None
    repository.record_balance_change(applicant.id, 80, "test", now)
    with factory.begin() as session:
        approver = session.scalar(select(UserRecord).where(UserRecord.platform_id == "u2"))
        rank_two = session.scalar(select(RankRecord).where(RankRecord.sort_order == 2))
        assert approver is not None
        assert rank_two is not None
        approver.rank_id = rank_two.id

    _receive(service, "apply", "u1", "/晋升", now)
    assert _latest_reply(factory) == "小明已提交晋升申请：实习生 → 正式员工，需要 80 摸鱼币。"

    _receive(service, "list", "u2", "/晋升申请列表", now)
    assert "1. 小明：实习生 → 正式员工（80 摸鱼币" in _latest_reply(factory)

    _receive(service, "approve", "u2", "/同意 1", now)
    assert _latest_reply(factory) == "小明已晋升为正式员工，扣除 80 摸鱼币。"


def test_positions_and_reject_promotion():
    from dzmm_bot.core.schema import RankRecord, UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    applicant = repository.find_user("u1")
    assert applicant is not None
    repository.record_balance_change(applicant.id, 80, "test", now)
    with factory.begin() as session:
        approver = session.scalar(select(UserRecord).where(UserRecord.platform_id == "u2"))
        rank_two = session.scalar(select(RankRecord).where(RankRecord.sort_order == 2))
        assert approver is not None
        assert rank_two is not None
        approver.rank_id = rank_two.id

    _receive(service, "positions", "u1", "/职位", now)
    assert "正式员工（LV2）：晋升价格 80 摸鱼币" in _latest_reply(factory)
    _receive(service, "apply", "u1", "/晋升", now)
    _receive(service, "reject", "u2", "/拒绝 1", now)
    assert _latest_reply(factory) == "已拒绝小明的晋升申请。"
    assert repository.find_user("u1").balance == 80


def test_promotion_reply_uses_the_next_enabled_rank():
    from dzmm_bot.core.schema import RankRecord

    service, _, factory = _service()
    now = datetime(2026, 8, 7, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    with factory.begin() as session:
        rank_two = session.scalar(select(RankRecord).where(RankRecord.sort_order == 2))
        assert rank_two is not None
        rank_two.enabled = False

    requested = _receive(service, "promotion", "u1", "/晋升", now)

    assert "实习生 → 小组长" in _replies_for(factory, requested.message_id)[0]


def test_random_event_commands_join_count_rounds_and_settle_on_exit():
    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository.create_random_event_scene(
        "茶水间",
        "咖啡机突然发出一声巨响。",
        ["咖啡机突然发出一声巨响。"],
        4,
        2,
        [("员工", 2)],
    )
    repository.set_random_event_settings(
        ["10:00"], "可选身份：{可选身份}；截止：{报名截止分钟}", 15, 5
    )
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    assert "可选身份：员工 × 2；截止：15" in _latest_reply(factory)

    _receive(service, "event-join-1", "u1", "/加入 员工", now)
    assert _latest_reply(factory) == "小明 已加入随机事件，担任 员工。\n剩余可选身份：员工 × 1"
    _receive(service, "event-join-2", "u2", "/加入 员工", now)
    _receive(service, "round-1", "u1", "第一句", now)
    _receive(service, "round-2", "u1", "第二句", now)
    _receive(service, "event-leave", "u1", "/退出", now)

    assert "领取 4 摸鱼币" in _latest_reply(factory)


@pytest.mark.parametrize("seat_count", [2, 1])
def test_random_event_replies_when_blocking_checkin_but_keeps_required_event_actions(seat_count):
    from dzmm_bot.core.schema import UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository.create_random_event_scene(
        "茶水间", "咖啡机突然发出一声巨响。", ["正式开始。"], 4, 1, [("员工", seat_count)]
    )
    repository.set_random_event_settings(["10:00"], "可选身份：{可选身份}", 15, 5)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)

    if seat_count == 1:
        _receive(service, "start-event", "u2", "/加入 员工", now)

    checkin = _receive(service, f"checkin-{seat_count}", "u1", "/打卡", now)
    assert _replies_for(factory, checkin.message_id) == [
        "当前有随机事件发生，监事不会处理。"
    ]
    with factory() as session:
        employee = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "u1")
        )
        assert employee.balance == 0

    if seat_count == 2:
        joined = _receive(service, "event-join", "u1", "/加入 员工", now)
        assert "已加入随机事件" in _replies_for(factory, joined.message_id)[0]


@pytest.mark.parametrize("seat_count", [2, 1])
def test_random_event_executes_checkin_when_admin_explicitly_allows_it(seat_count):
    from dzmm_bot.core.schema import UserRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository.create_random_event_scene(
        "茶水间", "咖啡机突然发出一声巨响。", ["正式开始。"], 4, 1, [("员工", seat_count)]
    )
    repository.set_random_event_settings(
        ["10:00"],
        "可选身份：{可选身份}",
        15,
        5,
        signup_allowed_commands=["/打卡"],
        in_progress_allowed_commands=["/打卡"],
        blocked_message="当前有随机事件发生，监事不会处理。",
    )
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)
    if seat_count == 1:
        assert repository.join_random_event("u2", "员工", now) == "started"

    checkin = _receive(service, f"checkin-allowed-{seat_count}", "u1", "/打卡", now)
    assert _replies_for(factory, checkin.message_id) == [
        "打卡成功，领取 5 摸鱼币。当前余额：5 摸鱼币。"
    ]
    with factory() as session:
        employee = session.scalar(
            select(UserRecord).where(UserRecord.platform_id == "u1")
        )
        assert employee.balance == 5


def test_random_event_uses_the_configured_block_message():
    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    repository.create_random_event_scene(
        "茶水间", "咖啡机突然发出一声巨响。", ["正式开始。"], 4, 1, [("员工", 2)]
    )
    repository.set_random_event_settings(
        ["10:00"],
        "可选身份：{可选身份}",
        15,
        5,
        blocked_message="活动进行中，监事暂不处理。",
    )
    _receive(service, "join", "u1", "/入职 小明", now)
    repository.schedule_random_events(now)
    repository.run_random_event_jobs(now)

    blocked = _receive(service, "blocked", "u1", "/打卡", now)

    assert _replies_for(factory, blocked.message_id) == ["活动进行中，监事暂不处理。"]


def test_hide_and_seek_short_commands_list_places_and_patrol(monkeypatch):
    service, _, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    monkeypatch.setattr("dzmm_bot.core.repository.randbelow", lambda _: 0)

    _receive(service, "start", "u1", "/开始摸鱼躲藏", now)
    started_reply = _latest_reply(factory)
    chosen = _receive(service, "choose", "u1", "/躲 7", now)
    finished_replies = _replies_for(factory, chosen.message_id)

    assert "1（" in started_reply and "7（" in started_reply
    assert "开局不扣除" in started_reply
    assert len(finished_replies) == 2
    assert "【系统巡查·第一轮】巡查" in finished_replies[0]
    assert "奇怪，人躲哪里去了......." in finished_replies[0]
    assert "【系统巡查·第二轮】巡查" in finished_replies[1]
    assert "躲藏成功" in finished_replies[1]


def test_hide_and_seek_found_template_receives_frozen_penalty_amount(monkeypatch):
    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    repository.set_reply_template(
        "/摸鱼躲猫猫",
        "found_first_round",
        "{昵称}，扣除 {惩罚金额} {货币}，当前余额 {余额} {货币}。",
    )
    monkeypatch.setattr("dzmm_bot.core.repository.randbelow", lambda _: 0)

    _receive(service, "start", "u1", "/开始摸鱼躲藏", now)
    _receive(service, "choose", "u1", "/躲 1", now)

    assert _latest_reply(factory) == "小明，扣除 1 摸鱼币，当前余额 -1 摸鱼币。"


def test_hide_and_seek_first_round_found_sends_only_one_reply(monkeypatch):
    service, _, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    monkeypatch.setattr("dzmm_bot.core.repository.randbelow", lambda _: 0)

    _receive(service, "start", "u1", "/开始摸鱼躲藏", now)
    chosen = _receive(service, "choose", "u1", "/躲 1", now)
    replies = _replies_for(factory, chosen.message_id)

    assert len(replies) == 1
    assert "【系统巡查·第一轮】巡查" in replies[0]
    assert "【系统巡查·第二轮】" not in replies[0]


def test_memory_assessment_single_uses_continue_and_cash_out_commands(monkeypatch):
    from dzmm_bot.core.schema import MemoryAssessmentRoundRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    monkeypatch.setattr("dzmm_bot.core.repository.choice", lambda _: "A")

    _receive(service, "start", "u1", "/记忆考核", now)
    with factory() as session:
        round_record = session.scalar(select(MemoryAssessmentRoundRecord))
    _receive(service, "too-early", "u1", "/答案 AAAAA", now)
    repository.mark_memory_assessment_round_recalled(round_record.id, now)
    _receive(service, "answer", "u1", "/答案 AAAAA", now)
    _receive(service, "cash-out", "u1", "/收手", now)

    assert _latest_reply(factory) == "小明 收手成功，获得 1 摸鱼币。当前余额：1 摸鱼币。"


def test_memory_assessment_only_accepts_answers_prefixed_with_answer_command(monkeypatch):
    from dzmm_bot.core.schema import MemoryAssessmentRoundRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    monkeypatch.setattr("dzmm_bot.core.repository.choice", lambda _: "A")

    _receive(service, "start", "u1", "/记忆考核", now)
    with factory() as session:
        round_record = session.scalar(select(MemoryAssessmentRoundRecord))
    repository.mark_memory_assessment_round_recalled(round_record.id, now)

    casual = _receive(service, "casual", "u1", "今天正常聊天", now)
    with factory() as session:
        assert session.get(MemoryAssessmentRoundRecord, round_record.id).state == "awaiting_answer"
    assert _replies_for(factory, casual.message_id) == []

    answer = _receive(service, "answer", "u1", "/答案 AAAAA", now)

    assert _replies_for(factory, answer.message_id) == [
        "第 1 级通过。现在收手可获得 1 摸鱼币，或发送 /继续 挑战下一层。"
    ]


def test_memory_assessment_prompt_is_queued_for_automatic_recall(monkeypatch):
    from dzmm_bot.core.schema import MemoryAssessmentRoundRecord, OutboundRecord

    service, _, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    monkeypatch.setattr("dzmm_bot.core.repository.choice", lambda _: "A")

    _receive(service, "start", "u1", "/记忆考核", now)

    with factory() as session:
        outbound = session.scalar(
            select(OutboundRecord).where(OutboundRecord.recall_after_seconds.is_not(None))
        )
        round_record = session.scalar(select(MemoryAssessmentRoundRecord))
    assert outbound.recall_after_seconds == 3
    assert round_record.outbound_message_id == outbound.id


def test_memory_assessment_duel_is_joined_with_plain_join_command(monkeypatch):
    from dzmm_bot.core.schema import MemoryAssessmentRoundRecord

    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join-1", "u1", "/入职 小明", now)
    _receive(service, "join-2", "u2", "/入职 小红", now)
    monkeypatch.setattr("dzmm_bot.core.repository.choice", lambda _: "A")

    _receive(service, "duel", "u1", "/记忆考核 对战", now)
    _receive(service, "duel-join", "u2", "/加入", now)
    with factory() as session:
        round_record = session.scalar(select(MemoryAssessmentRoundRecord))
    repository.mark_memory_assessment_round_recalled(round_record.id, now)
    _receive(service, "answer", "u1", "/答案 " + "A" * 13, now)

    assert "小明 最先答对，赢得奖池 10 摸鱼币。" in _latest_reply(factory)


def test_memory_assessment_duel_replies_when_multiplayer_game_is_active():
    """Fails if a multiplayer conflict crashes inbound command handling."""
    service, repository, factory = _service()
    now = datetime(2026, 8, 6, 10, 0, tzinfo=BEIJING)
    _receive(service, "join", "u1", "/入职 小明", now)
    repository.upsert_direct_chats([("u1", "direct-u1")], now)
    assert repository.start_undercover_signup("u1", 4, now).status == "signup_started"

    _receive(service, "duel", "u1", "/记忆考核 对战", now)

    assert _latest_reply(factory) == "当前已有多人玩法进行中，暂不能发起记忆考核对战。"


def test_disabled_command_does_not_reply_or_change_data():
    from dzmm_bot.core.schema import UserRecord

    service, repository, factory = _service()
    repository.set_command_enabled("/入职", False)

    _receive(
        service,
        "message-1",
        "platform-xiaoming",
        "/入职 小明",
        datetime(2026, 8, 5, 2, 0, tzinfo=UTC),
    )

    with factory() as session:
        assert session.scalar(select(UserRecord)) is None
    assert _latest_reply(factory) is None


def test_custom_checkin_template_receives_current_balance_and_reward():
    """Fails if a successful check-in ignores the administrator's template."""
    service, repository, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    repository.set_reply_template(
        "/打卡", "checked_in", "{昵称} 今日 +{打卡奖励}，余额 {余额}"
    )

    _receive(service, "join", "platform-xiaoming", "/入职 小明", received_at)
    _receive(service, "checkin", "platform-xiaoming", "/打卡", received_at)

    assert _latest_reply(factory) == "小明 今日 +5，余额 5"


def test_template_date_uses_the_beijing_calendar_date():
    service, repository, factory = _service()
    repository.set_reply_template("/余额", "shown", "{日期} {昵称}")

    _receive(
        service,
        "join",
        "platform-xiaoming",
        "/入职 小明",
        datetime(2026, 8, 5, 15, 59, tzinfo=UTC),
    )
    _receive(
        service,
        "balance",
        "platform-xiaoming",
        "/余额",
        datetime(2026, 8, 5, 16, 1, tzinfo=UTC),
    )

    assert _latest_reply(factory) == "2026-08-06 小明"


def test_invalid_persisted_template_falls_back_after_checkin_awards_balance():
    from dzmm_bot.core.schema import CommandReplyTemplateRecord, UserRecord

    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    _receive(service, "join", "platform-xiaoming", "/入职 小明", received_at)

    with factory() as session:
        template = session.scalar(
            select(CommandReplyTemplateRecord).where(
                CommandReplyTemplateRecord.command == "/打卡",
                CommandReplyTemplateRecord.scenario == "checked_in",
            )
        )
        template.template = "{商店列表}"
        session.commit()

    _receive(service, "checkin", "platform-xiaoming", "/打卡", received_at)

    assert _latest_reply(factory) == "打卡成功，领取 5 摸鱼币。当前余额：5 摸鱼币。"
    with factory() as session:
        assert session.scalar(select(UserRecord)).balance == 5


def test_help_lists_only_enabled_commands_and_uses_its_template():
    """Fails if help does not reflect the command library or its template."""
    service, repository, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)
    repository.set_command_enabled("/打卡", False)
    repository.set_reply_template("/帮助", "shown", "可用：\n{指令列表}")

    _receive(service, "help", "platform-xiaoming", "/帮助 基础", received_at)

    assert "【基础与资产】" in _latest_reply(factory)
    assert "/打卡" not in _latest_reply(factory)


def test_help_shows_category_entrypoints_instead_of_all_commands():
    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "help", "platform-xiaoming", "/帮助", received_at)

    reply = _latest_reply(factory)
    assert "发送 /帮助 分类，查看详细用法：" in reply
    assert "/帮助 基础" in reply
    assert "/帮助 游戏" in reply
    assert "/帮助 随机事件" in reply
    assert "/帮助 职位" in reply
    assert "/帮助 部门" in reply
    assert "/同意部门" not in reply


def test_help_random_event_topic_lists_submission_entrypoints():
    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "help-random-event", "platform-xiaoming", "/帮助 随机事件", received_at)

    reply = _latest_reply(factory)
    assert "/投稿 随机事件" in reply
    assert "/我的投稿" in reply
    assert "/撤回投稿 编号" in reply
    assert "/打赏 员工名称 金额" in reply
    assert "真实转移" in reply


def test_help_game_topic_links_to_each_game_guide():
    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "help-games", "platform-xiaoming", "/帮助 游戏", received_at)

    reply = _latest_reply(factory)
    assert "【游戏玩法】" in reply
    assert "/帮助 摸鱼躲藏" in reply
    assert "/帮助 记忆考核" in reply
    assert "/帮助 谁是卧底" in reply
    assert "/帮助 蹦蹦数字炸弹" in reply
    for command in (
        "/蹦蹦数字炸弹", "/加入", "/开始", "/报数 数字",
        "/跳过 编号", "/继续", "/结束游戏",
    ):
        assert command in reply
    assert "3-10" not in reply
    assert "3 至 10" not in reply
    assert "无操作释放" not in reply


def test_help_number_bomb_topic_shows_group_and_private_commands():
    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(
        service,
        "help-number-bomb",
        "platform-xiaoming",
        "/帮助 蹦蹦数字炸弹",
        received_at,
    )

    reply = _latest_reply(factory)
    assert "【蹦蹦数字炸弹】" in reply
    for command in (
        "/蹦蹦数字炸弹", "/加入", "/开始", "/报数 数字",
        "/跳过 编号", "/退出", "/继续", "/结束游戏",
    ):
        assert command in reply
    assert "人数" not in reply
    assert "3-10" not in reply
    assert "3 至 10" not in reply
    assert "无操作释放" not in reply


def test_help_hide_and_seek_topic_shows_start_and_followup_syntax():
    service, _, factory = _service()
    received_at = datetime(2026, 8, 5, 2, 0, tzinfo=UTC)

    _receive(service, "help-hide-and-seek", "platform-xiaoming", "/帮助 摸鱼躲藏", received_at)

    reply = _latest_reply(factory)
    assert "【摸鱼躲藏】" in reply
    assert "/开始摸鱼躲藏" in reply
    assert "/躲 序号" in reply
    assert "/摸鱼躲猫猫" not in reply
