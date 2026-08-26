import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

import httpx

from dzmm_bot.runtime.contracts import (
    DirectChatRoom,
    GroupChatRuntimeUpdate,
    GroupChatTarget,
    InboundMessage,
    LoginState,
)


@dataclass(frozen=True)
class OutboundClaim:
    id: UUID
    inbound_message_id: str | None
    text: str
    lease_token: UUID
    group_chat_id: UUID | None = None
    content_type: str = "text"
    image_url: str | None = None
    image_alt: str | None = None
    destination_chatroom_id: str | None = None
    delivery_key: str = "__group__"
    delivery_kind: str = "group"
    reference_message_id: str | None = None
    reference_sender_platform_id: str | None = None
    reference_content_type: str | None = None
    reference_text: str | None = None
    recall_after_seconds: int | None = None


@dataclass(frozen=True)
class OutboundRecallClaim:
    id: UUID
    platform_sent_id: str
    lease_token: UUID


@dataclass(frozen=True)
class WorkerCommand:
    id: UUID
    command: str
    lease_token: UUID


@dataclass(frozen=True)
class ProfileImageUploadClaim:
    id: UUID
    temp_path: str
    original_filename: str
    mime_type: str
    expected_profile_version: int
    lease_token: UUID
    attempt_count: int


@dataclass(frozen=True)
class ProfileImageCleanupClaim:
    id: UUID
    temp_path: str
    lease_token: UUID


