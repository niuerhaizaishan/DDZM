from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID


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
