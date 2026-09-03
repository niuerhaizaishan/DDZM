from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from time import monotonic, sleep
from uuid import UUID

import pytest
from socketio.exceptions import TimeoutError as SocketTimeoutError

from dzmm_bot.browser.bot_api import DzmmBotSendError
from dzmm_bot.browser.core_client import OutboundClaim, OutboundRecallClaim, WorkerCommand
from dzmm_bot.browser.aikda_socket import AikdaTransportError
from dzmm_bot.browser.worker import BrowserWorker
from dzmm_bot.runtime.contracts import (
    DirectChatRoom,
    GroupChatTarget,
    InboundMessage,
    LoginState,
    MessageReference,
)


NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
LEASE = UUID("00000000-0000-0000-0000-000000000001")
OUTBOUND_ID = UUID("00000000-0000-0000-0000-000000000002")
COMMAND_ID = UUID("00000000-0000-0000-0000-000000000003")
GROUP_ID = UUID("00000000-0000-0000-0000-000000000101")


@dataclass
class FakeGateway:
    messages: list[InboundMessage] = field(default_factory=list)
    authenticated: bool = True
    authentication_error: Exception | None = None
    account_display_name: str | None = None
    sent: list[str] = field(default_factory=list)
    sent_to: list[tuple[str, str]] = field(default_factory=list)
    sent_images: list[tuple[str, str]] = field(default_factory=list)
    uploaded_images: list[tuple[str, str]] = field(default_factory=list)
    upload_error: Exception | None = None
    retracted: list[str] = field(default_factory=list)
    retracted_to: list[tuple[str, str | None]] = field(default_factory=list)
    retract_error: Exception | None = None
    send_error: Exception | None = None
    read_error: Exception | None = None
    read_targets: list[tuple[str, ...]] = field(default_factory=list)
    message_handler: object | None = None
    send_delay_seconds: float = 0
    sent_message_ids: list[str | None] = field(default_factory=list)
    send_errors: list[Exception] = field(default_factory=list)
    sent_references: list[MessageReference | None] = field(default_factory=list)
    direct_send_release: Event | None = None
    direct_send_started: Event = field(default_factory=Event)
    direct_send_count: int = 0
    direct_send_lock: Lock = field(default_factory=Lock)
    maintenance_started: Event = field(default_factory=Event)
    maintenance_release: Event | None = None
    configured_groups: tuple[GroupChatTarget, ...] = ()
    close_count: int = 0
    close_error: Exception | None = None
    added_bots: list[tuple[str, str]] = field(default_factory=list)

    def configure_group_rooms(self, targets):
        self.configured_groups = targets

    def group_room_states(self):
        return {
            target.chatroom_id: ("connected", None)
            for target in self.configured_groups
        }

    def read_new(self, direct_chatroom_ids=()):
        self.read_targets.append(direct_chatroom_ids)
        if self.read_error:
            raise self.read_error
        return list(self.messages)

    def send(self, text, *, message_id=None, reference=None):
        self.sent_message_ids.append(message_id)
        self.sent_references.append(reference)
        if self.send_errors:
            raise self.send_errors.pop(0)
        if self.send_error:
            raise self.send_error
        if self.send_delay_seconds:
            sleep(self.send_delay_seconds)
        self.sent.append(text)
        return f"sent-{len(self.sent)}"

    def send_to(self, chatroom_id, text, *, message_id=None, reference=None):
        self.sent_message_ids.append(message_id)
        self.sent_references.append(reference)
        with self.direct_send_lock:
            self.direct_send_count += 1
            if self.direct_send_count >= 2:
                self.direct_send_started.set()
        if self.direct_send_release is not None:
            self.direct_send_release.wait(timeout=2)
        if self.send_errors:
            raise self.send_errors.pop(0)
        if self.send_error:
            raise self.send_error
        self.sent_to.append((chatroom_id, text))
        return f"direct-{len(self.sent_to)}"

    def send_image(self, image_url, *, alt="image", message_id=None, reference=None):
        self.sent_message_ids.append(message_id)
        self.sent_references.append(reference)
        self.sent_images.append((image_url, alt))
        return f"image-{len(self.sent_images)}"

    def send_image_to(
        self, chatroom_id, image_url, *, alt="image", message_id=None,
        reference=None,
    ):
        raise AssertionError("unexpected targeted image")

    def upload_image(self, path, mime_type):
        if self.upload_error is not None:
            raise self.upload_error
        self.uploaded_images.append((str(path), mime_type))
        return {"url": "https://cdn.example.com/uploaded.png"}

    def maintain_recovery(self, direct_chatroom_ids=()):
        self.maintenance_started.set()
        if self.maintenance_release is not None:
            self.maintenance_release.wait(timeout=2)

    def set_message_handler(self, handler):
        self.message_handler = handler

    def is_authenticated(self):
        if self.authentication_error is not None:
            raise self.authentication_error
        return self.authenticated

    def retract(self, message_id, *, chatroom_id=None):
        self.retracted.append(message_id)
        self.retracted_to.append((message_id, chatroom_id))
        if self.retract_error is not None:
            raise self.retract_error

    def close(self):
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error

    def add_bot_to_chatroom(self, chatroom_id, bot_id):
        self.added_bots.append((chatroom_id, bot_id))

@dataclass
class FakeSession:
    gateway: FakeGateway
    starts: int = 0
    stops: int = 0

    def configure_group_chats(self, targets):
        self.gateway.configure_group_rooms(targets)

    def start_headless(self):
        self.starts += 1
        return self.gateway

    def attach_existing(self):
        self.starts += 1
        return self.gateway

    def stop(self):
        self.stops += 1

    def login_state(self):
        return LoginState.READY if self.gateway.authenticated else LoginState.AUTH_REQUIRED


