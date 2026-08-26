import httpx
import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core import performance
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.repository import CoreRepository
from dzmm_bot.core.schema import (
    Base,
    GroupChatRecord,
    OutboundRecord,
    PerformanceMessageRecord,
    UserRecord,
)
from dzmm_bot.core.service import CoreService
from dzmm_bot.runtime.contracts import InboundMessage
from dzmm_bot.runtime.contracts import MessageReference


HTTPS_URL = "https://cdn.example/cover"


def _validator(body: bytes, status_code: int = 200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    return performance.HttpCoverImageValidator(
        httpx.Client(transport=httpx.MockTransport(handler), timeout=5)
    )


@pytest.mark.parametrize(
    ("body", "mime_type"),
    [
        (b"\x89PNG\r\n\x1a\n" + b"x" * 8, "image/png"),
        (b"\xff\xd8\xff" + b"x" * 8, "image/jpeg"),
        (b"RIFF\x0c\x00\x00\x00WEBP" + b"x" * 4, "image/webp"),
    ],
)
def test_cover_validator_accepts_supported_magic(body, mime_type) -> None:
    result = _validator(body).validate(HTTPS_URL)

    assert result.mime_type == mime_type
    assert result.byte_size == len(body)


def test_cover_validator_rejects_unsupported_magic() -> None:
    with pytest.raises(ValueError, match="JPEG、PNG、WebP"):
        _validator(b"not-an-image").validate(HTTPS_URL)


def test_cover_validator_stops_after_ten_mib() -> None:
    body = b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)

    with pytest.raises(ValueError, match="10MB"):
        _validator(body).validate(HTTPS_URL)


def test_cover_validator_rejects_redirects() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        _validator(b"", status_code=302).validate(HTTPS_URL)


def test_cover_validator_requires_https() -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _validator(b"anything").validate("http://cdn.example/cover")


BEIJING = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def command_context():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    repository = CoreRepository(factory)
    now = datetime(2026, 8, 26, 12, 0, tzinfo=BEIJING)
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=performance-room", now
    )
    with factory.begin() as session:
        session.get(GroupChatRecord, group.id).performances_enabled = True
    repository.create_user("owner", "发起人", now, 100)
    repository.create_user("actor", "演员甲", now, 100)
    repository.create_user("observer", "观众甲", now, 100)
    repository.create_user("fan", "观众乙", now, 100)
    repository.upsert_direct_chats([("owner", "direct-owner")], now)
    service = CoreService(repository, GroupCommandHandler(repository))
    return service, repository, group, now


def _receive(
    service,
    sender,
    content,
    now,
    *,
    room,
    source="group",
    platform_message_id=None,
    **kwargs,
):
    return service.receive_inbound(
        InboundMessage(
            platform_message_id or str(uuid4()),
            sender,
            content,
            now,
            source_type=source,
            chatroom_id=room,
            **kwargs,
        )
    )


def _claim(repository, room, now):
    return repository.claim_outbound(
        "worker", now, 30, required_delivery_key=room
    )


def _confirm(repository, outbound, now):
    assert repository.confirm_sent(
        outbound.id, "worker", outbound.lease_token, str(uuid4()), now
    )


