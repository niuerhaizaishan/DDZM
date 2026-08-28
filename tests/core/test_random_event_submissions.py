from datetime import UTC, datetime, timedelta
from copy import deepcopy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from dzmm_bot.core.repository import (
    CoreRepository,
    RandomEventSubmissionDailyLimitError,
)
from dzmm_bot.core.random_event_submissions import RandomEventSubmissionHandler
from dzmm_bot.core.commands import GroupCommandHandler
from dzmm_bot.core.service import CoreService
from dzmm_bot.core.schema import InboundRecord, OutboundRecord
from dzmm_bot.runtime.contracts import InboundMessage
from sqlalchemy import select
from dzmm_bot.core.schema import Base


NOW = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def repository():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return CoreRepository(sessionmaker(engine, expire_on_commit=False))


def _employee(repository, platform_id="employee-1"):
    repository.create_user(platform_id, f"投稿人-{platform_id}", NOW, 0)
    repository.upsert_direct_chats([(platform_id, f"direct-{platform_id}")], NOW)


def _pending_submission(repository, platform_id="employee-1"):
    _employee(repository, platform_id)
    _preview_submission(repository, platform_id)
    return repository.confirm_random_event_submission(platform_id, NOW)


def _preview_submission(repository, platform_id="employee-1", now=NOW):
    draft = repository.start_random_event_submission(platform_id, now).submission
    return repository.replace_random_event_submission_content(
        draft.id,
        {
            "scene_name": f"失踪的咖啡-{platform_id}",
            "signup_text": "茶水间出事了，快来报名。",
            "participant_count": 3,
            "roles": [
                {"role": "调查员", "capacity": 2},
                {"role": "嫌疑人", "capacity": 1},
            ],
            "events": [
                {"name": "现场", "opening_text": "{调查员}发现了空杯。"}
            ],
        },
        "preview",
        now,
    )


def test_submission_start_requires_employee_and_known_direct_chat(repository):
    assert repository.start_random_event_submission("outsider", NOW).status == "not_joined"

    repository.create_user("employee-1", "投稿人", NOW, 0)
    assert repository.start_random_event_submission("employee-1", NOW).status == "no_direct_chat"


def test_submission_start_resumes_the_same_draft(repository):
    _employee(repository)

    first = repository.start_random_event_submission("employee-1", NOW)
    resumed = repository.start_random_event_submission(
        "employee-1", NOW + timedelta(minutes=1)
    )

    assert first.status == "started"
    assert resumed.status == "resumed"
    assert resumed.submission.id == first.submission.id
    assert resumed.submission.current_step == "scene_name"
    assert resumed.direct_chatroom_id == "direct-employee-1"


def test_submission_start_reports_expired_draft_and_creates_a_new_one(repository):
    _employee(repository)
    first = repository.start_random_event_submission("employee-1", NOW).submission

    restarted = repository.start_random_event_submission(
        "employee-1", NOW + timedelta(minutes=31)
    )

    assert restarted.status == "expired_started"
    assert restarted.submission.id != first.id
    assert repository.get_random_event_submission(first.id).status == "expired"


def test_submission_confirmation_locks_configured_numeric_values(repository):
    _employee(repository)
    started = repository.start_random_event_submission("employee-1", NOW)
    repository.replace_random_event_submission_content(
        started.submission.id,
        {
            "scene_name": "失踪的咖啡",
            "signup_text": "茶水间出事了，快来报名。",
            "participant_count": 3,
            "roles": [
                {"role": "调查员", "capacity": 2},
                {"role": "嫌疑人", "capacity": 1},
            ],
            "events": [
                {"name": "现场", "opening_text": "{调查员}发现了空杯。"}
            ],
        },
        "preview",
        NOW,
    )

    submitted = repository.confirm_random_event_submission("employee-1", NOW)

    assert submitted.status == "pending"
    assert submitted.target_rounds == 10
    assert submitted.event_reward == 6
    assert submitted.approval_reward == 10
    assert repository.start_random_event_submission(
        "employee-1", NOW + timedelta(minutes=1)
    ).status == "started"
    with pytest.raises(ValueError, match="待审核"):
        repository.confirm_random_event_submission("employee-1", NOW)