@dataclass
class FakeDesktop:
    starts: int = 0
    stops: int = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


@dataclass
class FakeBotSender:
    sent_to: list[tuple[str, str]] = field(default_factory=list)
    send_error: Exception | None = None

    def send_to(self, chatroom_id, text):
        self.sent_to.append((chatroom_id, text))
        if self.send_error is not None:
            raise self.send_error
        return f"bot-{len(self.sent_to)}"


@dataclass
class FakeCore:
    pending: list[OutboundClaim] = field(default_factory=list)
    pending_recalls: list[OutboundRecallClaim] = field(default_factory=list)
    commands: list[WorkerCommand] = field(default_factory=list)
    submitted_ids: list[str] = field(default_factory=list)
    confirmed: list[tuple] = field(default_factory=list)
    failed: list[tuple] = field(default_factory=list)
    recalls_confirmed: list[tuple] = field(default_factory=list)
    recalls_failed: list[tuple] = field(default_factory=list)
    heartbeats: list[tuple] = field(default_factory=list)
    bot_delivery_heartbeats: list[tuple] = field(default_factory=list)
    completions: list[tuple] = field(default_factory=list)
    audits: list[tuple] = field(default_factory=list)
    daily_job_times: list[datetime] = field(default_factory=list)
    direct_chat_syncs: list[tuple[list[DirectChatRoom], datetime]] = field(default_factory=list)
    direct_chat_sync_event: Event = field(default_factory=Event)
    listening_desired: bool = True
    direct_rooms_to_read: tuple[str, ...] = ()
    submitted_event: Event = field(default_factory=Event)
    confirmed_event: Event = field(default_factory=Event)
    failed_event: Event = field(default_factory=Event)
    released: list[tuple] = field(default_factory=list)
    released_event: Event = field(default_factory=Event)
    upload_tasks: list = field(default_factory=list)
    upload_completions: list[tuple] = field(default_factory=list)
    upload_failures: list[tuple] = field(default_factory=list)
    upload_cleanup_tasks: list = field(default_factory=list)
    upload_cleanups: list[tuple] = field(default_factory=list)
    upload_completion_accepted: bool = True
    group_targets: tuple[GroupChatTarget, ...] = ()
    group_runtime_updates: list[tuple] = field(default_factory=list)
    confirm_error: Exception | None = None

    def group_chat_targets(self):
        return self.group_targets

    def sync_group_chat_runtime(self, worker_id, updates, now):
        self.group_runtime_updates.append((worker_id, updates, now))
        return True

    def submit_inbound(self, message):
        self.submitted_ids.append(message.platform_message_id)
        self.submitted_event.set()

    def claim_outbound(
        self, worker_id, now, lease_seconds, excluded_delivery_keys=(),
        required_delivery_key=None,
    ):
        for index, outbound in enumerate(self.pending):
            if outbound.delivery_key in excluded_delivery_keys:
                continue
            if (
                required_delivery_key is not None
                and outbound.delivery_key != required_delivery_key
            ):
                continue
            return self.pending.pop(index)
        return None

    def confirm_sent(self, message_id, worker_id, lease_token, platform_sent_id, now):
        if self.confirm_error is not None:
            raise self.confirm_error
        self.confirmed.append(
            (message_id, worker_id, lease_token, platform_sent_id, now)
        )
        self.confirmed_event.set()

    def mark_outbound_failed(self, message_id, worker_id, lease_token, now):
        self.failed.append((message_id, worker_id, lease_token, now))
        self.failed_event.set()

    def release_outbound(self, message_id, worker_id, lease_token, now):
        self.released.append((message_id, worker_id, lease_token, now))
        self.released_event.set()

    def claim_outbound_recall(self, worker_id, now, lease_seconds):
        return self.pending_recalls.pop(0) if self.pending_recalls else None

    def confirm_outbound_recalled(self, message_id, worker_id, lease_token, now):
        self.recalls_confirmed.append((message_id, worker_id, lease_token, now))

    def fail_outbound_recall(self, message_id, worker_id, lease_token, now):
        self.recalls_failed.append((message_id, worker_id, lease_token, now))

    def heartbeat(
        self,
        worker_id,
        login_state,
        listening,
        recorded_at,
        account_display_name=None,
        bot_delivery_state="unknown",
        bot_delivery_error=None,
    ):
        self.heartbeats.append(
            (worker_id, login_state, listening, recorded_at, account_display_name)
        )
        self.bot_delivery_heartbeats.append(
            (bot_delivery_state, bot_delivery_error)
        )
        return self.listening_desired

    def claim_command(self, worker_id, now, lease_seconds):
        command = self.commands.pop(0) if self.commands else None
        if command is not None and command.command == "pause_listening":
            self.listening_desired = False
        elif command is not None and command.command == "resume_listening":
            self.listening_desired = True
        return command

    def complete_command(self, command_id, worker_id, lease_token, status, now):
        self.completions.append(
            (command_id, worker_id, lease_token, status, now)
        )

    def record_audit(self, event_type, worker_id, recorded_at):
        self.audits.append((event_type, worker_id, recorded_at))

    def run_daily_jobs(self, now):
        self.daily_job_times.append(now)

    def sync_direct_chats(self, rooms, now):
        self.direct_chat_syncs.append((rooms, now))
        self.direct_chat_sync_event.set()

    def direct_inbound_chatroom_ids(self):
        return self.direct_rooms_to_read

    def claim_profile_image_upload(self, worker_id, now, lease_seconds):
        return self.upload_tasks.pop(0) if self.upload_tasks else None

    def complete_profile_image_upload(
        self, task_id, worker_id, lease_token, result_url, now
    ):
        self.upload_completions.append(
            (task_id, worker_id, lease_token, result_url, now)
        )
        return self.upload_completion_accepted

    def fail_profile_image_upload(
        self, task_id, worker_id, lease_token, failure_summary, now
    ):
        self.upload_failures.append(
            (task_id, worker_id, lease_token, failure_summary, now)
        )
        return self.upload_completion_accepted

    def claim_profile_image_cleanup(self, worker_id, now, lease_seconds):
        return self.upload_cleanup_tasks.pop(0) if self.upload_cleanup_tasks else None

    def complete_profile_image_cleanup(
        self, task_id, worker_id, lease_token, now
    ):
        self.upload_cleanups.append((task_id, worker_id, lease_token, now))