def _complete_command_draft(repository, group, now):
    repository.begin_performance_draft("owner", group.id, now)
    result = None
    for value in (
        "夜航",
        "夜间公演",
        (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
        "/跳过",
        "/确认",
    ):
        result = repository.consume_performance_draft_input(
            "owner", uuid4(), now, text=value
        )
    return result


def test_group_entry_starts_private_guide(command_context) -> None:
    service, repository, group, now = command_context

    _receive(service, "owner", "/预约公演", now, room=group.chatroom_id)

    group_reply = _claim(repository, group.chatroom_id, now)
    _confirm(repository, group_reply, now)
    direct_reply = _claim(repository, "direct-owner", now)
    assert group_reply.text == "公演预约向导已通过私聊发送。"
    assert direct_reply.text == "请发送公演标题（1–50字）。"


def test_active_performance_draft_has_private_routing_priority(command_context) -> None:
    service, repository, group, now = command_context
    _receive(service, "owner", "/预约公演", now, room=group.chatroom_id)
    _confirm(repository, _claim(repository, group.chatroom_id, now), now)
    _confirm(repository, _claim(repository, "direct-owner", now), now)
    values = (
        ("夜航", "请发送公演简介（1–500字）。"),
        ("夜间公演", "请发送公演时间，格式：2026/12/01-12:00:00。"),
        (
            (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
            "请发送参演人员名称，多人请用顿号分隔（1–30人）。",
        ),
        ("演员甲", "请发送公演封面图片，或发送 /跳过。"),
        ("/跳过", "预约信息已填写完成，发送 /确认 提交审核。"),
        ("/确认", "公演预约已提交审核。"),
    )
    for index, (content, expected) in enumerate(values, 1):
        _receive(
            service,
            "owner",
            content,
            now + timedelta(seconds=index),
            room="direct-owner",
            source="direct",
        )
        reply = _claim(repository, "direct-owner", now + timedelta(seconds=index))
        assert reply.text == expected
        _confirm(repository, reply, now + timedelta(seconds=index))

    assert repository.own_performance("owner", now).state == "pending_review"


def test_performance_draft_does_not_consume_other_direct_commands(
    command_context,
) -> None:
    service, repository, group, now = command_context
    repository.begin_performance_draft("owner", group.id, now)

    _receive(
        service,
        "owner",
        "/余额",
        now,
        room="direct-owner",
        source="direct",
    )

    reply = _claim(repository, "direct-owner", now)
    assert "当前余额" in reply.text
    assert repository.performance_draft_step("owner", now) == "title"


def test_my_performance_shows_rejection_reason(command_context) -> None:
    service, repository, group, now = command_context
    submitted = _complete_command_draft(repository, group, now)
    repository.review_performance(
        submitted.reservation.id, False, "admin:a", now, "请补充简介"
    )
    _confirm(repository, _claim(repository, "direct-owner", now), now)

    _receive(
        service,
        "owner",
        "/我的公演预约",
        now,
        room="direct-owner",
        source="direct",
    )

    reply = _claim(repository, "direct-owner", now)
    assert "状态：rejected" in reply.text
    assert "请补充简介" in reply.text


def test_private_image_advances_cover_step(command_context) -> None:
    class Validator:
        def validate(self, url):
            return performance.ValidatedCover(url, "image/webp", 123)

    _, repository, group, now = command_context
    service = CoreService(
        repository,
        GroupCommandHandler(repository),
        cover_image_validator=Validator(),
    )
    repository.begin_performance_draft("owner", group.id, now)
    for value in (
        "夜航",
        "夜间公演",
        (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
    ):
        repository.consume_performance_draft_input(
            "owner", uuid4(), now, text=value
        )

    _receive(
        service,
        "owner",
        "[图片]",
        now,
        room="direct-owner",
        source="direct",
        content_type="image",
        image_url="https://cdn.example/cover.webp",
        image_alt="封面",
    )

    reply = _claim(repository, "direct-owner", now)
    assert reply.text == "预约信息已填写完成，发送 /确认 提交审核。"


def test_performance_requires_direct_room(command_context) -> None:
    service, repository, group, now = command_context
    repository.create_user("no-room", "无私聊", now, 100)

    _receive(service, "no-room", "/预约公演", now, room=group.chatroom_id)

    reply = _claim(repository, group.chatroom_id, now)
    assert reply.text == "请先私聊总监事发送任意消息，再回群预约公演。"


def test_owner_can_request_postponement_in_direct_chat(command_context) -> None:
    service, repository, group, now = command_context
    repository.begin_performance_draft("owner", group.id, now)
    for value in (
        "夜航",
        "夜间公演",
        (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
        "/跳过",
        "/确认",
    ):
        result = repository.consume_performance_draft_input(
            "owner", uuid4(), now, text=value
        )
    repository.review_performance(result.reservation.id, True, "admin:a", now)
    _confirm(repository, _claim(repository, "direct-owner", now), now)

    _receive(
        service,
        "owner",
        "/延期 30m",
        now,
        room="direct-owner",
        source="direct",
    )

    reply = _claim(repository, "direct-owner", now)
    assert "延期 30 分钟" in reply.text
    assert "等待管理员审核" in reply.text


def _open_performance(command_context):
    service, repository, group, now = command_context
    repository.begin_performance_draft("owner", group.id, now)
    for value in (
        "夜航",
        "夜间公演",
        (now + timedelta(days=1)).strftime("%Y/%m/%d-%H:%M:%S"),
        "演员甲",
        "/跳过",
        "/确认",
    ):
        result = repository.consume_performance_draft_input(
            "owner", uuid4(), now, text=value
        )
    repository.review_performance(result.reservation.id, True, "admin:a", now)
    stage_time = now + timedelta(days=1)
    repository.run_performance_jobs(stage_time)
    with repository._session_factory.begin() as session:
        session.execute(delete(OutboundRecord))
    return service, repository, group, stage_time


def test_performance_participant_line_is_recorded_without_reply(command_context) -> None:
    service, repository, group, stage_time = _open_performance(command_context)

    _receive(service, "actor", "第一幕开始。", stage_time, room=group.chatroom_id)

    assert _claim(repository, group.chatroom_id, stage_time) is None
    with repository._session_factory() as session:
        assert session.scalar(select(func.count(PerformanceMessageRecord.id))) == 1


def test_performance_observer_must_use_parentheses(command_context) -> None:
    service, repository, group, stage_time = _open_performance(command_context)

    _receive(service, "observer", "我也想说话", stage_time, room=group.chatroom_id)
    warning = _claim(repository, group.chatroom_id, stage_time)
    assert warning.text == "公演正在进行，请使用括号进行场外交流。"
    _confirm(repository, warning, stage_time)
    _receive(
        service,
        "observer",
        "（场外：好耶）",
        stage_time + timedelta(seconds=1),
        room=group.chatroom_id,
    )
    assert _claim(repository, group.chatroom_id, stage_time) is None


def test_participant_end_opens_tipping(command_context) -> None:
    service, repository, group, stage_time = _open_performance(command_context)

    _receive(service, "actor", "/end", stage_time, room=group.chatroom_id)

    reply = _claim(repository, group.chatroom_id, stage_time)
    assert "180 秒打赏" in reply.text
    assert repository.performance_blocks_new_game(group.id) is True


def test_performance_tip_moves_real_balance(command_context) -> None:
    service, repository, group, stage_time = _open_performance(command_context)
    _receive(
        service,
        "actor",
        "第一幕开始。",
        stage_time,
        room=group.chatroom_id,
        platform_message_id="performance-line-1",
    )
    _receive(service, "actor", "/end", stage_time, room=group.chatroom_id)
    _confirm(repository, _claim(repository, group.chatroom_id, stage_time), stage_time)

    _receive(
        service,
        "fan",
        "/打赏 演员甲 5",
        stage_time + timedelta(seconds=1),
        room=group.chatroom_id,
    )

    reply = _claim(repository, group.chatroom_id, stage_time)
    assert "观众乙" in reply.text
    assert "演员甲" in reply.text
    assert "5" in reply.text
    with repository._session_factory() as session:
        assert session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == "fan")
        ) == 95
        assert session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == "actor")
        ) == 105