def test_submission_daily_limit_preserves_draft_and_resets_next_beijing_day(
    repository,
):
    first = _pending_submission(repository)
    repository.withdraw_random_event_submission(
        "employee-1", first.number, NOW + timedelta(minutes=1)
    )
    second = _preview_submission(
        repository, now=NOW + timedelta(minutes=2)
    )

    with pytest.raises(RandomEventSubmissionDailyLimitError):
        repository.confirm_random_event_submission(
            "employee-1", NOW + timedelta(hours=1)
        )

    unchanged = repository.get_random_event_submission(second.id)
    assert unchanged.current_step == "preview"
    assert unchanged.content == second.content
    assert unchanged.expires_at == second.expires_at

    repository.cancel_random_event_submission(
        "employee-1", NOW + timedelta(hours=1)
    )
    _preview_submission(repository, now=NOW + timedelta(days=1))

    submitted = repository.confirm_random_event_submission(
        "employee-1", NOW + timedelta(days=1)
    )

    assert submitted.status == "pending"


def test_submission_daily_limit_resets_at_beijing_midnight(repository):
    before_midnight = datetime(2026, 8, 15, 15, 59, 59, tzinfo=UTC)
    midnight = before_midnight + timedelta(seconds=1)
    _employee(repository)
    _preview_submission(repository, now=before_midnight)
    first = repository.confirm_random_event_submission(
        "employee-1", before_midnight
    )
    repository.withdraw_random_event_submission(
        "employee-1", first.number, before_midnight
    )

    _preview_submission(repository, now=midnight)
    submitted = repository.confirm_random_event_submission(
        "employee-1", midnight
    )

    assert submitted.status == "pending"


@pytest.mark.parametrize("review_state", ["approved", "rejected"])
def test_submission_daily_limit_survives_terminal_review_state(
    repository, review_state
):
    first = _pending_submission(repository)
    if review_state == "approved":
        repository.approve_random_event_submission(
            first.id, "管理员甲", NOW + timedelta(minutes=1)
        )
    else:
        repository.reject_random_event_submission(
            first.id,
            "管理员甲",
            "身份设计不完整",
            NOW + timedelta(minutes=1),
        )
    _preview_submission(repository, now=NOW + timedelta(minutes=2))

    with pytest.raises(RandomEventSubmissionDailyLimitError):
        repository.confirm_random_event_submission(
            "employee-1", NOW + timedelta(hours=1)
        )


def test_submission_daily_limit_is_independent_for_different_employees(repository):
    first = _pending_submission(repository, "employee-1")
    second = _pending_submission(repository, "employee-2")

    assert first.status == "pending"
    assert second.status == "pending"


def test_submission_accepts_one_role_per_configured_participant(repository):
    """Fails if valid single-seat submissions remain capped at 20 identities."""
    _employee(repository)
    draft = repository.start_random_event_submission(
        "employee-1", NOW
    ).submission
    repository.replace_random_event_submission_content(
        draft.id,
        {
            "scene_name": "二十一人事件",
            "signup_text": "需要二十一名员工参加。",
            "participant_count": 21,
            "roles": [
                {"role": f"身份{index}", "capacity": 1}
                for index in range(1, 22)
            ],
            "events": [
                {"name": "开场", "opening_text": "{身份1}第一个抵达现场。"}
            ],
        },
        "preview",
        NOW,
    )

    submitted = repository.confirm_random_event_submission("employee-1", NOW)

    assert submitted.status == "pending"
    assert len(submitted.content["roles"]) == 21
    assert all(role["capacity"] == 1 for role in submitted.content["roles"])


def test_inactive_submission_draft_expires_without_affecting_other_user(repository):
    _employee(repository, "employee-1")
    _employee(repository, "employee-2")
    first = repository.start_random_event_submission("employee-1", NOW).submission
    second = repository.start_random_event_submission(
        "employee-2", NOW + timedelta(minutes=20)
    ).submission

    expired = repository.expire_random_event_submission_drafts(
        NOW + timedelta(minutes=31)
    )

    assert expired == 1
    assert repository.get_random_event_submission(first.id).status == "expired"
    assert repository.get_random_event_submission(second.id).status == "draft"


def test_daily_jobs_expire_inactive_submission_drafts(repository):
    """Fails if an abandoned private wizard remains active until its owner returns."""
    _employee(repository)
    draft = repository.start_random_event_submission("employee-1", NOW).submission

    repository.run_daily_jobs(NOW + timedelta(minutes=31))

    assert repository.get_random_event_submission(draft.id).status == "expired"


