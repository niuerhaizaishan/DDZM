# Performance Reservation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable, moderated public-performance reservation system with private guided submission, global daily scheduling, postponement approval, timed opening, stage chat control, real-currency tipping, and admin operations.

**Architecture:** Add an independent performance state machine and persistence model while reusing the existing group registry, direct-chat discovery, gameplay gate, outbound queue, balance ledger, scheduler, and admin shell. Keep parsing/rendering in a focused `performance.py` module, transactional state in `CoreRepository`, routing in `CoreService`/`GroupCommandHandler`, and management behind Core plus authenticated Admin APIs.

**Tech Stack:** Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL production, SQLite unit tests, httpx, vanilla JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-performance-reservation-design.md`

## Global Constraints

- All dates and deadlines use `Asia/Shanghai`.
- A reservation starts at least 30 minutes in the future and no more than 30 days in the future.
- All groups share one calendar; only one non-terminal performance can occupy a Beijing calendar date.
- One employee can own only one non-terminal reservation at a time.
- The private draft lasts 30 minutes and does not occupy a date until `/确认` succeeds.
- Title length is 1–50 characters, introduction length is 1–500 characters, and participant count is 1–30 unique joined employees.
- Cover is optional; accepted platform images must decode as JPEG, PNG, or WebP and contain no more than 10 MiB.
- Preview is sent 5 minutes before the scheduled start; pending review expires at that boundary.
- Tipping lasts exactly 180 seconds and has no fee.
- Maximum performance duration is configurable and defaults to 360 minutes.
- Existing Admin `super_admin` is the only backend role with board-only post-preview powers; ordinary authenticated admin accounts keep pre-preview review powers.
- Performance messages, observer chat, and tip commands never become conversational AI memory; each participant receives one stable completion fact.
- Do not deploy during implementation. Deployment requires a separate explicit user confirmation after full verification and review.
- Migration `20260826_57` must use the current `20260826_56` migration as `down_revision`; preserve every unrelated working-tree file.

## File Structure

- Create `src/dzmm_bot/core/performance.py`: status constants, input parsing, cover validation, fixed message rendering, and small immutable result types.
- Create `migrations/versions/20260826_57_performance_reservations.py`: all performance tables, indexes, settings seed, and `group_chats.performances_enabled`.
- Modify `src/dzmm_bot/core/schema.py`: ORM records only.
- Modify `src/dzmm_bot/core/repository.py`: all transactional reservation, review, scheduling, stage, tip, and deferral operations.
- Modify `src/dzmm_bot/core/service.py` and `src/dzmm_bot/core/commands.py`: inbound routing and player-facing commands.
- Modify `src/dzmm_bot/runtime/contracts.py`, Browser Socket/client files, and Core inbound API models: first-class inbound image messages.
- Modify Core/Admin API and the existing Admin template/JavaScript: review, settings, history, and board controls.
- Create `tests/core/test_performance_repository.py`, `tests/core/test_performance_commands.py`, and `tests/core/test_performance_scheduler.py`: focused state-machine coverage.
- Extend existing Browser/Core/Admin tests only where their fixtures and transport contracts already live.

---

### Task 1: Add the performance domain schema and migration

**Files:**
- Create: `src/dzmm_bot/core/performance.py`
- Create: `migrations/versions/20260826_57_performance_reservations.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Test: `tests/core/test_performance_repository.py`
- Test: `tests/deploy/test_performance_migration.py`

**Interfaces:**
- Produces: `PERFORMANCE_ACTIVE_STATES`, `PERFORMANCE_STAGE_STATES`, `PerformanceSettingsRecord`, `PerformanceReservationRecord`, `PerformanceParticipantRecord`, `PerformanceDraftRecord`, `PerformanceExtensionRequestRecord`, `PerformanceMessageRecord`, and `PerformanceTipRecord`.
- Produces immutable domain values `PerformanceView`, `PerformanceDraftResult`, `PerformanceActionResult`, and `PerformanceTipResult`; repository methods never return live ORM rows outside their transaction.
- Extends: `OutboundRecord` with `deferred_by_performance_id` and `performance_defer_key` so held announcements remain normal outbounds and existing outbound foreign keys stay valid.
- Produces: `GroupChatRecord.performances_enabled: bool` and a seeded setting with `maximum_duration_minutes=360`.

- [ ] **Step 1: Write failing ORM and migration tests**

```python
def test_performance_schema_enforces_one_live_date_and_one_live_owner(session):
    first = reservation(event_date=date(2026, 9, 1), owner_id=USER_A)
    session.add(first)
    session.flush()
    session.add(reservation(event_date=date(2026, 9, 1), owner_id=USER_B))
    with pytest.raises(IntegrityError):
        session.flush()


def test_migration_57_adds_performance_defaults(upgrade_from_56):
    upgrade_from_56("20260826_57")
    assert scalar("select maximum_duration_minutes from performance_settings") == 360
    assert scalar("select performances_enabled from group_chats limit 1") == 0
```

- [ ] **Step 2: Run the tests and verify the missing schema fails**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/deploy/test_performance_migration.py -q
```

Expected: failures naming the missing records, tables, or revision.

- [ ] **Step 3: Define status sets and ORM records**

```python
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


class PerformanceSettingsRecord(Base):
    __tablename__ = "performance_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    maximum_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=360)