@pytest.fixture
def context():
    gateway = FakeGateway()
    session = FakeSession(gateway)
    desktop = FakeDesktop()
    core = FakeCore()
    sleeps = []
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        sleep=sleeps.append,
    )
    return worker, gateway, session, desktop, core, sleeps


def test_worker_submits_each_platform_message_once(context):
    worker, gateway, _, _, core, _ = context
    gateway.messages = [InboundMessage("p-1", "u-1", "/test", NOW)]

    worker.run_once()
    worker.run_once()

    assert core.submitted_ids == ["p-1"]


def test_worker_adds_the_configured_long_message_bot_to_a_group():
    gateway = FakeGateway()
    core = FakeCore(commands=[WorkerCommand(COMMAND_ID, "add_bot:group-a", LEASE)])
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=FakeSession(gateway),
        desktop=FakeDesktop(),
        clock=lambda: NOW,
        sleep=lambda _: None,
        long_message_bot_id="long-message-bot",
    )

    worker.run_once()

    assert gateway.added_bots == [("group-a", "long-message-bot")]
    assert core.completions[-1][3] == "completed"


def test_worker_keeps_socket_transport_alive_when_daily_jobs_fail_once(context):
    worker, gateway, session, _, core, _ = context
    attempts = 0

    def run_daily_jobs(now):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("daily jobs failed")
        core.daily_job_times.append(now)

    core.run_daily_jobs = run_daily_jobs

    worker.run_once()
    worker.run_once()

    assert attempts == 2
    assert session.starts == 1
    assert len(gateway.read_targets) == 2


def test_worker_adds_and_removes_groups_without_restart():
    gateway = FakeGateway()
    session = FakeSession(gateway)
    core = FakeCore()
    clock_time = [NOW]
    group_a = GroupChatTarget(
        UUID("00000000-0000-0000-0000-000000000101"),
        "group-a",
        "https://www.aikda.com/chat?c=group-a",
    )
    group_b = GroupChatTarget(
        UUID("00000000-0000-0000-0000-000000000102"),
        "group-b",
        "https://www.aikda.com/chat?c=group-b",
    )
    core.group_targets = (group_a,)
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=FakeDesktop(),
        clock=lambda: clock_time[0],
        sleep=lambda _: None,
    )

    worker.run_once()
    assert {item.chatroom_id for item in gateway.configured_groups} == {"group-a"}

    clock_time[0] = NOW + timedelta(seconds=6)
    core.group_targets = (group_a, group_b)
    worker.run_once()
    assert {item.chatroom_id for item in gateway.configured_groups} == {
        "group-a",
        "group-b",
    }

    clock_time[0] = NOW + timedelta(seconds=12)
    core.group_targets = (group_b,)
    worker.run_once()

    assert session.starts == 1
    assert {item.chatroom_id for item in gateway.configured_groups} == {"group-b"}
    all_updates = [
        update
        for _, updates, _ in core.group_runtime_updates
        for update in updates
    ]
    assert any(
        update.group_chat_id == group_a.group_chat_id
        and update.connection_state == "disabled"
        for update in all_updates
    )


def test_worker_reads_only_core_selected_direct_rooms(context):
    worker, gateway, _, _, core, _ = context
    core.direct_rooms_to_read = ("direct-1",)
    gateway.messages = [
        InboundMessage(
            "dm-1", "u-1", "/报数 29", NOW,
            source_type="direct", chatroom_id="direct-1",
        )
    ]

    worker.run_once()

    assert gateway.read_targets == [("direct-1",)]
    assert core.submitted_ids == ["dm-1"]


def test_worker_maps_but_does_not_dispatch_an_ordinary_unknown_direct_message(context):
    worker, gateway, _, _, core, _ = context
    worker.run_once()

    assert gateway.message_handler is not None
    gateway.message_handler(InboundMessage(
        "new-dm", "new-user", "你好", NOW,
        source_type="direct", chatroom_id="new-direct",
    ))

    assert core.direct_chat_sync_event.wait(timeout=1)
    assert core.direct_chat_syncs[-1] == (
        [DirectChatRoom("new-user", "new-direct")], NOW
    )
    assert core.submitted_ids == []


def test_worker_dispatches_the_random_event_submission_entry_from_a_new_direct_room(
    context,
):
    worker, gateway, _, _, core, _ = context
    worker.run_once()

    gateway.message_handler(InboundMessage(
        "new-submission", "new-user", "/投稿 随机事件", NOW,
        source_type="direct", chatroom_id="new-direct",
    ))

    assert core.submitted_event.wait(timeout=1)
    assert core.direct_chat_syncs[-1] == (
        [DirectChatRoom("new-user", "new-direct")], NOW
    )
    assert core.submitted_ids == ["new-submission"]


