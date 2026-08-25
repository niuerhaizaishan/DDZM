from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import logging
from threading import Event, Lock
from time import monotonic as default_monotonic, sleep as default_sleep
from typing import Protocol
from uuid import uuid5

from socketio.exceptions import TimeoutError as SocketTimeoutError

from dzmm_bot.runtime.contracts import (
    DirectChatRoom,
    GroupChatRuntimeUpdate,
    GroupChatTarget,
    InboundMessage,
    LoginState,
    MessageReference,
)
from dzmm_bot.runtime.outbound import group_message_chunks, requires_bot_group_sender

from .bot_api import DzmmBotSendError
from .core_client import CorePort, OutboundClaim, WorkerCommand
from .aikda_socket import AikdaAuthenticationError, AikdaMessageRejectedError
from .session import BrowserSession, ChatGateway


_LOGGER = logging.getLogger(__name__)
_DIRECT_ENTRY_COMMANDS = {
    "/上架暗网",
    "/取消上架",
    "/确认",
    "/报价",
    "/公开",
    "/不公开",
}
_OUTBOUND_BATCH_SIZE = 20
_OUTBOUND_BATCH_BUDGET_SECONDS = 2.0
_GROUP_TARGET_SYNC_INTERVAL_SECONDS = 5.0


class ManualDesktop(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class BotSender(Protocol):
    def send_to(self, chatroom_id: str, text: str) -> str: ...


class BrowserWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        core: CorePort,
        session: BrowserSession,
        desktop: ManualDesktop,
        clock: Callable[[], datetime] = lambda: datetime.now(ZoneInfo("Asia/Shanghai")),
        monotonic: Callable[[], float] = default_monotonic,
        sleep: Callable[[float], None] = default_sleep,
        lease_seconds: int = 30,
        bot_sender: BotSender | None = None,
        outbound_concurrency: int = 4,
    ) -> None:
        if not 1 <= outbound_concurrency <= 16:
            raise ValueError("outbound_concurrency must be between 1 and 16")
        self._worker_id = worker_id
        self._core = core
        self._session = session
        self._desktop = desktop
        self._clock = clock
        self._monotonic = monotonic
        self._sleep = sleep
        self._lease_seconds = lease_seconds
        self._bot_sender = bot_sender
        self._bot_delivery_status = (
            ("unknown", None) if bot_sender is not None else ("unconfigured", None)
        )
        self._gateway: ChatGateway | None = None
        self._listening = True
        self._login_state = LoginState.READY
        self._seen_message_ids: set[str] = set()
        self._auth_loss_reported = False
        self._auth_backoff = 1
        self._manual_auth_confirmed = False
        self._inbound_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="dzmm-inbound"
        )
        self._outbound_executor = ThreadPoolExecutor(
            max_workers=outbound_concurrency, thread_name_prefix="dzmm-outbound"
        )
        self._outbound_concurrency = outbound_concurrency
        self._outbound_futures: dict[str, Future[None]] = {}
        self._paused_messages: list[InboundMessage] = []
        self._paused_messages_lock = Lock()
        self._group_targets: tuple[GroupChatTarget, ...] = ()
        self._next_group_target_sync_at: datetime | None = None
        self._disabled_group_updates: list[GroupChatRuntimeUpdate] = []
        self._group_connected_at: dict[str, datetime] = {}
        self._group_last_inbound_at: dict[str, datetime] = {}
        self._group_last_outbound_at: dict[str, datetime] = {}
        self._gateway_reconnect_requested = Event()

    @property
    def login_state(self) -> LoginState:
        return self._login_state

    @property
    def browser_stopped(self) -> bool:
        return self._gateway is None

    def run_once(self) -> None:
        now = self._clock()
        self._sync_group_targets(now)
        self._reconnect_gateway_if_requested()
        command = self._core.claim_command(
            self._worker_id, now, self._lease_seconds
        )
        if command is not None:
            self._execute_command(command)

        transport_ready = True
        if self._login_state is not LoginState.AUTH_IN_PROGRESS:
            try:
                gateway = self._ensure_gateway()
                authenticated = gateway.is_authenticated()
            except AikdaAuthenticationError:
                _LOGGER.warning("browser authentication is no longer valid")
                self._recover_browser_session()
            except Exception:
                _LOGGER.exception("browser transport check failed")
                transport_ready = False
            else:
                if authenticated or self._manual_auth_confirmed:
                    self._login_state = LoginState.READY
                    self._auth_loss_reported = False
                    self._auth_backoff = 1
                else:
                    self._recover_browser_session()

        self._report_group_runtime(now)

        self._sync_listener_state()
        self._flush_paused_messages()

        if self._login_state is LoginState.AUTH_REQUIRED:
            self._core.run_daily_jobs(now)
            delay = self._auth_backoff
            self._auth_backoff = min(self._auth_backoff * 2, 2)
            self._sleep(delay)
            return
        if self._login_state is LoginState.AUTH_IN_PROGRESS:
            self._core.run_daily_jobs(now)
            return
        if not transport_ready:
            self._core.run_daily_jobs(now)
            return

        gateway = self._ensure_gateway()
        self._start_outbound_if_idle(gateway)
        self._process_profile_image_cleanup()
        self._process_profile_image_upload(gateway)
        if self._listening:
            try:
                direct_targets = self._core.direct_inbound_chatroom_ids()
                messages = gateway.read_new(direct_targets)
            except NotImplementedError:
                self._listening = False
                messages = []
            except AikdaAuthenticationError:
                _LOGGER.warning("browser message read detected authentication loss")
                self._recover_browser_session()
                self._sync_listener_state()
                return
            except Exception:
                _LOGGER.exception("browser message read failed")
                gateway.close()
                self._core.run_daily_jobs(now)
                return
            for message in messages:
                if message.platform_message_id in self._seen_message_ids:
                    continue
                self._queue_inbound(message)
                self._seen_message_ids.add(message.platform_message_id)

        self._core.run_daily_jobs(now)

        recall = self._core.claim_outbound_recall(
            self._worker_id, self._clock(), self._lease_seconds
        )
        if recall is not None:
            try:
                gateway.retract(recall.platform_sent_id)
            except Exception:
                _LOGGER.exception("outbound retraction failed: %s", recall.id)
            else:
                self._core.confirm_outbound_recalled(
                    recall.id,
                    self._worker_id,
                    recall.lease_token,
                    self._clock(),
                )

        self._maintain_recovery(gateway)

    def _process_profile_image_upload(self, gateway: ChatGateway) -> None:
        claim = self._core.claim_profile_image_upload(
            self._worker_id, self._clock(), self._lease_seconds
        )
        if claim is None:
            return
        path = Path(claim.temp_path)
        reported = False
        try:
            result = gateway.upload_image(path, claim.mime_type)
            image_url = result.get("url") if isinstance(result, dict) else None
            if not isinstance(image_url, str) or not image_url:
                raise ValueError("upload response missing image URL")
            reported = self._core.complete_profile_image_upload(
                claim.id, self._worker_id, claim.lease_token,
                image_url, self._clock(),
            )
        except Exception:
            _LOGGER.exception("profile image upload failed: %s", claim.id)
            try:
                reported = self._core.fail_profile_image_upload(
                    claim.id, self._worker_id, claim.lease_token,
                    "upload_failed", self._clock(),
                )
            except Exception:
                _LOGGER.exception("profile image upload failure report failed: %s", claim.id)
        finally:
            if reported:
                path.unlink(missing_ok=True)

    def _process_profile_image_cleanup(self) -> None:
        claim = self._core.claim_profile_image_cleanup(
            self._worker_id, self._clock(), self._lease_seconds
        )
        if claim is None:
            return
        try:
            Path(claim.temp_path).unlink(missing_ok=True)
        except OSError:
            _LOGGER.exception("profile image temp cleanup failed: %s", claim.id)
            return
        self._core.complete_profile_image_cleanup(
            claim.id, self._worker_id, claim.lease_token, self._clock()
        )

    def _queue_inbound(self, message: InboundMessage) -> None:
        if not self._listening:
            with self._paused_messages_lock:
                self._paused_messages.append(message)
            return
        self._inbound_executor.submit(self._dispatch_inbound, message)

    def _flush_paused_messages(self) -> None:
        if not self._listening:
            return
        with self._paused_messages_lock:
            messages, self._paused_messages = self._paused_messages, []
        for message in messages:
            self._inbound_executor.submit(self._dispatch_inbound, message)

    def _dispatch_inbound(self, message: InboundMessage) -> None:
        if message.source_type == "group" and message.chatroom_id is not None:
            self._group_last_inbound_at[message.chatroom_id] = self._clock()
        if message.source_type == "direct" and message.chatroom_id is not None:
            self._core.sync_direct_chats(
                [DirectChatRoom(message.sender_platform_id, message.chatroom_id)],
                self._clock(),
            )
            content = message.content.strip()
            command = content.split(maxsplit=1)[0] if content else ""
            if (
                content != "/投稿 随机事件"
                and command not in _DIRECT_ENTRY_COMMANDS
                and message.chatroom_id not in self._core.direct_inbound_chatroom_ids()
            ):
                return
        self._core.submit_inbound(message)

    def _start_outbound_if_idle(self, gateway: ChatGateway) -> None:
        for delivery_key, future in tuple(self._outbound_futures.items()):
            if not future.done():
                continue
            del self._outbound_futures[delivery_key]
            try:
                future.result()
            except Exception:
                _LOGGER.exception(
                    "outbound delivery task failed: %s", delivery_key
                )
        while len(self._outbound_futures) < self._outbound_concurrency:
            outbound = self._core.claim_outbound(
                self._worker_id,
                self._clock(),
                self._lease_seconds,
                tuple(self._outbound_futures),
            )
            if outbound is None:
                return
            delivery_key = outbound.delivery_key
            self._outbound_futures[delivery_key] = self._outbound_executor.submit(
                self._drain_outbound, gateway, outbound
            )

    def _drain_outbound(self, gateway: ChatGateway, outbound) -> None:
        started_at = self._monotonic()
        sent_count = 0
        while sent_count < _OUTBOUND_BATCH_SIZE:
            if self._monotonic() - started_at >= _OUTBOUND_BATCH_BUDGET_SECONDS:
                return
            if outbound is None:
                outbound = self._core.claim_outbound(
                    self._worker_id,
                    self._clock(),
                    self._lease_seconds,
                    required_delivery_key=delivery_key,
                )
                if outbound is None:
                    return
            delivery_key = outbound.delivery_key
            if not self._send_one_outbound(gateway, outbound):
                return
            sent_count += 1
            outbound = None

    def _send_one_outbound(self, gateway: ChatGateway, outbound) -> bool:
        try:
            platform_sent_id = self._send_outbound(gateway, outbound)
        except SocketTimeoutError:
            _LOGGER.warning("outbound acknowledgement timed out: %s", outbound.id)
            self._gateway_reconnect_requested.set()
            self._core.release_outbound(
                outbound.id,
                self._worker_id,
                outbound.lease_token,
                self._clock(),
            )
            return False
        except AikdaMessageRejectedError as error:
            _LOGGER.warning(
                "outbound send rejected: %s: %s", outbound.id, error
            )
            self._core.mark_outbound_failed(
                outbound.id,
                self._worker_id,
                outbound.lease_token,
                self._clock(),
            )
            return False
        except DzmmBotSendError as error:
            _LOGGER.warning("Bot API outbound send failed: %s: %s", outbound.id, error)
            self._core.mark_outbound_failed(
                outbound.id,
                self._worker_id,
                outbound.lease_token,
                self._clock(),
            )
            return False
        except Exception as error:
            if "请勿发送重复内容" in str(error):
                _LOGGER.warning("outbound content rejected as duplicate: %s", outbound.id)
                self._core.mark_outbound_failed(
                    outbound.id,
                    self._worker_id,
                    outbound.lease_token,
                    self._clock(),
                )
                return False
            _LOGGER.exception("outbound send failed: %s", outbound.id)
            self._gateway_reconnect_requested.set()
            self._core.release_outbound(
                outbound.id,
                self._worker_id,
                outbound.lease_token,
                self._clock(),
            )
            return False
        self._core.confirm_sent(
            outbound.id,
            self._worker_id,
            outbound.lease_token,
            platform_sent_id,
            self._clock(),
        )
        if outbound.destination_chatroom_id is not None:
            self._group_last_outbound_at[
                outbound.destination_chatroom_id
            ] = self._clock()
        return True

    def _sync_group_targets(self, now: datetime) -> None:
        if (
            self._next_group_target_sync_at is not None
            and now < self._next_group_target_sync_at
        ):
            return
        self._next_group_target_sync_at = now + timedelta(
            seconds=_GROUP_TARGET_SYNC_INTERVAL_SECONDS
        )
        try:
            targets = self._core.group_chat_targets()
            previous = {
                target.group_chat_id: target for target in self._group_targets
            }
            current_targets = {target.group_chat_id: target for target in targets}
            self._session.configure_group_chats(targets)
        except Exception:
            _LOGGER.exception("group chat target synchronization failed")
            return
        self._disabled_group_updates.extend(
            GroupChatRuntimeUpdate(group_id, "disabled")
            for group_id in previous.keys() - current_targets.keys()
        )
        self._group_targets = targets
        if self._gateway is not None:
            self._gateway.configure_group_rooms(targets)
        self._report_group_runtime(now)

    def _report_group_runtime(self, now: datetime) -> None:
        states: dict[str, tuple[str, str | None]] = {}
        if self._gateway is not None:
            try:
                states = self._gateway.group_room_states()
            except Exception:
                _LOGGER.exception("group chat runtime state read failed")
        updates = list(self._disabled_group_updates)
        for target in self._group_targets:
            state, error = states.get(target.chatroom_id, ("pending", None))
            if self._login_state is not LoginState.READY and state == "connected":
                state = "pending"
            if state == "connected":
                connected_at = self._group_connected_at.setdefault(
                    target.chatroom_id, now
                )
            else:
                connected_at = self._group_connected_at.get(target.chatroom_id)
            updates.append(
                GroupChatRuntimeUpdate(
                    target.group_chat_id,
                    state,
                    last_connected_at=connected_at,
                    last_inbound_at=self._group_last_inbound_at.get(
                        target.chatroom_id
                    ),
                    last_outbound_at=self._group_last_outbound_at.get(
                        target.chatroom_id
                    ),
                    last_error_summary=error,
                )
            )
        if not updates:
            return
        try:
            accepted = self._core.sync_group_chat_runtime(
                self._worker_id, tuple(updates), now
            )
        except Exception:
            _LOGGER.exception("group chat runtime synchronization failed")
            return
        if accepted:
            self._disabled_group_updates.clear()

    def _send_outbound(self, gateway: ChatGateway, outbound) -> str:
        platform_message_id = str(outbound.id)
        reference = self._outbound_reference(outbound)
        if outbound.content_type == "image":
            if outbound.image_url is None:
                raise RuntimeError("image outbound missing URL")
            if outbound.destination_chatroom_id is not None:
                return gateway.send_image_to(
                    outbound.destination_chatroom_id,
                    outbound.image_url,
                    alt=outbound.image_alt or "image",
                    message_id=platform_message_id,
                    reference=reference,
                )
            return gateway.send_image(
                outbound.image_url,
                alt=outbound.image_alt or "image",
                message_id=platform_message_id,
                reference=reference,
            )
        if (
            self._bot_sender is not None
            and outbound.destination_chatroom_id is not None
            and outbound.delivery_kind == "group"
            and outbound.recall_after_seconds is None
            and requires_bot_group_sender(outbound.text)
        ):
            try:
                message_id = self._bot_sender.send_to(
                    outbound.destination_chatroom_id, outbound.text
                )
                self._bot_delivery_status = ("ready", None)
                return message_id
            except DzmmBotSendError as error:
                if str(error).strip().lower() == "captcha_required":
                    self._bot_delivery_status = (
                        "captcha_required",
                        "captcha_required",
                    )
                _LOGGER.warning(
                    "Bot API group send failed for %s (%s); falling back to browser sender",
                    outbound.destination_chatroom_id,
                    error,
                )
                platform_message_id = ""
                for index, chunk in enumerate(group_message_chunks(outbound.text)):
                    platform_message_id = gateway.send_to(
                        outbound.destination_chatroom_id,
                        chunk,
                        message_id=str(uuid5(outbound.id, f"browser-fallback:{index}")),
                        reference=reference if index == 0 else None,
                    )
                return platform_message_id
        if (
            outbound.delivery_kind == "group"
            and outbound.group_chat_id is not None
            and outbound.destination_chatroom_id is None
        ):
            raise RuntimeError("group outbound missing destination chatroom")
        if outbound.destination_chatroom_id is not None:
            return gateway.send_to(
                outbound.destination_chatroom_id,
                outbound.text,
                message_id=platform_message_id,
                reference=reference,
            )
        return gateway.send(
            outbound.text, message_id=platform_message_id, reference=reference
        )

    @staticmethod
    def _outbound_reference(outbound) -> MessageReference | None:
        if (
            outbound.reference_message_id is None
            or outbound.reference_sender_platform_id is None
            or outbound.reference_content_type is None
        ):
            return None
        return MessageReference(
            message_id=outbound.reference_message_id,
            sender_platform_id=outbound.reference_sender_platform_id,
            content_type=outbound.reference_content_type,
            text=outbound.reference_text,
        )

    def _maintain_recovery(self, gateway: ChatGateway) -> None:
        try:
            gateway.maintain_recovery(
                self._core.direct_inbound_chatroom_ids()
            )
        except NotImplementedError:
            return
        except Exception:
            _LOGGER.exception("message recovery maintenance failed")

    def _reconnect_gateway_if_requested(self) -> None:
        if not self._gateway_reconnect_requested.is_set():
            return
        try:
            if self._gateway is not None:
                self._gateway.close()
        except Exception:
            _LOGGER.exception("socket reconnect teardown failed")
        finally:
            self._gateway_reconnect_requested.clear()

    def _ensure_gateway(self) -> ChatGateway:
        if self._gateway is None:
            self._gateway = self._configure_gateway(self._session.start_headless())
        return self._gateway

    def _configure_gateway(self, gateway: ChatGateway) -> ChatGateway:
        handler = getattr(gateway, "set_message_handler", None)
        if handler is not None:
            handler(self._queue_inbound)
        return gateway

    def _sync_listener_state(self) -> None:
        desired = self._core.heartbeat(
            self._worker_id,
            self._login_state,
            self._listening,
            self._clock(),
            account_display_name=(
                None
                if self._gateway is None
                else getattr(self._gateway, "account_display_name", None)
            ),
            bot_delivery_state=self._bot_delivery_status[0],
            bot_delivery_error=self._bot_delivery_status[1],
        )
        self._listening = desired and self._login_state is LoginState.READY

    def _transition_to_auth_required(self) -> None:
        self._login_state = LoginState.AUTH_REQUIRED
        self._listening = False
        if not self._auth_loss_reported:
            self._core.record_audit(
                "authentication_lost", self._worker_id, self._clock()
            )
            self._auth_loss_reported = True

    def _recover_browser_session(self) -> None:
        self._session.stop()
        self._gateway = None
        self._transition_to_auth_required()

    def _execute_command(self, command: WorkerCommand) -> None:
        status = "completed"
        try:
            if command.command == "pause_listening":
                self._listening = False
            elif command.command == "resume_listening":
                self._listening = True
            elif command.command == "restart_browser":
                self._session.stop()
                self._gateway = self._configure_gateway(self._session.start_headless())
            elif command.command == "start_auth":
                self._session.stop()
                self._gateway = None
                self._login_state = LoginState.AUTH_REQUIRED
                self._desktop.start()
                self._login_state = LoginState.AUTH_IN_PROGRESS
                self._listening = False
                self._manual_auth_confirmed = False
            elif command.command == "finish_auth":
                self._gateway = self._configure_gateway(self._session.attach_existing())
                self._login_state = LoginState.READY
                self._listening = True
                self._bot_delivery_status = (
                    ("unknown", None)
                    if self._bot_sender is not None
                    else ("unconfigured", None)
                )
                self._auth_loss_reported = False
                self._auth_backoff = 1
                self._manual_auth_confirmed = True
            elif command.command == "cancel_auth":
                try:
                    self._session.stop()
                finally:
                    self._gateway = None
                    self._desktop.stop()
                    self._login_state = LoginState.AUTH_REQUIRED
                    self._listening = True
                    self._manual_auth_confirmed = False
            elif command.command == "retract_test":
                gateway = self._ensure_gateway()
                platform_message_id = gateway.send("【撤回验证】这条消息会立即撤回。")
                gateway.retract(platform_message_id)
                _LOGGER.info("worker retraction test succeeded: %s", platform_message_id)
            else:
                raise ValueError(f"unsupported worker command: {command.command}")
        except Exception:
            _LOGGER.exception("worker command failed: %s", command.command)
            status = "failed"
        self._core.complete_command(
            command.id,
            self._worker_id,
            command.lease_token,
            status,
            self._clock(),
        )