class PerformanceReservationRecord(Base):
    __tablename__ = "performance_reservations"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    group_chat_id: Mapped[UUID] = mapped_column(ForeignKey("group_chats.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(50), nullable=False)
    introduction: Mapped[str] = mapped_column(String(500), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    cover_url: Mapped[str | None] = mapped_column(Text)
    cover_alt: Mapped[str | None] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    pre_notice_sent_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    tipping_started_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    tipping_deadline: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    maximum_duration_minutes_snapshot: Mapped[int | None] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(255))
    reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    cancellation_reason: Mapped[str | None] = mapped_column(String(500))
    cancelled_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
```

Define the remaining rows with these exact responsibilities:

```python
class PerformanceParticipantRecord(Base):
    __tablename__ = "performance_participants"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PerformanceDraftRecord(Base):
    __tablename__ = "performance_drafts"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    group_chat_id: Mapped[UUID] = mapped_column(ForeignKey("group_chats.id"), nullable=False)
    current_step: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_activity_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class PerformanceExtensionRequestRecord(Base):
    __tablename__ = "performance_extension_requests"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    requester_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    original_scheduled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    proposed_scheduled_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer: Mapped[str | None] = mapped_column(String(255))
    rejection_reason: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)


class PerformanceMessageRecord(Base):
    __tablename__ = "performance_messages"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)


