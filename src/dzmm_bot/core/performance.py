from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from .schema import BEIJING


PERFORMANCE_ACTIVE_STATES = frozenset(
    {"pending_review", "approved", "previewed", "waiting", "performing", "tipping"}
)
PERFORMANCE_STAGE_STATES = frozenset({"performing", "tipping"})
_POSTPONEMENT_PATTERN = re.compile(r"^(?P<amount>[1-9]\d*)(?P<unit>[mhd])$")


@dataclass(frozen=True)
class PerformanceExtensionView:
    id: UUID
    reservation_id: UUID
    duration_minutes: int
    original_scheduled_at: datetime
    proposed_scheduled_at: datetime
    state: str
    rejection_reason: str | None
    requested_at: datetime
    reviewed_at: datetime | None


@dataclass(frozen=True)
class PerformanceTipView:
    sender_display_name: str
    recipient_display_name: str
    amount: int
    created_at: datetime


@dataclass(frozen=True)
class PerformanceAuditView:
    event_type: str
    actor: str | None
    payload: dict[str, Any]
    created_at: datetime


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
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    rejection_reason: str | None = None
    cancellation_reason: str | None = None
    cancelled_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    tips: tuple[PerformanceTipView, ...] = ()
    audit_events: tuple[PerformanceAuditView, ...] = ()
    extension: PerformanceExtensionView | None = None


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
class PerformancePostponementResult:
    status: str
    request: PerformanceExtensionView | None = None
    reservation: PerformanceView | None = None


@dataclass(frozen=True)
class PerformanceTipResult:
    status: str
    sender_display_name: str | None = None
    recipient_display_name: str | None = None
    amount: int | None = None
    sender_balance: int | None = None
    recipient_balance: int | None = None


@dataclass(frozen=True)
class PerformanceSettings:
    maximum_duration_minutes: int
    version: int


@dataclass(frozen=True)
class ValidatedCover:
    url: str
    mime_type: str
    byte_size: int


def parse_postponement(value: str) -> timedelta:
    match = _POSTPONEMENT_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("延期格式应为 /延期 30m、/延期 1h 或 /延期 1d")
    factor = {"m": 1, "h": 60, "d": 1440}[match.group("unit")]
    return timedelta(minutes=int(match.group("amount")) * factor)


def render_performance_preview(view: PerformanceView) -> str:
    return (
        "【公演即将开始】\n"
        f"公演：{view.title}\n"
        f"简介：{view.introduction}\n"
        f"时间：{view.scheduled_at.strftime('%Y/%m/%d-%H:%M:%S')}\n"
        f"参演人员：{'、'.join(view.participant_names)}"
    )


def render_performance_opening(view: PerformanceView) -> str:
    return (
        "-------------------------演出开始-----------------------\n"
        f"公演：{view.title}\n"
        f"简介：{view.introduction}\n"
        f"参演人员：{'、'.join(view.participant_names)}"
    )


def render_performance_tipping_open(view: PerformanceView) -> str:
    return (
        f"公演《{view.title}》演出部分已结束，进入 180 秒打赏环节。\n"
        "仅开放 /打赏 参演人员名称 金额，或回复参演人员本场消息发送 /打赏 金额。"
    )


def render_performance_settlement(
    total: int,
    participant_totals: tuple[tuple[str, int], ...],
    top_tips: tuple[tuple[str, str, int], ...],
    currency_name: str,
) -> str:
    participant_lines = "\n".join(
        f"{name}：{amount} {currency_name}" for name, amount in participant_totals
    )
    top_lines = "\n".join(
        f"{index}. {sender} → {recipient}：{amount} {currency_name}"
        for index, (sender, recipient, amount) in enumerate(top_tips, 1)
    )
    if not top_lines:
        top_lines = "本场无人打赏。"
    return (
        "公演打赏结束\n"
        f"总打赏：{total} {currency_name}\n\n"
        f"参演人员：\n{participant_lines}\n\n"
        f"最高打赏明细：\n{top_lines}\n\n"
        "-------------------------演出结束-----------------------"
    )


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


def parse_performance_datetime(value: str, now: datetime) -> datetime:
    try:
        parsed = datetime.strptime(
            value.strip(), "%Y/%m/%d-%H:%M:%S"
        ).replace(tzinfo=BEIJING)
    except ValueError as error:
        raise ValueError("公演时间格式应为 YYYY/MM/DD-HH:MM:SS") from error
    local_now = now.astimezone(BEIJING)
    if parsed < local_now + timedelta(minutes=30):
        raise ValueError("公演时间至少需要提前 30 分钟")
    if parsed > local_now + timedelta(days=30):
        raise ValueError("只能预约未来 30 天内的公演")
    return parsed


def parse_performance_participants(value: str) -> tuple[str, ...]:
    names = tuple(
        part.strip()
        for part in re.split(r"[、,，\n]+", value.strip())
        if part.strip()
    )
    if not 1 <= len(names) <= 30:
        raise ValueError("参演人员需要填写 1–30 名已入职员工")
    if len(set(names)) != len(names):
        raise ValueError("参演人员不能重复")
    return names