class CorePort(Protocol):
    def submit_inbound(self, message: InboundMessage) -> None: ...

    def run_daily_jobs(self, now: datetime) -> None: ...

    def sync_direct_chats(self, rooms: list[DirectChatRoom], now: datetime) -> None: ...

    def direct_inbound_chatroom_ids(self) -> tuple[str, ...]: ...

    def group_chat_targets(self) -> tuple[GroupChatTarget, ...]: ...

    def sync_group_chat_runtime(
        self,
        worker_id: str,
        updates: tuple[GroupChatRuntimeUpdate, ...],
        now: datetime,
    ) -> bool: ...

    def claim_profile_image_upload(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ProfileImageUploadClaim | None: ...

    def complete_profile_image_upload(
        self, task_id: UUID, worker_id: str, lease_token: UUID,
        result_url: str, now: datetime,
    ) -> bool: ...

    def fail_profile_image_upload(
        self, task_id: UUID, worker_id: str, lease_token: UUID,
        failure_summary: str, now: datetime,
    ) -> bool: ...

    def claim_profile_image_cleanup(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ProfileImageCleanupClaim | None: ...

    def complete_profile_image_cleanup(
        self, task_id: UUID, worker_id: str, lease_token: UUID, now: datetime
    ) -> bool: ...

    def claim_outbound(
        self,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        excluded_delivery_keys: tuple[str, ...] = (),
        required_delivery_key: str | None = None,
    ) -> OutboundClaim | None: ...

    def confirm_sent(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        platform_sent_id: str,
        now: datetime,
    ) -> None: ...

    def mark_outbound_failed(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None: ...

    def release_outbound(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None: ...

    def claim_outbound_recall(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> OutboundRecallClaim | None: ...

    def confirm_outbound_recalled(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None: ...

    def heartbeat(
        self,
        worker_id: str,
        login_state: LoginState,
        listening: bool,
        recorded_at: datetime,
        account_display_name: str | None = None,
        bot_delivery_state: str = "unknown",
        bot_delivery_error: str | None = None,
    ) -> bool: ...

    def claim_command(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> WorkerCommand | None: ...

    def complete_command(
        self,
        command_id: UUID,
        worker_id: str,
        lease_token: UUID,
        status: str,
        now: datetime,
    ) -> None: ...

    def record_audit(
        self, event_type: str, worker_id: str, recorded_at: datetime
    ) -> None: ...


class CoreClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"X-Core-Token": token},
            timeout=10,
        )
        self._logger = logging.getLogger(__name__)

    def submit_inbound(self, message: InboundMessage) -> None:
        reference = message.reference
        payload = {
            "platform_message_id": message.platform_message_id,
            "sender_platform_id": message.sender_platform_id,
            "content": message.content,
            "received_at": message.received_at.isoformat(),
            "source_type": message.source_type,
            "chatroom_id": message.chatroom_id,
        }
        if message.content_type == "image":
            payload.update(
                {
                    "content_type": message.content_type,
                    "image_url": message.image_url,
                    "image_alt": message.image_alt,
                    "image_width": message.image_width,
                    "image_height": message.image_height,
                }
            )
        if reference is not None:
            reference_payload = {
                "message_id": reference.message_id,
                "sender_platform_id": reference.sender_platform_id,
                "content_type": reference.content_type,
                "image_url": reference.image_url,
                "alt": reference.alt,
                "width": reference.width,
                "height": reference.height,
                "blurhash": reference.blurhash,
            }
            if reference.text is not None:
                reference_payload["text"] = reference.text
            payload["reference"] = reference_payload
        self._post(
            "/internal/inbound",
            payload,
        )

    def run_daily_jobs(self, now: datetime) -> None:
        self._post("/internal/daily-jobs/run", {"now": now.isoformat()})

    def sync_direct_chats(self, rooms: list[DirectChatRoom], now: datetime) -> None:
        self._post(
            "/internal/direct-chats/sync",
            {
                "rooms": [
                    {
                        "platform_user_id": room.platform_user_id,
                        "chatroom_id": room.chatroom_id,
                    }
                    for room in rooms
                ],
                "now": now.isoformat(),
            },
        )

    def direct_inbound_chatroom_ids(self) -> tuple[str, ...]:
        data = self._get("/internal/direct-inbound/rooms")
        return tuple(data["chatroom_ids"])

    def group_chat_targets(self) -> tuple[GroupChatTarget, ...]:
        return tuple(
            GroupChatTarget(
                group_chat_id=UUID(item["group_chat_id"]),
                chatroom_id=item["chatroom_id"],
                chat_url=item["chat_url"],
            )
            for item in self._get("/internal/group-chats/targets")
        )

    def sync_group_chat_runtime(
        self,
        worker_id: str,
        updates: tuple[GroupChatRuntimeUpdate, ...],
        now: datetime,
    ) -> bool:
        data = self._post(
            "/internal/group-chats/runtime",
            {
                "worker_id": worker_id,
                "statuses": [
                    {
                        "group_chat_id": str(item.group_chat_id),
                        "connection_state": item.connection_state,
                        "last_connected_at": _iso_or_none(item.last_connected_at),
                        "last_inbound_at": _iso_or_none(item.last_inbound_at),
                        "last_outbound_at": _iso_or_none(item.last_outbound_at),
                        "last_error_summary": item.last_error_summary,
                    }
                    for item in updates
                ],
                "now": now.isoformat(),
            },
        )
        return bool(data["accepted"])

    def claim_profile_image_upload(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ProfileImageUploadClaim | None:
        data = self._post(
            "/internal/profile-image-uploads/claim",
            _claim_payload(worker_id, now, lease_seconds),
        )
        if data is None:
            return None
        return ProfileImageUploadClaim(
            id=UUID(data["id"]),
            temp_path=data["temp_path"],
            original_filename=data["original_filename"],
            mime_type=data["mime_type"],
            expected_profile_version=data["expected_profile_version"],
            lease_token=UUID(data["lease_token"]),
            attempt_count=data["attempt_count"],
        )

    def complete_profile_image_upload(
        self, task_id: UUID, worker_id: str, lease_token: UUID,
        result_url: str, now: datetime,
    ) -> bool:
        data = self._post(
            f"/internal/profile-image-uploads/{task_id}/completed",
            {
                "worker_id": worker_id, "lease_token": str(lease_token),
                "result_url": result_url, "now": now.isoformat(),
            },
        )
        return bool(data["accepted"])

    def fail_profile_image_upload(
        self, task_id: UUID, worker_id: str, lease_token: UUID,
        failure_summary: str, now: datetime,
    ) -> bool:
        data = self._post(
            f"/internal/profile-image-uploads/{task_id}/failed",
            {
                "worker_id": worker_id, "lease_token": str(lease_token),
                "failure_summary": failure_summary, "now": now.isoformat(),
            },
        )
        return bool(data["accepted"])

    def claim_profile_image_cleanup(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> ProfileImageCleanupClaim | None:
        data = self._post(
            "/internal/profile-image-cleanups/claim",
            _claim_payload(worker_id, now, lease_seconds),
        )
        if data is None:
            return None
        return ProfileImageCleanupClaim(
            id=UUID(data["id"]),
            temp_path=data["temp_path"],
            lease_token=UUID(data["lease_token"]),
        )

    def complete_profile_image_cleanup(
        self, task_id: UUID, worker_id: str, lease_token: UUID, now: datetime
    ) -> bool:
        data = self._post(
            f"/internal/profile-image-cleanups/{task_id}/completed",
            {
                "worker_id": worker_id, "lease_token": str(lease_token),
                "now": now.isoformat(),
            },
        )
        return bool(data["accepted"])

    def claim_outbound(
        self,
        worker_id: str,
        now: datetime,
        lease_seconds: int,
        excluded_delivery_keys: tuple[str, ...] = (),
        required_delivery_key: str | None = None,
    ) -> OutboundClaim | None:
        payload = _claim_payload(worker_id, now, lease_seconds)
        payload["excluded_delivery_keys"] = list(excluded_delivery_keys)
        payload["required_delivery_key"] = required_delivery_key
        data = self._post(
            "/internal/outbound/claim",
            payload,
        )
        if data is None:
            return None
        return OutboundClaim(
            id=UUID(data["id"]),
            inbound_message_id=data["inbound_message_id"],
            text=data["text"],
            lease_token=UUID(data["lease_token"]),
            group_chat_id=(
                None
                if data.get("group_chat_id") is None
                else UUID(data["group_chat_id"])
            ),
            content_type=data["content_type"],
            image_url=data["image_url"],
            image_alt=data["image_alt"],
            destination_chatroom_id=data["destination_chatroom_id"],
            delivery_key=data.get("delivery_key") or data.get("destination_chatroom_id") or "__group__",
            delivery_kind=data["delivery_kind"],
            reference_message_id=data.get("reference_message_id"),
            reference_sender_platform_id=data.get("reference_sender_platform_id"),
            reference_content_type=data.get("reference_content_type"),
            reference_text=data.get("reference_text"),
            recall_after_seconds=data["recall_after_seconds"],
        )

    def confirm_sent(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        platform_sent_id: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/outbound/{message_id}/sent",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "platform_sent_id": platform_sent_id,
                "now": now.isoformat(),
            },
        )

    def mark_outbound_failed(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/outbound/{message_id}/failed",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "now": now.isoformat(),
            },
        )

    def release_outbound(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/outbound/{message_id}/retry",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "now": now.isoformat(),
            },
        )

    def claim_outbound_recall(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> OutboundRecallClaim | None:
        data = self._post(
            "/internal/outbound/recall/claim",
            _claim_payload(worker_id, now, lease_seconds),
        )
        if data is None:
            return None
        return OutboundRecallClaim(
            id=UUID(data["id"]),
            platform_sent_id=data["platform_sent_id"],
            lease_token=UUID(data["lease_token"]),
        )

    def confirm_outbound_recalled(
        self,
        message_id: UUID,
        worker_id: str,
        lease_token: UUID,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/outbound/{message_id}/recalled",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "now": now.isoformat(),
            },
        )

    def heartbeat(
        self,
        worker_id: str,
        login_state: LoginState,
        listening: bool,
        recorded_at: datetime,
        account_display_name: str | None = None,
        bot_delivery_state: str = "unknown",
        bot_delivery_error: str | None = None,
    ) -> bool:
        payload = {
            "worker_id": worker_id,
            "login_state": login_state.value,
            "listening": listening,
            "bot_delivery_state": bot_delivery_state,
            "bot_delivery_error": bot_delivery_error,
            "recorded_at": recorded_at.isoformat(),
        }
        if account_display_name is not None:
            payload["account_display_name"] = account_display_name
        response = self._post(
            "/internal/heartbeat",
            payload,
        )
        return bool(response["listening_desired"])

    def claim_command(
        self, worker_id: str, now: datetime, lease_seconds: int
    ) -> WorkerCommand | None:
        data = self._post(
            "/internal/worker-commands/claim",
            _claim_payload(worker_id, now, lease_seconds),
        )
        if data is None:
            return None
        return WorkerCommand(
            id=UUID(data["id"]),
            command=data["command"],
            lease_token=UUID(data["lease_token"]),
        )

    def complete_command(
        self,
        command_id: UUID,
        worker_id: str,
        lease_token: UUID,
        status: str,
        now: datetime,
    ) -> None:
        self._post(
            f"/internal/worker-commands/{command_id}/complete",
            {
                "worker_id": worker_id,
                "lease_token": str(lease_token),
                "status": status,
                "now": now.isoformat(),
            },
        )

    def record_audit(
        self, event_type: str, worker_id: str, recorded_at: datetime
    ) -> None:
        self._logger.warning(
            "browser audit event=%s worker_id=%s recorded_at=%s",
            event_type,
            worker_id,
            recorded_at.isoformat(),
        )

    def _post(self, path: str, payload: dict):
        response = self._client.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    def _get(self, path: str):
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()


def _claim_payload(worker_id: str, now: datetime, lease_seconds: int) -> dict:
    return {
        "worker_id": worker_id,
        "now": now.isoformat(),
        "lease_seconds": lease_seconds,
    }


def _iso_or_none(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