class PerformanceTipRecord(Base):
    __tablename__ = "performance_tips"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("performance_reservations.id"), nullable=False
    )
    sender_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    recipient_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    inbound_message_id: Mapped[UUID] = mapped_column(
        ForeignKey("inbound_messages.id"), unique=True, nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
```

Add partial unique indexes for active `event_date`, active `owner_user_id`, and one stage-active performance per group. Add a partial unique pending-extension index and the unique participant/message/tip constraints. Use existing `AuditEventRecord` for admin action history.

Extend `OutboundRecord` with nullable `deferred_by_performance_id: UUID` and `performance_defer_key: str`, plus a partial unique index over `(deferred_by_performance_id, performance_defer_key)` when status is `held_performance` and the key is non-null.

- [ ] **Step 4: Implement migration 57**

```python
revision = "20260826_57"
down_revision = "20260826_56"


def upgrade() -> None:
    with op.batch_alter_table("group_chats") as batch:
        batch.add_column(
            sa.Column("performances_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "performance_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("maximum_duration_minutes", sa.Integer(), nullable=False),
    )
    op.bulk_insert(
        sa.table("performance_settings", sa.column("id"), sa.column("maximum_duration_minutes")),
        [{"id": 1, "maximum_duration_minutes": 360}],
    )
```

Create `performance_reservations`, `performance_participants`, `performance_drafts`, `performance_extension_requests`, `performance_messages`, and `performance_tips`. Add the two outbound deferral columns and partial indexes for live date, live owner, stage-active group, pending extension, and held keyed outbound. `downgrade()` drops the indexes, the six dependent tables, the settings table, the two outbound columns, and `group_chats.performances_enabled` in reverse dependency order.

- [ ] **Step 5: Run focused migration tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/deploy/test_performance_migration.py -q
git add src/dzmm_bot/core/performance.py src/dzmm_bot/core/schema.py migrations/versions/20260826_57_performance_reservations.py tests/core/test_performance_repository.py tests/deploy/test_performance_migration.py
git commit -m "feat: add performance reservation schema"
```

### Task 2: Carry private image messages through the Socket and validate covers

**Files:**
- Modify: `src/dzmm_bot/runtime/contracts.py`
- Modify: `src/dzmm_bot/browser/aikda_socket.py`
- Modify: `src/dzmm_bot/browser/core_client.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/core/performance.py`
- Modify: `src/dzmm_bot/core/service.py`
- Test: `tests/browser/test_aikda_socket.py`
- Test: `tests/browser/test_core_client.py`
- Test: `tests/core/test_app.py`
- Test: `tests/core/test_performance_commands.py`

**Interfaces:**
- Produces: extra `InboundMessage` fields `content_type`, `image_url`, `image_alt`, `image_width`, and `image_height`.
- Produces: `HttpCoverImageValidator.validate(url: str) -> ValidatedCover`.
- Consumes later: the draft handler receives a validated CDN URL, not raw bytes.

- [ ] **Step 1: Write failing transport tests for a direct image event**

```python
def test_socket_preserves_direct_image_as_inbound(gateway):
    payload = image_message("cover-1", "employee-1", "https://cdn.example/cover.webp")
    gateway.socket.trigger("message:new", {"chatroomId": "direct-1", "message": payload})
    [received] = gateway.adapter.read_new(("direct-1",))
    assert received.content_type == "image"
    assert received.image_url == "https://cdn.example/cover.webp"
    assert received.source_type == "direct"
```

Also assert malformed image URLs are discarded and existing text/reference behavior is unchanged.

- [ ] **Step 2: Run the transport tests and confirm images are currently dropped**

```bash
.venv/bin/pytest tests/browser/test_aikda_socket.py tests/browser/test_core_client.py tests/core/test_app.py -q -k 'image and inbound'
```

Expected: no inbound message is produced for the image payload.

- [ ] **Step 3: Extend the inbound contract without breaking positional callers**

```python
@dataclass(frozen=True)
class InboundMessage:
    platform_message_id: str
    sender_platform_id: str
    content: str
    received_at: datetime
    source_type: str = "group"
    chatroom_id: str | None = None
    reference: MessageReference | None = None
    content_type: str = "text"
    image_url: str | None = None
    image_alt: str | None = None
    image_width: int | None = None
    image_height: int | None = None
```

Update Socket parsing to accept `content.type in {"text", "image"}` and serialize these fields through Browser `CoreClient`, `InboundRequest`, and Core `create_app`. Store image inbound content as `[图片]` in `InboundRecord` while passing the structured fields to the performance draft handler.

- [ ] **Step 4: Write failing cover validation tests**

```python
@pytest.mark.parametrize("body,mime", [
    (b"\x89PNG\r\n\x1a\n" + b"x" * 8, "image/png"),
    (b"\xff\xd8\xff" + b"x" * 8, "image/jpeg"),
    (b"RIFF\x0c\x00\x00\x00WEBP" + b"x" * 4, "image/webp"),
])
def test_cover_validator_accepts_supported_magic(body, mime):
    assert validator_for(body).validate(HTTPS_URL).mime_type == mime


def test_cover_validator_stops_after_ten_mib():
    with pytest.raises(ValueError, match="10MB"):
        validator_for(b"\x89PNG\r\n\x1a\n" + b"x" * (10 * 1024 * 1024)).validate(HTTPS_URL)
```

- [ ] **Step 5: Implement bounded remote validation**

```python
@dataclass(frozen=True)
class ValidatedCover:
    url: str
    mime_type: str
    byte_size: int


class HttpCoverImageValidator:
    def __init__(self, client: httpx.Client, max_bytes: int = 10 * 1024 * 1024) -> None:
        self._client = client
        self._max_bytes = max_bytes

    def validate(self, url: str) -> ValidatedCover:
        if urlsplit(url).scheme != "https":
            raise ValueError("公演封面必须使用 HTTPS 图片地址")
        with self._client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > self._max_bytes:
                    raise ValueError("公演封面不能超过 10MB")
        mime_type = detect_image_magic(bytes(body))
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError("公演封面仅支持 JPEG、PNG、WebP")
        return ValidatedCover(url, mime_type, len(body))
```

Define `CoverImageValidator` as a one-method protocol and add optional `cover_image_validator` injection to `CoreService`; production `create_app` supplies one `HttpCoverImageValidator` backed by an `httpx.Client(timeout=5)`, while tests supply a fake or `httpx.MockTransport`. Disable redirects. The URL originates from a platform image message; never accept a URL typed as plain text.

- [ ] **Step 6: Run transport/validator tests and commit**

```bash
.venv/bin/pytest tests/browser/test_aikda_socket.py tests/browser/test_core_client.py tests/core/test_app.py tests/core/test_performance_commands.py -q -k 'image or cover'
git add src/dzmm_bot/runtime/contracts.py src/dzmm_bot/browser/aikda_socket.py src/dzmm_bot/browser/core_client.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/core/performance.py src/dzmm_bot/core/service.py tests/browser/test_aikda_socket.py tests/browser/test_core_client.py tests/core/test_app.py tests/core/test_performance_commands.py
git commit -m "feat: accept validated performance cover images"
```

### Task 3: Implement guided drafts, submission, cancellation, and player queries

**Files:**
- Modify: `src/dzmm_bot/core/performance.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Test: `tests/core/test_performance_repository.py`
- Test: `tests/core/test_performance_commands.py`
- Test: `tests/core/test_service.py`
- Test: `tests/browser/test_worker.py`

**Interfaces:**
- Produces: `begin_performance_draft(platform_id, group_chat_id, now) -> PerformanceDraftResult`.
- Produces: `consume_performance_draft_input(platform_id, inbound_id, now, *, text, image_url, image_alt) -> PerformanceDraftResult | None`.
- Produces: `cancel_own_performance(platform_id: str, now: datetime) -> PerformanceActionResult`.
- Produces: `own_performance(platform_id: str, now: datetime) -> PerformanceView | None`.
- Produces: `upcoming_performances(group_chat_id: UUID, now: datetime) -> tuple[PerformanceView, ...]`.

- [ ] **Step 1: Write failing repository tests for the complete draft flow**

```python
def test_confirmed_draft_locks_the_date_and_owner(repository, joined_users, now):
    result = complete_draft(
        repository,
        owner="owner",
        title="夜航",
        introduction="一场夜间公演",
        scheduled_at=now + timedelta(days=1),
        participants=["演员甲", "演员乙"],
        cover_url=None,
    )
    assert result.status == "submitted"
    assert result.reservation.state == "pending_review"
    assert result.reservation.event_date == (now + timedelta(days=1)).date()


def test_second_draft_cannot_occupy_same_date(repository, now):
    complete_draft(repository, owner="owner-a", scheduled_at=now + timedelta(days=1))
    result = complete_draft(repository, owner="owner-b", scheduled_at=now + timedelta(days=1))
    assert result.status == "date_taken"
```

Use parametrized tests named `test_performance_time_boundary`, `test_performance_text_limits`, and `test_performance_participant_validation` for 29:59/30:00 minutes, 30 days, title/introduction limits, unknown/duplicate participants, 30-minute draft expiry, owner active limit, and cover `/跳过`.

- [ ] **Step 2: Run tests and verify the repository methods are absent**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py -q -k 'draft or submit or cancel or upcoming'
```

- [ ] **Step 3: Implement parsers and transactional draft methods**

```python
def parse_performance_datetime(value: str, now: datetime) -> datetime:
    parsed = datetime.strptime(value.strip(), "%Y/%m/%d-%H:%M:%S").replace(tzinfo=BEIJING)
    if parsed < now.astimezone(BEIJING) + timedelta(minutes=30):
        raise ValueError("公演时间至少需要提前 30 分钟")
    if parsed > now.astimezone(BEIJING) + timedelta(days=30):
        raise ValueError("只能预约未来 30 天内的公演")
    return parsed


def begin_performance_draft(
    self, platform_id: str, group_chat_id: UUID, now: datetime
) -> PerformanceDraftResult:
    """Lock user, verify membership, group switch, direct room, and owner limit."""
```

At `/确认`, lock the gameplay gate, user, and conflicting active reservations in that order; create the reservation plus participant rows in one transaction. Do not reserve a date before confirmation.

- [ ] **Step 4: Write failing command/service tests**

```python
def test_group_entry_starts_private_guide(service, repository, now):
    receive_group(service, "owner", "/预约公演", now)
    direct = latest_direct_reply(repository)
    assert direct.text == "请发送公演标题（1–50字）。"


def test_private_image_advances_cover_step(service, active_cover_draft, now):
    receive_direct_image(service, "owner", "https://cdn.example/cover.webp", now)
    assert "发送 /确认" in latest_direct_reply_text()
```

Add named tests `test_performance_requires_direct_room`, `test_performance_requires_group_switch`, `test_cancel_performance_draft_and_reservation`, `test_my_performance_renders_review_state`, `test_performance_schedule_hides_pending`, and `test_active_performance_draft_has_private_routing_priority`.

- [ ] **Step 5: Route commands and active direct rooms**

```python
_DIRECT_ENTRY_COMMANDS.update({
    "/我的公演预约", "/取消公演预约", "/延期",
})

if message.source_type == "direct":
    performance_reply = self._performance_handler.handle(message)
    if performance_reply is not None:
        self._enqueue_replies(
            stored.id,
            performance_reply,
            default_destination_chatroom_id=message.chatroom_id,
        )
        return ReceiveResult(stored.id, True)
```

Register `/预约公演`, `/我的公演预约`, `/取消公演预约`, `/公演日程`, `/延期`, and `/end` in command definitions/help. Extend `direct_inbound_chatroom_ids()` with owners of active performance drafts and pending future reservations.

- [ ] **Step 6: Run focused command/service tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_service.py tests/browser/test_worker.py -q -k 'performance or inbound_room'
git add src/dzmm_bot/core/performance.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/service.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/browser/worker.py tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_service.py tests/browser/test_worker.py
git commit -m "feat: add guided performance reservations"
```

### Task 4: Expose review, settings, group switch, and admin UI

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Test: `tests/core/test_app.py`
- Test: `tests/admin/test_app.py`

**Interfaces:**
- Produces: Core endpoints under `/internal/game/performances` and Admin proxies under `/api/game/performances`.
- Produces: `performances_enabled` on all group create/update/response contracts.
- Produces: admin role mapping `admin` for ordinary review and `super_admin` for board-only actions.

- [ ] **Step 1: Write failing Core/Admin API tests**

```python
def test_admin_can_approve_pending_performance(client, admin_headers, pending_id):
    response = client.post(
        f"/api/game/performances/{pending_id}/approve",
        headers={**admin_headers, "Idempotency-Key": "approve-1"},
    )
    assert response.status_code == 200
    assert response.json()["state"] == "approved"


def test_ordinary_admin_cannot_cancel_after_preview(client, admin_headers, previewed_id):
    response = client.post(
        f"/api/game/performances/{previewed_id}/cancel",
        json={"reason": "临时取消"},
        headers=admin_headers,
    )
    assert response.status_code == 403
```

Add named tests `test_performance_list_and_detail`, `test_performance_rejection_requires_reason`, `test_performance_admin_mutation_is_idempotent`, `test_performance_settings_update`, `test_group_performance_switch_round_trip`, `test_performance_history_filters`, and `test_super_admin_force_operations`.

- [ ] **Step 2: Run tests and confirm routes/models are missing**

```bash
.venv/bin/pytest tests/core/test_app.py tests/admin/test_app.py -q -k 'performance or performances_enabled'
```

- [ ] **Step 3: Add typed API contracts and repository actions**

```python
class PerformanceSettingsResponse(ApiModel):
    maximum_duration_minutes: int


class UpdatePerformanceSettingsRequest(ApiModel):
    maximum_duration_minutes: int = Field(ge=1)


class ReviewPerformanceRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


class PerformanceResponse(ApiModel):
    id: UUID
    owner_display_name: str
    group_chat_id: UUID
    title: str
    introduction: str
    scheduled_at: datetime
    participant_names: list[str]
    cover_url: str | None
    state: str
```

Implement `review_performance`, `cancel_performance_by_admin`, `force_end_performance`, `force_settle_performance`, `list_performances`, `performance_details`, `get_performance_settings`, and `update_performance_settings`. Every mutation receives `actor` and writes an `AuditEventRecord`.

- [ ] **Step 4: Add Core and Admin routes with explicit role checks**

```python
def require_board_power(identity: AdminIdentity) -> AdminIdentity:
    if identity.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "董事会权限不足")
    return identity
```

Ordinary review routes use `authorize`; post-preview cancellation, post-preview extension approval, force end, and force settlement call `require_board_power`. Keep existing idempotency and configuration-version fencing.

- [ ] **Step 5: Add the admin performance view**

```html
<section id="performances-view" class="dashboard-view panel" hidden>
  <div class="panel-heading">
    <div><h2>公演场次</h2><p class="muted">审核预约、处理延期并管理进行中的公演。</p></div>
    <button id="edit-performance-settings" class="primary" type="button">公演设置</button>
  </div>
  <div id="performance-list" aria-live="polite"></div>
</section>
```

Render tabs with IDs `performance-pending`, `performance-future`, `performance-active`, and `performance-history`; the detail modal includes cover, participants, rejection reason, extension, tip ledger, and audit entries. Buttons carry `data-performance-action` and are hidden when `identity.role !== "super_admin"` for board-only actions. Add checkbox `group-chat-performances-enabled` to the existing group form.

- [ ] **Step 6: Run API/UI tests and commit**

```bash
.venv/bin/pytest tests/core/test_app.py tests/admin/test_app.py -q -k 'performance or performances_enabled'
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/core/repository.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: add performance administration"
```

### Task 5: Implement postponement requests and atomic calendar moves

**Files:**
- Modify: `src/dzmm_bot/core/performance.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Test: `tests/core/test_performance_repository.py`
- Test: `tests/core/test_performance_commands.py`
- Test: `tests/admin/test_app.py`

**Interfaces:**
- Produces: `parse_postponement(value: str) -> timedelta`.
- Produces: `request_performance_postponement(platform_id, duration, now)` and `review_performance_postponement(request_id, approve, actor, now)`.

- [ ] **Step 1: Write failing parser and transaction tests**

```python
@pytest.mark.parametrize("raw,expected", [("30m", 30), ("1h", 60), ("1d", 1440)])
def test_parse_postponement(raw, expected):
    assert parse_postponement(raw) == timedelta(minutes=expected)


def test_approved_postponement_moves_calendar_atomically(repository, reservation, now):
    request = repository.request_performance_postponement("owner", timedelta(days=1), now)
    result = repository.review_performance_postponement(request.id, True, "admin:a", now)
    assert result.reservation.event_date == reservation.event_date + timedelta(days=1)
    assert result.reservation.pre_notice_sent_at is None
```

Add named tests `test_postponement_rejects_invalid_duration`, `test_only_one_postponement_can_be_pending`, `test_postponement_rejects_occupied_target_date`, `test_postponement_revalidates_time_window`, `test_postponement_expires_at_original_start`, `test_postponement_rejects_non_schedulable_states`, and `test_postponement_conflict_rolls_back_original_date`.

- [ ] **Step 2: Run tests and verify failure**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py -q -k 'postpone or delay'
```

- [ ] **Step 3: Implement the parser and repository workflow**

```python
_POSTPONEMENT_PATTERN = re.compile(r"^(?P<amount>[1-9]\d*)(?P<unit>[mhd])$")


def parse_postponement(value: str) -> timedelta:
    match = _POSTPONEMENT_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError("延期格式应为 /延期 30m、/延期 1h 或 /延期 1d")
    factor = {"m": 1, "h": 60, "d": 1440}[match.group("unit")]
    return timedelta(minutes=int(match.group("amount")) * factor)
```

Approval lock order is gameplay gate, extension row, reservation row, conflicting calendar rows. Move old/new occupancy in one transaction, reset preview fields, and enqueue the immediate group change notice only when the old preview had been sent.

- [ ] **Step 4: Route `/延期` and expose admin decisions**

```python
if command == "/延期":
    duration = parse_postponement(payload)
    return self._performance_postponement(message, duration)
```

Show original/proposed time in `/我的公演预约` and the admin modal. Before preview any admin can decide; after preview the Admin proxy requires `super_admin`.

- [ ] **Step 5: Run postponement tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_app.py tests/admin/test_app.py -q -k 'performance and (postpone or extension or delay)'
git add src/dzmm_bot/core/performance.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/static/admin.js tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: add performance postponement approval"
```

### Task 6: Add preview, conflict-aware opening, restart recovery, and fixed hosting messages

**Files:**
- Modify: `src/dzmm_bot/core/performance.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/service.py`
- Test: `tests/core/test_performance_scheduler.py`
- Test: `tests/core/test_repository.py`

**Interfaces:**
- Produces: `run_performance_jobs(now: datetime) -> None` called before game/random-event jobs.
- Produces: `performance_blocks_new_game(group_chat_id) -> bool` and a conflict check that excludes the current performance.
- Produces: system image enqueue support with stable delivery ordering.

- [ ] **Step 1: Write failing scheduler boundary tests**

```python
def test_preview_is_sent_once_at_five_minutes(repository, approved, now):
    repository.run_performance_jobs(approved.scheduled_at - timedelta(minutes=5))
    repository.run_performance_jobs(approved.scheduled_at - timedelta(minutes=4))
    assert group_texts(repository).count(expected_preview(approved)) == 1


def test_due_performance_waits_for_existing_game(repository, approved, active_game):
    repository.run_performance_jobs(approved.scheduled_at)
    assert repository.performance(approved.id).state == "waiting"
    finish(active_game)
    repository.run_performance_jobs(approved.scheduled_at + timedelta(seconds=1))
    assert repository.performance(approved.id).state == "performing"
```

Add named tests `test_pending_review_expires_at_preview_boundary`, `test_waiting_performance_does_not_interrupt_existing_game`, `test_preview_blocks_new_game_and_random_event`, `test_late_job_recovers_preview_and_opening`, `test_opening_queues_text_before_cover`, `test_opening_without_cover_queues_one_message`, and `test_performance_jobs_are_idempotent`.

- [ ] **Step 2: Run tests and confirm state transitions are missing**

```bash
.venv/bin/pytest tests/core/test_performance_scheduler.py tests/core/test_repository.py -q -k 'performance'
```

- [ ] **Step 3: Implement fixed renderers**

```python
def render_performance_opening(view: PerformanceView) -> str:
    return (
        "-------------------------演出开始-----------------------\n"
        f"公演：{view.title}\n"
        f"简介：{view.introduction}\n"
        f"参演人员：{'、'.join(view.participant_names)}"
    )
```

Add `render_performance_preview`, time-change, cancellation, tipping-open, and settlement renderers; none may call an AI service.

- [ ] **Step 4: Implement job transitions under the gameplay gate**

```python
def run_performance_jobs(self, now: datetime) -> None:
    now = now.astimezone(BEIJING)
    with self.transaction():
        with self._session() as session:
            self._lock_gameplay_gate(session)
            self._expire_unreviewed_performances(session, now)
            self._preview_due_performances(session, now)
            self._open_or_wait_due_performances(session, now)
            self._advance_waiting_performances(session, now)
            self._expire_performing_and_tipping(session, now)
```

Call this before jobs that can start games or random events. Add `enqueue_system_image_outbound(image_url: str, *, image_alt: str, group_chat_id: UUID, destination_chatroom_id: str, bypass_performance_gate: bool = False) -> OutboundRecord` so opening text and optional cover share one destination delivery key and deterministic reply indexes. Performance-owned preview/opening/cancellation messages explicitly bypass performance deferral.

- [ ] **Step 5: Run scheduler tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_scheduler.py tests/core/test_repository.py -q -k 'performance or random_event or game_conflict'
git add src/dzmm_bot/core/performance.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/service.py tests/core/test_performance_scheduler.py tests/core/test_repository.py
git commit -m "feat: schedule and open public performances"
```

### Task 7: Enforce stage chat rules and participant `/end`

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Test: `tests/core/test_performance_commands.py`
- Test: `tests/core/test_service.py`

**Interfaces:**
- Produces: `classify_performance_message(platform_id, inbound_id, content, group_chat_id) -> str` with `participant`, `observer_valid`, `observer_invalid`, or `none`.
- Produces: `end_performance(platform_id, group_chat_id, now, *, forced=False) -> PerformanceActionResult`.

- [ ] **Step 1: Write failing stage-routing tests**

```python
def test_participant_line_is_recorded_without_bot_reply(service, performing, now):
    receive_group(service, "actor", "第一幕开始。", now)
    assert latest_outbound() is None
    assert mapped_performance_message().reservation_id == performing.id


def test_observer_must_use_parentheses(service, performing, now):
    receive_group(service, "observer", "我也想说话", now)
    assert latest_reply_text() == "公演正在进行，请使用括号进行场外交流。"
    receive_group(service, "observer", "（场外：好耶）", now + timedelta(seconds=1))
    assert outbound_count() == 1
```

Add `/end` participant/non-participant cases, prohibited commands, AI mention suppression, tipping-stage bracket behavior, other-group isolation, and AI-memory exclusion.

- [ ] **Step 2: Run tests and confirm current command/AI routing leaks through**

```bash
.venv/bin/pytest tests/core/test_performance_commands.py tests/core/test_service.py -q -k 'performance or stage'
```

- [ ] **Step 3: Put performance classification before random-event and command routing**

```python
stage = self._repository.classify_performance_message(
    message.sender_platform_id,
    stored.id,
    message.content,
    group_context.group_chat_id,
)
if stage in {"participant", "observer_valid"}:
    self._repository.record_ai_memory_message(
        stored.id, message.sender_platform_id, False, message.received_at
    )
    return ReceiveResult(stored.id, True)
if stage == "observer_invalid":
    self._repository.enqueue_outbound(
        stored.id,
        "公演正在进行，请使用括号进行场外交流。",
        group_chat_id=group_context.group_chat_id,
        destination_chatroom_id=group_context.chatroom_id,
    )
    return ReceiveResult(stored.id, True)
```

Allow only participant `/end` while `performing` and performance `/打赏` while `tipping`; reject other commands before AI and gameplay handlers.

- [ ] **Step 4: Implement `/end` and maximum-duration transition**

```python
def end_performance(
    self, platform_id: str, group_chat_id: UUID, now: datetime
) -> PerformanceActionResult:
    """Require a current participant, enter tipping, and set deadline to now plus 180 seconds."""
```

Use the same transition helper for scheduler timeout and super-admin force end. A force settlement during tipping calls the settlement helper instead.

- [ ] **Step 5: Run stage tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_commands.py tests/core/test_service.py tests/core/test_performance_scheduler.py -q -k 'performance or stage'
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/service.py src/dzmm_bot/core/commands.py tests/core/test_performance_commands.py tests/core/test_service.py tests/core/test_performance_scheduler.py
git commit -m "feat: enforce performance stage chat"
```

### Task 8: Add real-currency tipping and final settlement

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/performance.py`
- Test: `tests/core/test_performance_repository.py`
- Test: `tests/core/test_performance_commands.py`
- Test: `tests/core/test_performance_scheduler.py`

**Interfaces:**
- Produces: `tip_performance(sender_platform_id, recipient_name, amount, inbound_id, now, group_chat_id, reference_message_id=None) -> PerformanceTipResult`.
- Produces: `_settle_performance_tipping(session, reservation, now, forced=False)`.

- [ ] **Step 1: Write failing atomic tip tests**

```python
def test_tip_moves_real_balance_once(repository, tipping, inbound_id, now):
    first = repository.tip_performance(
        "fan", "演员甲", 5, inbound_id, now, tipping.group_chat_id
    )
    second = repository.tip_performance(
        "fan", "演员甲", 5, inbound_id, now, tipping.group_chat_id
    )
    assert first.status == second.status == "sent"
    assert balance("fan") == 95
    assert balance("演员甲") == 105
    assert tip_rows(tipping.id) == 1
```

Add insufficient balance, nonpositive amount, nonparticipant target, self-tip, wrong group, wrong state, reply to current participant line, old/foreign reference rejection, row-lock concurrency, and ledger sources.

- [ ] **Step 2: Run tests and verify performance tips do not exist**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py -q -k 'tip or tipping'
```

- [ ] **Step 3: Implement tip transfer with idempotency**

```python
def tip_performance(
    self,
    sender_platform_id: str,
    recipient_name: str | None,
    amount: int,
    inbound_id: UUID,
    now: datetime,
    group_chat_id: UUID,
    reference_message_id: str | None = None,
) -> PerformanceTipResult:
    with self.transaction():
        with self._session() as session:
            self._lock_gameplay_gate(session)
            reservation = self._stage_active_performance(session, group_chat_id)
            if reservation is None or reservation.state != "tipping":
                return PerformanceTipResult("not_tipping")
            existing = session.scalar(
                select(PerformanceTipRecord).where(
                    PerformanceTipRecord.inbound_message_id == inbound_id
                )
            )
            if existing is not None:
                return _performance_tip_result(existing)
            sender = self._locked_user(session, sender_platform_id)
            recipient = self._locked_performance_participant(
                session, reservation.id, recipient_name
            )
            self._apply_balance_change(sender, -amount, "performance_tip_out", now)
            self._apply_balance_change(recipient, amount, "performance_tip_in", now)
            session.add(
                PerformanceTipRecord(
                    reservation_id=reservation.id,
                    sender_user_id=sender.id,
                    recipient_user_id=recipient.id,
                    inbound_message_id=inbound_id,
                    amount=amount,
                    created_at=now,
                )
            )
```

Validate a reply target through `PerformanceMessageRecord` rather than trusting display text. Add Chinese ledger labels for `performance_tip_out` and `performance_tip_in`.

- [ ] **Step 4: Route `/打赏` to performance before random-event tipping**

```python
if self._repository.active_performance_state(group_chat_id) == "tipping":
    return self._performance_tip(message, content, received_at)
return self._random_event_tip(message, content, received_at)
```

Support both name form and reply form. Only the reply form derives the recipient from the referenced current-performance message.

- [ ] **Step 5: Implement top-five settlement and memory facts**

```python
top_five = sorted(
    tips, key=lambda tip: (-tip.amount, tip.created_at, str(tip.id))
)[:5]
participant_totals = aggregate_by_participant(tips, participants)
text = render_performance_settlement(total, participant_totals, top_five)
reservation.state = "completed"
reservation.ended_at = now
```

Insert one deduplicated activity fact per participant keyed by `performance:{reservation.id}:{user.id}`. The final line must be `-------------------------演出结束-----------------------`.

- [ ] **Step 6: Run tipping tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_performance_scheduler.py -q -k 'performance and (tip or settle or memory)'
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/performance.py tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_performance_scheduler.py
git commit -m "feat: settle performance tipping"
```

### Task 9: Defer same-group system notices until the performance closes

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Test: `tests/core/test_performance_scheduler.py`
- Test: `tests/core/test_dark_market_repository.py`
- Test: `tests/core/test_repository.py`

**Interfaces:**
- Extends: `enqueue_system_outbound(text: str, *, recall_after_seconds: int | None = None, memory_round_id: UUID | None = None, group_chat_id: UUID | None = None, destination_chatroom_id: str | None = None, delivery_kind: str = "group", performance_defer_key: str | None = None, bypass_performance_gate: bool = False) -> OutboundRecord`.
- Produces: `_flush_performance_deferred_notices(session, reservation, now)`.

- [ ] **Step 1: Write failing deferral and isolation tests**

```python
def test_same_group_system_notice_waits_until_performance_settlement(
    repository, performing, now
):
    repository.enqueue_system_outbound(
        "暗网成交",
        group_chat_id=performing.group_chat_id,
        destination_chatroom_id=group_room(performing.group_chat_id),
        performance_defer_key="dark-market:listing-1",
    )
    assert "暗网成交" not in pending_group_texts()
    assert held_performance_texts() == ["暗网成交"]
    settle_performance(repository, performing, now)
    assert pending_group_texts()[-1] == "暗网成交"
```

Add named tests `test_other_group_notice_remains_immediate`, `test_direct_refund_remains_immediate`, `test_latest_keyed_notice_replaces_held_text`, `test_unkeyed_notices_keep_chronological_order`, `test_notice_and_business_transaction_roll_back_together`, `test_performance_owned_notice_bypasses_hold`, and `test_notice_lock_order_starts_with_gameplay_gate`.

- [ ] **Step 2: Run tests and confirm notices currently pass through**

```bash
.venv/bin/pytest tests/core/test_performance_scheduler.py tests/core/test_dark_market_repository.py tests/core/test_repository.py -q -k 'performance and (defer or notice or outbound)'
```

- [ ] **Step 3: Add central system-notice interception**

```python
if (
    delivery_kind == "group"
    and not bypass_performance_gate
    and group_chat_id is not None
    and (
        performance := self._stage_active_performance(session, group_chat_id)
    ) is not None
):
    return self._hold_performance_outbound(
        session,
        performance,
        text,
        destination_chatroom_id,
        performance_defer_key,
    )
```

Acquire gameplay gate before reservation/user/listing/balance locks in every transaction that may generate a public notice. Performance preview/opening/tipping/settlement/cancellation calls use `bypass_performance_gate=True`.

- [ ] **Step 4: Preserve dark-market latest-state coalescing**

```python
self.enqueue_system_outbound(
    notice_text,
    group_chat_id=group_chat_id,
    destination_chatroom_id=destination,
    performance_defer_key=f"dark-market:{listing.id}",
)
```

`_hold_performance_outbound` creates or updates an `OutboundRecord` with `status="held_performance"`, `deferred_by_performance_id`, and optional `performance_defer_key`; therefore callers still receive a valid outbound ID. Do not defer `delivery_kind="direct"`, balance mutations, refunds, freezes, or private transaction messages. Flush after the final settlement outbound is created by changing held rows to `pending` in `(created_at, id)` order.

- [ ] **Step 5: Run deferral/concurrency tests and commit**

```bash
.venv/bin/pytest tests/core/test_performance_scheduler.py tests/core/test_dark_market_repository.py tests/core/test_repository.py -q -k 'performance or dark_market or random_event'
git add src/dzmm_bot/core/repository.py tests/core/test_performance_scheduler.py tests/core/test_dark_market_repository.py tests/core/test_repository.py
git commit -m "feat: defer announcements during performances"
```

### Task 10: Finish help text, end-to-end coverage, migration checks, and review

**Files:**
- Modify: `rule.md`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: relevant tests from Tasks 1–9

**Interfaces:**
- Consumes all prior task interfaces.
- Produces a release-ready but undeployed feature.

- [ ] **Step 1: Add exact player help and rules assertions**

```python
def test_performance_help_lists_all_player_commands(service, now):
    receive_group(service, "employee", "/帮助 公演", now)
    text = latest_reply_text()
    assert "/预约公演" in text
    assert "/公演日程" in text
    assert "/我的公演预约" in text
    assert "/取消公演预约" in text
    assert "/延期 30m" in text
    assert "/end" in text
    assert "回复参演人员消息发送 /打赏 金额" in text
```

Document the private steps, daily/global limits, approval, postponement, parentheses, six-hour default, 180-second tip phase, board powers, and group isolation in `rule.md`.

- [ ] **Step 2: Add one complete end-to-end scenario**

```python
def test_performance_end_to_end(app_context, now):
    reservation = submit_and_approve_performance(
        app_context, now + timedelta(hours=2)
    )
    run_jobs_at(reservation.scheduled_at - timedelta(minutes=5))
    run_jobs_at(reservation.scheduled_at)
    participant_says("开场台词")
    participant_sends("/end")
    fan_replies_with_tip(5)
    run_jobs_at(reservation.tipping_deadline)
    assert reservation_state() == "completed"
    assert final_group_message().endswith(
        "-------------------------演出结束-----------------------"
    )
    assert balances_are_consistent()
```

Add parametrized test `test_performance_restart_is_idempotent` with checkpoints `submitted`, `previewed`, `performing`, `tipping_before_tip`, `tipping_after_tip`, and `settlement_enqueued`; reconstruct `CoreRepository` at each checkpoint and assert no duplicate transition or money movement.

- [ ] **Step 3: Run focused and full verification**

```bash
.venv/bin/pytest tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_performance_scheduler.py tests/core/test_app.py tests/admin/test_app.py tests/browser/test_aikda_socket.py tests/browser/test_worker.py -q
.venv/bin/pytest -q
.venv/bin/python -m compileall -q src migrations/versions
git diff --check
.venv/bin/alembic heads
```

Expected: zero failures, compile success, no whitespace errors, and exactly one Alembic head at `20260826_57`.

- [ ] **Step 4: Review migration and dirty-tree boundaries**

```bash
git status --short
git diff --name-only HEAD
git diff -- migrations/versions/20260826_57_performance_reservations.py
```

Confirm unrelated `.env`, `.DS_Store`, transport handoff notes, and pre-existing user files remain untouched. Verify migration 56 changes are present before upgrading to 57.

- [ ] **Step 5: Request code review and resolve every blocking finding**

Use `superpowers:requesting-code-review`. Treat every Critical or Important finding as blocking; reproduce it with a failing test before changing implementation, then rerun the focused and full suites.

- [ ] **Step 6: Commit final documentation and regression work**

```bash
git add rule.md src/dzmm_bot/core/commands.py src/dzmm_bot/core/repository.py tests/core/test_performance_repository.py tests/core/test_performance_commands.py tests/core/test_performance_scheduler.py tests/core/test_app.py tests/admin/test_app.py tests/browser/test_aikda_socket.py tests/browser/test_worker.py
git commit -m "docs: document public performance gameplay"
```

## Completion Gate

- [ ] Every design requirement maps to a passing focused test.
- [ ] All money movement, date occupancy, postponement, and state transitions are transactional and idempotent.
- [ ] Full tests pass after the final review fix, not only before review.
- [ ] One Alembic head remains and migration 57 upgrades cleanly from 56.
- [ ] Report exact test counts, commits, migration requirement, and any non-blocking warnings.
- [ ] Stop before deployment and wait for explicit deployment confirmation.