def _direct(
    content,
    platform_id="employee-1",
    message_id="message-1",
    received_at=NOW,
):
    return InboundMessage(
        message_id,
        platform_id,
        content,
        received_at,
        source_type="direct",
        chatroom_id=f"direct-{platform_id}",
    )


def _legacy_role_capacity_handler(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    draft = repository.start_random_event_submission(
        "employee-1", NOW
    ).submission
    repository.replace_random_event_submission_content(
        draft.id,
        {
            "scene_name": "失踪的咖啡",
            "signup_text": "茶水间出事了。",
            "participant_count": 3,
            "roles": [{"role": "调查员", "capacity": 1}],
            "events": [],
            "_working_role": "嫌疑人",
        },
        "role_capacity",
        NOW,
    )
    return handler


def test_legacy_role_capacity_resume_defaults_pending_role_to_one(repository):
    """Fails if resuming an old draft still asks for identity capacity."""
    handler = _legacy_role_capacity_handler(repository)

    reply = handler.handle(_direct("/投稿 随机事件"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert "还剩 1" in reply.text
    assert "身份人数" not in reply.text
    assert draft.current_step == "role_name"
    assert draft.content["roles"] == [
        {"role": "调查员", "capacity": 1},
        {"role": "嫌疑人", "capacity": 1},
    ]


def test_legacy_role_capacity_plain_text_is_used_as_next_role(repository):
    """Fails if compatibility consumes the player's next role-name message."""
    handler = _legacy_role_capacity_handler(repository)

    reply = handler.handle(_direct("目击者"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert "事件名称" in reply.text
    assert draft.current_step == "event_name"
    assert [item["role"] for item in draft.content["roles"]] == [
        "调查员", "嫌疑人", "目击者",
    ]
    assert all(item["capacity"] == 1 for item in draft.content["roles"])


def test_legacy_role_capacity_is_normalized_only_once(repository):
    """Fails if repeatedly resuming a migrated draft duplicates its pending role."""
    handler = _legacy_role_capacity_handler(repository)

    handler.handle(_direct("/投稿 随机事件"))
    handler.handle(_direct("/投稿 随机事件"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert [item["role"] for item in draft.content["roles"]] == [
        "调查员", "嫌疑人",
    ]


def test_submission_wizard_collects_complete_scene_one_field_at_a_time(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)

    start = handler.handle(_direct("/投稿 随机事件"))
    assert start.text == "请先发送场景名称（1～64 字）。"

    assert "报名公告" in handler.handle(_direct("失踪的咖啡")).text
    assert "参加人数" in handler.handle(_direct("茶水间出事了，快来报名。")).text
    assert "身份名称" in handler.handle(_direct("3")).text
    assert "还剩 2" in handler.handle(_direct("调查员")).text
    assert "还剩 1" in handler.handle(_direct("嫌疑人")).text
    assert "事件名称" in handler.handle(_direct("目击者")).text
    assert "剧情开场白" in handler.handle(_direct("现场")).text
    controls = handler.handle(_direct("{调查员}发现了空杯。"))
    assert "/事件完成" in controls.text
    preview = handler.handle(_direct("/事件完成"))
    assert "失踪的咖啡" in preview.text
    assert "调查员 × 1" in preview.text
    assert "嫌疑人 × 1" in preview.text
    assert "目击者 × 1" in preview.text
    assert "/确认投稿" in preview.text
    confirmed = handler.handle(_direct("/确认投稿"))
    assert "已提交审核" in confirmed.text


def test_submission_daily_limit_reply_is_exact_and_keeps_preview(repository):
    first = _pending_submission(repository)
    repository.withdraw_random_event_submission(
        "employee-1", first.number, NOW + timedelta(minutes=1)
    )
    _preview_submission(repository, now=NOW + timedelta(minutes=2))

    reply = RandomEventSubmissionHandler(repository).handle(
        _direct(
            "/确认投稿",
            received_at=NOW + timedelta(minutes=10),
        )
    )

    assert reply.text == "你今天已经投稿过一次，请明天再来。"
    draft = repository.active_random_event_submission(
        "employee-1", NOW + timedelta(minutes=10)
    )
    assert draft.current_step == "preview"


def test_submission_role_names_each_fill_one_seat(repository):
    """Fails if role entry still needs a capacity message or stores another value."""
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人",
    ):
        reply = handler.handle(_direct(content))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert reply is not None
    assert "事件名称" in reply.text
    assert "身份人数" not in reply.text
    assert draft.current_step == "event_name"
    assert draft.content["roles"] == [
        {"role": "调查员", "capacity": 1},
        {"role": "嫌疑人", "capacity": 1},
    ]


def test_submission_wizard_rejects_misordered_variable_braces_immediately(repository):
    """Fails if malformed braces advance the wizard and only fail at confirmation."""
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人", "现场",
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct("}{"))

    assert "括号不完整" in reply.text
    assert repository.active_random_event_submission(
        "employee-1", NOW
    ).current_step == "event_opening"


@pytest.mark.parametrize(
    "opening",
    (
        "｛调查员｝发现了空杯。",
        "【调查员】发现了空杯。",
        "[调查员]发现了空杯。",
    ),
)
def test_submission_wizard_normalizes_compatible_role_variable_braces(
    repository, opening
):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "1",
        "调查员", "现场",
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct(opening))
    draft = repository.active_random_event_submission("employee-1", NOW)

    assert "/事件完成" in reply.text
    assert draft.content["events"][0]["opening_text"] == "{调查员}发现了空杯。"


def test_submission_wizard_preserves_bracketed_text_that_is_not_a_role(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "1",
        "调查员", "现场",
    ):
        handler.handle(_direct(content))

    handler.handle(_direct("【第一幕】[调查员]发现了空杯。"))
    draft = repository.active_random_event_submission("employee-1", NOW)

    assert draft.content["events"][0]["opening_text"] == "【第一幕】{调查员}发现了空杯。"


def test_submission_step_prompt_uses_configured_reply_template(repository):
    _employee(repository)
    repository.set_reply_template(
        "/投稿", "prompt_scene_name", "请填写投稿场景名。"
    )

    reply = RandomEventSubmissionHandler(repository).handle(
        _direct("/投稿 随机事件")
    )

    assert reply.text == "请填写投稿场景名。"


def test_submission_wizard_does_not_consume_unrelated_commands(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    handler.handle(_direct("/投稿 随机事件"))

    assert handler.handle(_direct("/余额")) is None
    assert repository.active_random_event_submission(
        "employee-1", NOW
    ).current_step == "scene_name"


def test_submission_cancel_requires_confirmation(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    handler.handle(_direct("/投稿 随机事件"))

    prompt = handler.handle(_direct("/取消投稿"))
    assert "/确认取消投稿" in prompt.text
    assert repository.active_random_event_submission("employee-1", NOW) is not None

    cancelled = handler.handle(_direct("/确认取消投稿"))
    assert "已取消" in cancelled.text
    assert repository.active_random_event_submission("employee-1", NOW) is None


def test_submission_confirmation_reports_when_submissions_were_disabled(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人", "现场", "{调查员}发现空杯。", "/事件完成",
    ):
        handler.handle(_direct(content))
    settings = repository.get_random_event_settings()
    repository.set_random_event_settings(
        settings.schedule_times,
        settings.signup_notice_template,
        settings.signup_timeout_minutes,
        settings.reminder_interval_minutes,
        settings.signup_allowed_commands,
        settings.in_progress_allowed_commands,
        settings.blocked_message,
        submission_enabled=False,
    )

    reply = handler.handle(_direct("/确认投稿"))

    assert "未开放" in reply.text
    assert repository.active_random_event_submission("employee-1", NOW) is not None


def test_my_submissions_shows_submission_and_review_times(repository):
    """Fails if players cannot tell when a reviewed submission changed state."""
    pending = _pending_submission(repository)
    repository.reject_random_event_submission(
        pending.id, "super-admin", "身份说明需补充", NOW + timedelta(hours=1)
    )

    reply = RandomEventSubmissionHandler(repository).handle(_direct("/我的投稿"))

    assert "提交于 2026-08-15 20:00" in reply.text
    assert "审核于 2026-08-15 21:00" in reply.text


def test_group_submission_entry_enqueues_group_notice_and_private_prompt(repository):
    _employee(repository)
    service = CoreService(repository, GroupCommandHandler(repository))

    service.receive_inbound(
        InboundMessage("group-start", "employee-1", "/投稿 随机事件", NOW)
    )

    with repository._session_factory() as session:
        records = list(
            session.scalars(
                select(OutboundRecord).order_by(OutboundRecord.created_at, OutboundRecord.reply_index)
            )
        )
    assert [(record.text, record.destination_chatroom_id) for record in records] == [
        ("已转入私聊引导。", None),
        ("请先发送场景名称（1～64 字）。", "direct-employee-1"),
    ]
    assert records[0].reference_message_id == "group-start"
    assert records[1].reference_message_id is None


def test_direct_balance_command_does_not_advance_submission_draft(repository):
    _employee(repository)
    service = CoreService(repository, GroupCommandHandler(repository))
    service.receive_inbound(_direct("/投稿 随机事件", message_id="start"))

    service.receive_inbound(_direct("/余额", message_id="balance"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert draft.current_step == "scene_name"
    with repository._session_factory() as session:
        balance_reply = session.scalar(
            select(OutboundRecord).where(
                OutboundRecord.reference_message_id == "balance"
            )
        )
    assert "余额" in balance_reply.text
    assert balance_reply.destination_chatroom_id == "direct-employee-1"


def test_direct_game_command_does_not_advance_submission_draft(repository):
    _employee(repository)
    service = CoreService(repository, GroupCommandHandler(repository))
    service.receive_inbound(_direct("/投稿 随机事件", message_id="start"))

    service.receive_inbound(_direct("/退出", message_id="exit"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert draft.current_step == "scene_name"
    with repository._session_factory() as session:
        reply = session.scalar(
            select(OutboundRecord).where(OutboundRecord.reference_message_id == "exit")
        )
    assert reply is not None


def test_edit_role_refills_only_role_name(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件",
        "失踪的咖啡",
        "茶水间出事了。",
        "2",
        "调查员",
        "嫌疑人",
        "现场",
        "{调查员}发现空杯。",
        "/事件完成",
    ):
        handler.handle(_direct(content))

    prompt = handler.handle(_direct("/修改身份 1"))
    renamed = handler.handle(_direct("侦探"))

    assert "身份名称" in prompt.text
    assert "身份人数" not in renamed.text
    assert "事件名称" in renamed.text
    draft = repository.active_random_event_submission("employee-1", NOW)
    assert draft.content["roles"] == [
        {"role": "侦探", "capacity": 1},
        {"role": "嫌疑人", "capacity": 1},
    ]


def test_delete_role_returns_to_role_name(repository):
    """Fails if deleting a role leaves the draft full or enters capacity input."""
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人", "现场", "{调查员}发现空杯。", "/事件完成",
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct("/删除身份 1"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert "身份名称" in reply.text
    assert "身份人数" not in reply.text
    assert draft.current_step == "role_name"
    assert draft.content["roles"] == [{"role": "嫌疑人", "capacity": 1}]
    assert draft.content["events"] == []


def test_back_from_partially_filled_roles_reopens_last_role(repository):
    """Fails if backtracking from role names returns to legacy capacity input."""
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "3", "调查员",
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct("/上一步"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert "身份名称" in reply.text
    assert "身份人数" not in reply.text
    assert draft.current_step == "role_name"
    assert draft.content["roles"] == []


def test_back_from_event_name_reopens_last_role(repository):
    """Fails if a full role list backtracks into the removed capacity step."""
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人",
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct("/上一步"))

    draft = repository.active_random_event_submission("employee-1", NOW)
    assert "身份名称" in reply.text
    assert "身份人数" not in reply.text
    assert draft.current_step == "role_name"
    assert draft.content["roles"] == [{"role": "调查员", "capacity": 1}]


def test_back_from_first_role_returns_to_participant_count(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2"
    ):
        handler.handle(_direct(content))

    reply = handler.handle(_direct("/上一步"))

    assert "参加人数" in reply.text


def test_edit_event_refills_event_name_and_opening(repository):
    _employee(repository)
    handler = RandomEventSubmissionHandler(repository)
    for content in (
        "/投稿 随机事件", "失踪的咖啡", "茶水间出事了。", "2",
        "调查员", "嫌疑人", "旧事件", "{调查员}发现空杯。", "/事件完成",
    ):
        handler.handle(_direct(content))

    prompt = handler.handle(_direct("/修改事件 1"))
    opening = handler.handle(_direct("新事件"))
    handler.handle(_direct("{调查员}发现文件。"))
    preview = handler.handle(_direct("/事件完成"))

    assert "事件名称" in prompt.text
    assert "剧情开场白" in opening.text
    assert "新事件" in preview.text
    assert "旧事件" not in preview.text


def test_plain_direct_submission_value_is_not_marked_ai_memory_eligible(repository):
    _employee(repository)
    service = CoreService(repository, GroupCommandHandler(repository))
    service.receive_inbound(_direct("/投稿 随机事件", message_id="start"))

    service.receive_inbound(_direct("失踪的咖啡", message_id="draft-content"))

    with repository._session_factory() as session:
        inbound = session.scalar(
            select(InboundRecord).where(
                InboundRecord.platform_message_id == "draft-content"
            )
        )
    assert inbound.ai_memory_eligible is False


def test_submission_approval_atomically_creates_scene_rewards_and_notifies(repository):
    pending = _pending_submission(repository)

    approved = repository.approve_random_event_submission(
        pending.id, "管理员甲", NOW
    )

    assert approved.status == "approved"
    assert approved.scene_id is not None
    profile = repository.get_user_profile("employee-1")
    assert profile.user.balance == 10
    [scene] = repository.list_random_event_scenes()
    assert scene.name == "失踪的咖啡-employee-1"
    assert scene.enabled is True
    with repository._session_factory() as session:
        notification = session.scalar(
            select(OutboundRecord).where(OutboundRecord.inbound_message_id.is_(None))
        )
    assert notification.destination_chatroom_id == "direct-employee-1"
    assert "获得 10 摸鱼币" in notification.text

    with pytest.raises(ValueError, match="待审核"):
        repository.approve_random_event_submission(pending.id, "管理员乙", NOW)
    assert repository.get_user_profile("employee-1").user.balance == 10
    [fact] = repository.list_ai_activity_facts("employee-1")
    assert fact.activity_type == "随机事件投稿"
    assert (fact.participation_count, fact.win_count, fact.loss_count) == (2, 1, 0)


def test_submission_rejection_requires_reason_and_notifies_without_reward(repository):
    pending = _pending_submission(repository)

    with pytest.raises(ValueError, match="拒绝原因"):
        repository.reject_random_event_submission(pending.id, "管理员甲", "", NOW)

    rejected = repository.reject_random_event_submission(
        pending.id, "管理员甲", "身份设计不完整", NOW
    )

    assert rejected.status == "rejected"
    assert rejected.rejection_reason == "身份设计不完整"
    assert repository.get_user_profile("employee-1").user.balance == 0
    with repository._session_factory() as session:
        notification = session.scalar(
            select(OutboundRecord).where(OutboundRecord.inbound_message_id.is_(None))
        )
    assert "身份设计不完整" in notification.text


def test_pending_submission_remains_editable_after_maximum_is_reduced(repository):
    pending = _pending_submission(repository)
    settings = repository.get_random_event_settings()
    repository.set_random_event_settings(
        settings.schedule_times,
        settings.signup_notice_template,
        settings.signup_timeout_minutes,
        settings.reminder_interval_minutes,
        settings.signup_allowed_commands,
        settings.in_progress_allowed_commands,
        settings.blocked_message,
        submission_max_participants=2,
    )

    updated = repository.update_random_event_submission_content(
        pending.id,
        {**pending.content, "scene_name": "修改后的场景"},
        NOW + timedelta(minutes=1),
    )

    assert updated.content["scene_name"] == "修改后的场景"


def test_admin_edit_rejects_unbalanced_role_variable_braces(repository):
    pending = _pending_submission(repository)
    content = deepcopy(pending.content)
    content["events"][0]["opening_text"] = "{调查员发现了空杯。"

    with pytest.raises(ValueError, match="括号"):
        repository.update_random_event_submission_content(
            pending.id, content, NOW + timedelta(minutes=1)
        )


def test_admin_edit_rejects_non_text_nested_content(repository):
    pending = _pending_submission(repository)
    content = deepcopy(pending.content)
    content["events"][0]["opening_text"] = {"unexpected": "object"}

    with pytest.raises(ValueError, match="事件模板无效"):
        repository.update_random_event_submission_content(
            pending.id, content, NOW + timedelta(minutes=1)
        )
