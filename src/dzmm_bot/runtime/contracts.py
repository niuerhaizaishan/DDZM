from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class LoginState(StrEnum):
    READY = "ready"
    AUTH_REQUIRED = "auth_required"
    AUTH_IN_PROGRESS = "auth_in_progress"


@dataclass(frozen=True)
class MessageReference:
    message_id: str
    sender_platform_id: str
    content_type: str
    image_url: str | None = None
    alt: str | None = None
    width: int | None = None
    height: int | None = None
    blurhash: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class InboundMessage:
    platform_message_id: str
    sender_platform_id: str
    content: str
    received_at: datetime
    source_type: str = "group"
    chatroom_id: str | None = None
    reference: MessageReference | None = None


@dataclass(frozen=True)
class DirectChatRoom:
    platform_user_id: str
    chatroom_id: str


@dataclass(frozen=True)
class GroupChatTarget:
    group_chat_id: UUID
    chatroom_id: str
    chat_url: str


@dataclass(frozen=True)
class GroupChatRuntimeUpdate:
    group_chat_id: UUID
    connection_state: str
    last_connected_at: datetime | None = None
    last_inbound_at: datetime | None = None
    last_outbound_at: datetime | None = None
    last_error_summary: str | None = None


@dataclass(frozen=True)
class OutboundMessage:
    inbound_message_id: str
    text: str
    content_type: str = "text"
    image_url: str | None = None
    image_alt: str | None = None
    id: UUID = field(default_factory=uuid4)
    status: str = "pending"
    lease_worker_id: str | None = None
    lease_token: UUID | None = None
    lease_expires_at: datetime | None = None
    attempt_count: int = 0
    platform_sent_id: str | None = None
    destination_chatroom_id: str | None = None
    delivery_key: str = "__group__"
    delivery_kind: str = "group"
    reference_message_id: str | None = None
    reference_sender_platform_id: str | None = None
    reference_content_type: str | None = None
    reference_text: str | None = None


@dataclass(frozen=True)
class WorkerHeartbeat:
    worker_id: str
    login_state: LoginState
    recorded_at: datetime
    listening: bool = True