@pytest.mark.parametrize(
    "content",
    (
        "/上架暗网",
        "/取消上架",
        "/确认",
        "/报价 12 25",
        "/公开 12",
        "/不公开 12",
        "/确认收货 12",
        "/投诉 12",
        "/查看暗网",
        "/登陆暗网",
        "/登录暗网",
        "/暗网",
    ),
)
def test_worker_dispatches_dark_market_commands_from_a_new_direct_room(context, content):
    worker, gateway, _, _, core, _ = context
    worker.run_once()

    gateway.message_handler(
        InboundMessage(
            f"new-dark-market-{content}",
            "new-user",
            content,
            NOW,
            source_type="direct",
            chatroom_id="new-direct",
        )
    )

    assert core.submitted_event.wait(timeout=1)
    assert core.direct_chat_syncs[-1] == (
        [DirectChatRoom("new-user", "new-direct")],
        NOW,
    )
    assert core.submitted_ids == [f"new-dark-market-{content}"]


def test_worker_does_not_wait_for_outbound_socket_send(context):
    worker, gateway, _, _, core, _ = context
    gateway.send_delay_seconds = 0.2
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]

    started = monotonic()
    worker.run_once()

    assert monotonic() - started < 0.1


def test_worker_starts_outbound_before_blocked_chat_maintenance(context):
    worker, gateway, _, _, core, _ = context
    gateway.maintenance_release = Event()
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]

    run = Thread(target=worker.run_once)
    run.start()
    assert gateway.maintenance_started.wait(timeout=1)
    try:
        assert core.confirmed_event.wait(timeout=1)
    finally:
        gateway.maintenance_release.set()
        run.join(timeout=1)


def test_worker_runs_daily_jobs_after_submitting_messages(context):
    worker, gateway, _, _, core, _ = context
    gateway.messages = [InboundMessage("p-1", "u-1", "普通消息", NOW)]

    worker.run_once()

    assert core.submitted_ids == ["p-1"]
    assert core.daily_job_times == [NOW]


def test_worker_heartbeats_the_current_account_display_name(context):
    worker, gateway, _, _, core, _ = context
    gateway.account_display_name = "饭饭（小狗青巫）."

    worker.run_once()

    assert core.heartbeats[-1] == (
        "worker-a",
        LoginState.READY,
        True,
        NOW,
        "饭饭（小狗青巫）.",
    )

def test_worker_releases_transport_failure_without_marking_auth_lost(context):
    worker, gateway, session, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]
    gateway.send_error = RuntimeError("page unavailable")

    worker.run_once()
    next(iter(worker._outbound_futures.values())).result(timeout=1)
    worker.run_once()

    assert core.confirmed == []
    assert core.released == [(OUTBOUND_ID, "worker-a", LEASE, NOW)]
    assert gateway.close_count == 1
    assert session.stops == 0
    assert core.audits == []
    assert worker.login_state is LoginState.READY


def test_read_transport_failure_closes_socket_without_marking_auth_required(context):
    worker, gateway, session, _, core, _ = context
    gateway.read_error = AikdaTransportError("socket disconnected")

    worker.run_once()

    assert worker.login_state is LoginState.READY
    assert gateway.close_count == 1
    assert session.stops == 0
    assert core.audits == []
    assert core.heartbeats[-1] == (
        "worker-a",
        LoginState.READY,
        True,
        NOW,
        None,
    )


def test_authentication_transport_failure_keeps_the_worker_ready(context):
    worker, gateway, session, _, core, _ = context
    gateway.authentication_error = AikdaTransportError("request aborted")

    worker.run_once()

    assert worker.login_state is LoginState.READY
    assert session.stops == 0
    assert core.audits == []
    assert core.daily_job_times == [NOW]


def test_worker_resumes_reading_after_an_authenticated_session_recovers(context):
    """Fails if recovery returns Ready but leaves inbound listening disabled."""
    worker, gateway, _, _, core, _ = context
    gateway.read_error = AikdaTransportError("temporary socket failure")

    worker.run_once()

    gateway.read_error = None
    gateway.messages = [InboundMessage("p-recovered", "u-1", "/帮助", NOW)]
    worker.run_once()

    assert worker.login_state is LoginState.READY
    assert core.submitted_ids == ["p-recovered"]


def test_worker_applies_persisted_pause_before_reading(context):
    worker, gateway, _, _, core, _ = context
    core.listening_desired = False
    gateway.messages = [InboundMessage("p-paused", "u-1", "/打卡", NOW)]

    worker.run_once()
    worker.run_once()

    assert core.submitted_ids == []
    assert core.heartbeats[-1] == (
        "worker-a",
        LoginState.READY,
        False,
        NOW,
        None,
    )


def test_worker_applies_persisted_enable_after_pause(context):
    worker, gateway, _, _, core, _ = context
    core.listening_desired = False
    worker.run_once()
    core.listening_desired = True
    gateway.messages = [InboundMessage("p-enabled", "u-1", "/打卡", NOW)]

    worker.run_once()

    assert core.submitted_ids == ["p-enabled"]


def test_duplicate_content_rejection_is_marked_failed_without_resetting_browser(context):
    worker, gateway, session, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]
    gateway.send_error = RuntimeError("请勿发送重复内容")

    worker.run_once()

    assert core.failed_event.wait(timeout=1)
    assert core.confirmed == []
    assert core.failed == [(OUTBOUND_ID, "worker-a", LEASE, NOW)]
    assert worker.login_state is LoginState.READY
    assert session.stops == 0