def test_performance_tip_can_resolve_reply_target(command_context) -> None:
    service, repository, group, stage_time = _open_performance(command_context)
    _receive(
        service,
        "actor",
        "第一幕开始。",
        stage_time,
        room=group.chatroom_id,
        platform_message_id="performance-line-2",
    )
    _receive(service, "actor", "/end", stage_time, room=group.chatroom_id)
    _confirm(repository, _claim(repository, group.chatroom_id, stage_time), stage_time)

    _receive(
        service,
        "fan",
        "/打赏 6",
        stage_time + timedelta(seconds=1),
        room=group.chatroom_id,
        reference=MessageReference(
            "performance-line-2", "actor", "text", text="第一幕开始。"
        ),
    )

    reply = _claim(repository, group.chatroom_id, stage_time)
    assert "演员甲" in reply.text
    with repository._session_factory() as session:
        assert session.scalar(
            select(UserRecord.balance).where(UserRecord.platform_id == "actor")
        ) == 106


def test_performance_help_lists_all_player_commands(command_context) -> None:
    service, repository, group, now = command_context

    _receive(service, "owner", "/帮助 公演", now, room=group.chatroom_id)

    text = _claim(repository, group.chatroom_id, now).text
    for expected in (
        "/预约公演",
        "/公演日程",
        "/我的公演预约",
        "/取消公演预约",
        "/延期 30m",
        "/end",
        "回复参演人员本场消息发送 /打赏 金额",
    ):
        assert expected in text
