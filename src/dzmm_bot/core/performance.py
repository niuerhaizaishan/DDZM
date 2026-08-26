from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx


PERFORMANCE_ACTIVE_STATES = frozenset(
    {"pending_review", "approved", "previewed", "waiting", "performing", "tipping"}
)
PERFORMANCE_STAGE_STATES = frozenset({"performing", "tipping"})


@dataclass(frozen=True)
class PerformanceView:
    id: UUID
    owner_platform_id: str
    owner_display_name: str
    group_chat_id: UUID
    title: str
    introduction: str
    scheduled_at: datetime
    event_date: date
    participant_names: tuple[str, ...]
    cover_url: str | None
    cover_alt: str | None
    state: str
    pre_notice_sent_at: datetime | None
    tipping_deadline: datetime | None


@dataclass(frozen=True)
class PerformanceDraftResult:
    status: str
    reservation: PerformanceView | None = None
    current_step: str | None = None
    direct_chatroom_id: str | None = None


@dataclass(frozen=True)
class PerformanceActionResult:
    status: str
    reservation: PerformanceView | None = None


@dataclass(frozen=True)
class PerformanceTipResult:
    status: str
    sender_display_name: str | None = None
    recipient_display_name: str | None = None
    amount: int | None = None


@dataclass(frozen=True)
class ValidatedCover:
    url: str
    mime_type: str
    byte_size: int


class CoverImageValidator(Protocol):
    def validate(self, url: str) -> ValidatedCover: ...


def detect_image_magic(body: bytes) -> str | None:
    if body.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if body.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(body) >= 12 and body.startswith(b"RIFF") and body[8:12] == b"WEBP":
        return "image/webp"
    return None


class HttpCoverImageValidator:
    def __init__(
        self, client: httpx.Client, max_bytes: int = 10 * 1024 * 1024
    ) -> None:
        self._client = client
        self._max_bytes = max_bytes

    def validate(self, url: str) -> ValidatedCover:
        parsed = urlsplit(url.strip())
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("公演封面必须使用 HTTPS 图片地址")
        with self._client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self._max_bytes:
                    raise ValueError("公演封面不能超过 10MB")
        mime_type = detect_image_magic(bytes(body))
        if mime_type is None:
            raise ValueError("公演封面仅支持 JPEG、PNG、WebP")
        return ValidatedCover(url=url, mime_type=mime_type, byte_size=len(body))