def test_sent_confirmation_includes_current_fencing_values(context):
    worker, _, _, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert core.confirmed == [
        (OUTBOUND_ID, "worker-a", LEASE, "sent-1", NOW)
    ]


def test_worker_routes_image_outbound_to_gateway_image_send(context):
    worker, gateway, _, _, core, _ = context
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", "", LEASE,
        content_type="image",
        image_url="https://cdn.example.com/profile.webp",
        image_alt="档案形象",
    )]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert gateway.sent == []
    assert gateway.sent_images == [
        ("https://cdn.example.com/profile.webp", "档案形象")
    ]
    assert core.confirmed[0][3] == "image-1"


def test_worker_uploads_profile_image_reports_completion_and_removes_temp_file(
    context, tmp_path
):
    from dzmm_bot.browser.core_client import ProfileImageUploadClaim

    worker, gateway, _, _, core, _ = context
    upload_path = tmp_path / "profile.png"
    upload_path.write_bytes(b"image")
    task_id = UUID(int=10)
    core.upload_tasks = [ProfileImageUploadClaim(
        task_id, str(upload_path), "profile.png", "image/png", 1, LEASE, 1
    )]

    worker.run_once()

    assert gateway.uploaded_images == [(str(upload_path), "image/png")]
    assert core.upload_completions == [(
        task_id, "worker-a", LEASE,
        "https://cdn.example.com/uploaded.png", NOW,
    )]
    assert not upload_path.exists()


def test_worker_reports_profile_image_upload_failure_and_removes_temp_file(
    context, tmp_path
):
    from dzmm_bot.browser.core_client import ProfileImageUploadClaim

    worker, gateway, _, _, core, _ = context
    upload_path = tmp_path / "profile.webp"
    upload_path.write_bytes(b"image")
    gateway.upload_error = RuntimeError("platform rejected upload")
    task_id = UUID(int=11)
    core.upload_tasks = [ProfileImageUploadClaim(
        task_id, str(upload_path), "profile.webp", "image/webp", 1, LEASE, 1
    )]

    worker.run_once()

    assert core.upload_completions == []
    assert core.upload_failures == [(
        task_id, "worker-a", LEASE, "upload_failed", NOW,
    )]
    assert not upload_path.exists()


def test_worker_keeps_profile_image_temp_file_when_completion_is_rejected(
    context, tmp_path
):
    from dzmm_bot.browser.core_client import ProfileImageUploadClaim

    worker, _, _, _, core, _ = context
    upload_path = tmp_path / "profile.png"
    upload_path.write_bytes(b"image")
    core.upload_completion_accepted = False
    core.upload_tasks = [ProfileImageUploadClaim(
        UUID(int=13), str(upload_path), "profile.png", "image/png", 1, LEASE, 1
    )]

    worker.run_once()

    assert upload_path.exists()


def test_worker_removes_superseded_profile_image_temp_file(context, tmp_path):
    from dzmm_bot.browser.core_client import ProfileImageCleanupClaim

    worker, _, _, _, core, _ = context
    upload_path = tmp_path / "superseded.png"
    upload_path.write_bytes(b"image")
    task_id = UUID(int=12)
    core.upload_cleanup_tasks = [ProfileImageCleanupClaim(
        task_id, str(upload_path), LEASE
    )]

    worker.run_once()

    assert not upload_path.exists()
    assert core.upload_cleanups == [(task_id, "worker-a", LEASE, NOW)]


def test_worker_retries_socket_timeout_with_the_same_platform_message_id(context):
    worker, gateway, _, _, core, _ = context
    outbound = OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)
    core.pending = [outbound]
    gateway.send_errors = [SocketTimeoutError()]

    worker.run_once()

    assert core.released_event.wait(timeout=1)
    assert core.released == [(OUTBOUND_ID, "worker-a", LEASE, NOW)]

    core.pending = [outbound]
    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert gateway.sent_message_ids == [str(OUTBOUND_ID), str(OUTBOUND_ID)]


def test_worker_reconnects_socket_on_main_loop_after_outbound_timeout(context):
    """Fails if a sender thread closes the shared socket itself."""
    worker, gateway, _, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]
    gateway.send_error = SocketTimeoutError()

    worker.run_once()
    assert core.released_event.wait(timeout=1)

    assert gateway.close_count == 0

    gateway.send_error = None
    worker.run_once()

    assert gateway.close_count == 1
    assert len(core.heartbeats) == 2


def test_worker_contains_completed_outbound_confirmation_failure(context):
    """Fails if a completed sender Future can terminate the Worker main loop."""
    worker, _, _, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]
    core.confirm_error = RuntimeError("core confirmation failed")

    worker.run_once()
    future = next(iter(worker._outbound_futures.values()))
    with pytest.raises(RuntimeError, match="core confirmation failed"):
        future.result(timeout=1)

    worker.run_once()

    assert len(core.heartbeats) == 2


def test_worker_contains_main_thread_socket_close_failure(context):
    """Fails if a reconnect teardown exception terminates the Worker loop."""
    worker, gateway, _, _, core, _ = context
    core.pending = [OutboundClaim(OUTBOUND_ID, "in-1", "reply", LEASE)]
    gateway.send_error = SocketTimeoutError()

    worker.run_once()
    assert core.released_event.wait(timeout=1)
    gateway.close_error = RuntimeError("disconnect failed")

    worker.run_once()

    assert gateway.close_count == 1
    assert len(core.heartbeats) == 2


def test_worker_drains_at_most_twenty_outbounds_in_order(context):
    worker, gateway, _, _, core, _ = context
    core.pending = [
        OutboundClaim(UUID(int=index), f"in-{index}", f"reply-{index}", LEASE)
        for index in range(1, 26)
    ]

    worker.run_once()

    assert gateway.sent == [f"reply-{index}" for index in range(1, 21)]
    assert [confirmed[0] for confirmed in core.confirmed] == [
        UUID(int=index) for index in range(1, 21)
    ]
    assert [outbound.id for outbound in core.pending] == [
        UUID(int=index) for index in range(21, 26)
    ]


def test_worker_sends_different_direct_rooms_concurrently():
    gateway = FakeGateway()
    gateway.direct_send_release = Event()
    core = FakeCore(pending=[
        OutboundClaim(
            UUID(int=101), "in-a", "A", LEASE,
            destination_chatroom_id="direct-a", delivery_key="direct-a",
            delivery_kind="direct",
        ),
        OutboundClaim(
            UUID(int=102), "in-b", "B", LEASE,
            destination_chatroom_id="direct-b", delivery_key="direct-b",
            delivery_kind="direct",
        ),
    ])
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=FakeSession(gateway),
        desktop=FakeDesktop(),
        clock=lambda: NOW,
        outbound_concurrency=2,
    )

    worker.run_once()

    assert gateway.direct_send_started.wait(timeout=1)
    gateway.direct_send_release.set()
    deadline = monotonic() + 1
    while len(core.confirmed) < 2 and monotonic() < deadline:
        sleep(0.01)
    assert {item[0] for item in core.confirmed} == {UUID(int=101), UUID(int=102)}


def test_worker_passes_trigger_reference_to_gateway(context):
    worker, gateway, _, _, core, _ = context
    core.pending = [OutboundClaim(
        OUTBOUND_ID,
        "in-1",
        "余额：5 摸鱼币",
        LEASE,
        reference_message_id="platform-trigger-1",
        reference_sender_platform_id="employee-1",
        reference_content_type="text",
        reference_text="/余额",
    )]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert gateway.sent_references == [MessageReference(
        message_id="platform-trigger-1",
        sender_platform_id="employee-1",
        content_type="text",
        text="/余额",
    )]


def test_worker_stops_outbound_batch_when_time_budget_is_reached():
    gateway = FakeGateway()
    session = FakeSession(gateway)
    core = FakeCore(
        pending=[
            OutboundClaim(UUID(int=index), f"in-{index}", f"reply-{index}", LEASE)
            for index in range(1, 21)
        ]
    )
    ticks = iter((0.0, 0.0, 0.7, 1.4, 2.0))
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=FakeDesktop(),
        clock=lambda: NOW,
        monotonic=lambda: next(ticks),
    )

    worker.run_once()

    assert gateway.sent == ["reply-1", "reply-2", "reply-3"]
    assert len(core.pending) == 17


def test_worker_uses_bot_api_for_group_replies_over_the_newline_limit(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "\n".join(f"第{index}行" for index in range(12))
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", text, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-1",
    )]

    worker.run_once()

    assert bot_sender.sent_to == [("group-1", text)]
    assert gateway.sent == []
    assert core.confirmed == [(OUTBOUND_ID, "worker-a", LEASE, "bot-1", NOW)]


def test_worker_falls_back_to_browser_chunks_when_bot_is_not_in_group(context):
    worker, gateway, session, _, core, _ = context
    bot_sender = FakeBotSender(
        send_error=DzmmBotSendError("Bot is not a member of this chatroom")
    )
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=FakeDesktop(),
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    lines = [f"第{index}行" for index in range(12)]
    text = "\n".join(lines)
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", text, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-2",
    )]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert bot_sender.sent_to == [("group-2", text)]
    assert gateway.sent_to == [
        ("group-2", "\n".join(lines[:11])),
        ("group-2", lines[11]),
    ]
    assert len(set(gateway.sent_message_ids)) == 2
    assert all(gateway.sent_message_ids)
    assert core.failed == []
    assert core.released == []
    assert session.stops == 0
    assert worker.login_state is LoginState.READY


def test_worker_falls_back_to_browser_chunks_when_bot_requires_captcha(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender(send_error=DzmmBotSendError("captcha_required"))
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "字" * 1001
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", text, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-2",
    )]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    worker.run_once()
    assert bot_sender.sent_to == [("group-2", text)]
    assert gateway.sent_to == [("group-2", "字" * 1000), ("group-2", "字")]
    assert core.bot_delivery_heartbeats[-1] == (
        "captcha_required",
        "captcha_required",
    )
    assert core.failed == []
    assert core.released == []
    assert session.stops == 0
    assert worker.login_state is LoginState.READY


def test_worker_skips_bot_after_captcha_until_the_status_is_rechecked(context):
    """Fails if every long message retries a Bot sender already marked CAPTCHA-blocked."""
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender(send_error=DzmmBotSendError("captcha_required"))
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    first = OutboundClaim(
        OUTBOUND_ID, "in-1", "字" * 1001, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-2",
    )
    second = OutboundClaim(
        UUID("00000000-0000-0000-0000-000000000004"), "in-2", "字" * 1001,
        LEASE, group_chat_id=GROUP_ID, destination_chatroom_id="group-2",
    )

    worker._send_outbound(gateway, first)
    worker._send_outbound(gateway, second)

    assert bot_sender.sent_to == [("group-2", "字" * 1001)]
    assert gateway.sent_to == [
        ("group-2", "字" * 1000), ("group-2", "字"),
        ("group-2", "字" * 1000), ("group-2", "字"),
    ]


def test_worker_keeps_group_replies_within_platform_limits_on_the_browser_gateway(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "\n".join(f"第{index}行" for index in range(11))
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", text, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-1",
    )]

    worker.run_once()

    assert bot_sender.sent_to == []
    assert gateway.sent_to == [("group-1", text)]


def test_worker_uses_bot_api_for_group_replies_over_the_character_limit(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "字" * 1001
    core.pending = [OutboundClaim(
        OUTBOUND_ID, "in-1", text, LEASE,
        group_chat_id=GROUP_ID, destination_chatroom_id="group-1",
    )]

    worker.run_once()

    assert bot_sender.sent_to == [("group-1", text)]
    assert gateway.sent == []


def test_worker_routes_referenced_long_reply_through_bot_without_reply_metadata(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "字" * 1001
    core.pending = [OutboundClaim(
        OUTBOUND_ID,
        "in-1",
        text,
        LEASE,
        group_chat_id=GROUP_ID,
        destination_chatroom_id="group-1",
        reference_message_id="trigger-1",
        reference_sender_platform_id="employee-1",
        reference_content_type="text",
        reference_text="@总监事 介绍玩法",
    )]

    worker.run_once()

    assert core.confirmed_event.wait(timeout=1)
    assert bot_sender.sent_to == [("group-1", text)]
    assert gateway.sent == []


def test_worker_keeps_recalled_group_replies_on_the_browser_gateway(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    text = "\n".join(f"第{index}行" for index in range(12))
    core.pending = [
        OutboundClaim(
            OUTBOUND_ID,
            "in-1",
            text,
            LEASE,
            group_chat_id=GROUP_ID,
            destination_chatroom_id="group-1",
            recall_after_seconds=3,
        )
    ]

    worker.run_once()

    assert bot_sender.sent_to == []
    assert gateway.sent_to == [("group-1", text)]


def test_worker_keeps_direct_messages_on_the_browser_gateway(context):
    _, gateway, session, desktop, core, _ = context
    bot_sender = FakeBotSender()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    core.pending = [
        OutboundClaim(
            OUTBOUND_ID,
            None,
            "咖啡",
            LEASE,
            destination_chatroom_id="direct-1",
            delivery_kind="undercover_card",
        )
    ]

    worker.run_once()

    assert bot_sender.sent_to == []
    assert gateway.sent_to == [("direct-1", "咖啡")]


def test_worker_sends_targeted_claims_without_scanning_historical_direct_rooms(context):
    worker, gateway, _, _, core, _ = context
    core.pending = [
        OutboundClaim(
            OUTBOUND_ID,
            None,
            "你的身份：卧底。词语：咖啡",
            LEASE,
            destination_chatroom_id="direct-1",
            delivery_kind="undercover_card",
        )
    ]

    worker.run_once()

    assert core.direct_chat_syncs == []
    assert gateway.sent == []
    assert gateway.sent_to == [("direct-1", "你的身份：卧底。词语：咖啡")]
    assert core.confirmed == [(OUTBOUND_ID, "worker-a", LEASE, "direct-1", NOW)]


def test_worker_retracts_a_due_outbound_with_current_fencing_values(context):
    worker, gateway, _, _, core, _ = context
    core.pending_recalls = [
        OutboundRecallClaim(
            OUTBOUND_ID, "platform-message", LEASE,
            destination_chatroom_id="group-2",
        )
    ]

    worker.run_once()

    assert gateway.retracted == ["platform-message"]
    assert gateway.retracted_to == [("platform-message", "group-2")]
    assert core.recalls_confirmed == [(OUTBOUND_ID, "worker-a", LEASE, NOW)]


def test_worker_stops_retrying_a_recall_when_the_gateway_rejects_it(context):
    """Fails if a rejected recall lease is left claimable forever."""
    worker, gateway, _, _, core, _ = context
    gateway.retract_error = RuntimeError("服务器内部错误")
    core.pending_recalls = [OutboundRecallClaim(OUTBOUND_ID, "platform-message", LEASE)]

    worker.run_once()

    assert core.recalls_failed == [(OUTBOUND_ID, "worker-a", LEASE, NOW)]
    assert core.recalls_confirmed == []


def test_paused_worker_still_heartbeats_and_polls_commands(context):
    worker, gateway, _, _, core, _ = context
    core.commands = [WorkerCommand(COMMAND_ID, "pause_listening", LEASE)]
    gateway.messages = [InboundMessage("p-1", "u-1", "/test", NOW)]

    worker.run_once()
    worker.run_once()

    assert len(core.heartbeats) == 2
    assert core.completions == [
        (COMMAND_ID, "worker-a", LEASE, "completed", NOW)
    ]
    assert core.submitted_ids == []


@pytest.mark.parametrize(
    ("command", "expected_starts", "expected_stops", "desktop_starts", "desktop_stops"),
    [
        ("restart_browser", 1, 1, 0, 0),
        ("start_auth", 0, 1, 1, 0),
        ("finish_auth", 1, 0, 0, 0),
    ],
)
def test_lifecycle_commands_touch_only_the_expected_processes(
    context, command, expected_starts, expected_stops, desktop_starts, desktop_stops
):
    worker, _, session, desktop, core, _ = context
    core.commands = [WorkerCommand(COMMAND_ID, command, LEASE)]

    worker.run_once()

    assert (session.starts, session.stops) == (expected_starts, expected_stops)
    assert (desktop.starts, desktop.stops) == (desktop_starts, desktop_stops)


def test_bot_verification_marks_auth_required_before_starting_desktop(context):
    _, _, session, _, core, _ = context

    class StateCheckingDesktop(FakeDesktop):
        worker = None

        def start(self):
            assert self.worker.login_state is LoginState.AUTH_REQUIRED
            super().start()

    desktop = StateCheckingDesktop()
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=FakeBotSender(),
    )
    desktop.worker = worker
    core.commands = [WorkerCommand(COMMAND_ID, "start_auth", LEASE)]

    worker.run_once()

    assert worker.login_state is LoginState.AUTH_IN_PROGRESS
    assert core.completions == [
        (COMMAND_ID, "worker-a", LEASE, "completed", NOW)
    ]


@pytest.mark.parametrize("command", ["restart_browser", "finish_auth"])
def test_lifecycle_commands_restore_the_realtime_message_handler(context, command):
    worker, gateway, _, _, core, _ = context
    core.commands = [WorkerCommand(COMMAND_ID, command, LEASE)]

    worker.run_once()

    assert gateway.message_handler == worker._queue_inbound


def test_finishing_verification_rechecks_bot_delivery_on_the_next_long_message(context):
    _, _, session, desktop, core, _ = context
    bot_sender = FakeBotSender(send_error=DzmmBotSendError("captcha_required"))
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
        bot_sender=bot_sender,
    )
    core.pending = [OutboundClaim(
        OUTBOUND_ID,
        "in-1",
        "字" * 1001,
        LEASE,
        group_chat_id=GROUP_ID,
        destination_chatroom_id="group-2",
    )]
    worker.run_once()
    assert core.confirmed_event.wait(timeout=1)
    core.commands = [WorkerCommand(COMMAND_ID, "finish_auth", LEASE)]

    worker.run_once()

    assert core.bot_delivery_heartbeats[-1] == ("unknown", None)


def test_cancel_auth_closes_desktop_and_restores_the_persisted_browser(context):
    worker, _, session, desktop, core, _ = context
    core.commands = [
        WorkerCommand(COMMAND_ID, "start_auth", LEASE),
        WorkerCommand(UUID(int=4), "cancel_auth", UUID(int=5)),
    ]

    worker.run_once()
    worker.run_once()

    assert (desktop.starts, desktop.stops) == (1, 1)
    assert (session.starts, session.stops) == (1, 2)
    assert worker.login_state is LoginState.READY


def test_cancel_auth_stops_the_browser_session_before_the_desktop():
    events = []
    gateway = FakeGateway()

    class OrderedSession(FakeSession):
        def stop(self):
            events.append("session")
            super().stop()

    class OrderedDesktop(FakeDesktop):
        def stop(self):
            events.append("desktop")
            super().stop()

    session = OrderedSession(gateway)
    desktop = OrderedDesktop()
    core = FakeCore()
    core.commands = [
        WorkerCommand(COMMAND_ID, "start_auth", LEASE),
        WorkerCommand(UUID(int=4), "cancel_auth", UUID(int=5)),
    ]
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
    )

    worker.run_once()
    events.clear()
    worker.run_once()

    assert events == ["session", "desktop"]


def test_cancel_auth_attempts_desktop_cleanup_when_session_stop_fails():
    gateway = FakeGateway()

    class FailingSecondStopSession(FakeSession):
        def stop(self):
            super().stop()
            if self.stops == 2:
                raise RuntimeError("session stop failed")

    session = FailingSecondStopSession(gateway)
    desktop = FakeDesktop()
    core = FakeCore()
    core.commands = [
        WorkerCommand(COMMAND_ID, "start_auth", LEASE),
        WorkerCommand(UUID(int=4), "cancel_auth", UUID(int=5)),
    ]
    worker = BrowserWorker(
        worker_id="worker-a",
        core=core,
        session=session,
        desktop=desktop,
        clock=lambda: NOW,
    )

    worker.run_once()
    worker.run_once()

    assert desktop.stops == 1
    assert core.completions[-1] == (
        UUID(int=4),
        "worker-a",
        UUID(int=5),
        "failed",
        NOW,
    )
    assert worker.login_state is LoginState.READY


def test_authentication_loss_transitions_once_and_backs_off_bounded(context):
    worker, gateway, _, _, core, sleeps = context
    gateway.authenticated = False

    for _ in range(8):
        worker.run_once()

    assert core.audits == [("authentication_lost", "worker-a", NOW)]
    assert core.submitted_ids == []
    assert all(
        state is LoginState.AUTH_REQUIRED
        for _, state, _, _, _ in core.heartbeats
    )
    assert sleeps == [1, 2, 2, 2, 2, 2, 2, 2]


def test_resume_listening_allows_polling_again(context):
    worker, gateway, _, _, core, _ = context
    gateway.messages = [InboundMessage("p-1", "u-1", "/test", NOW)]
    core.commands = [
        WorkerCommand(COMMAND_ID, "pause_listening", LEASE),
        WorkerCommand(UUID(int=4), "resume_listening", UUID(int=5)),
    ]

    worker.run_once()
    worker.run_once()

    assert core.submitted_ids == ["p-1"]


def test_retract_test_command_withdraws_its_own_test_message(context):
    worker, gateway, _, _, core, _ = context
    core.commands = [WorkerCommand(COMMAND_ID, "retract_test", LEASE)]

    worker.run_once()

    assert gateway.sent == ["【撤回验证】这条消息会立即撤回。"]
    assert gateway.retracted == ["sent-1"]
    assert core.completions == [
        (COMMAND_ID, "worker-a", LEASE, "completed", NOW)
    ]
