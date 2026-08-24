# Dark Web Exchange Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the shared anonymous “暗网交易所” market with guided private listings, real-balance bid freezing, deterministic settlement, mutual identity disclosure, and full admin control.

**Architecture:** Add an independent persistent market state machine beside the existing group-game state machines. Keep pure validation and rendering helpers in a focused `dark_market.py`, keep transactional orchestration in `CoreRepository`, route explicit commands through `CommandRouter`, and let `CoreService` consume only non-command draft answers. Reuse the existing outbound queue and balance ledger so state, money, and notifications commit atomically.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, vanilla JavaScript admin UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-dark-web-exchange-design.md`

## Global Constraints

- The market is global across groups and has exactly one configured enabled-listening announcement group.
- Players can query listings only in the configured market group; listing, bid, settlement, delisting, and disclosure announcements go only there.
- Listing duration defaults to 3 hours and is configurable from 1–24 hours; exact deadlines are never exposed to players.
- Names are at most 30 characters, purposes 100, details 500; gender is `male`, `female`, or `private`; prices are integer `1–99999`.
- The current highest bid is backed by real frozen balance; outbid funds are returned immediately in the same transaction.
- Fee defaults to 5%, is configurable from 1–100%, rounds upward, and is at least 1 for every sale.
- A seller may bid on and win their own listing; the sale still charges the fee.
- Listings cannot be withdrawn by players after confirmation. Admin force-delisting returns the current frozen bid without charging a fee.
- Existing listings remain open for bids and settle normally after the feature is disabled; disabling only prevents new drafts and listing confirmations.
- The market never occupies a group-game slot and never enters `/当前游戏`.
- All dates, daily quotas, and expiry calculations use `Asia/Shanghai`.
- No player-facing response, log-safe summary, or AI context may reveal anonymous platform IDs, employee numbers, or names.

---

### Task 1: Persistent Market Schema and Migration

**Files:**
- Create: `migrations/versions/20260824_52_dark_market.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Create: `tests/deploy/test_dark_market_migration.py`

**Interfaces:**
- Produces ORM models `DarkMarketSettingsRecord`, `DarkMarketRankLimitRecord`, `DarkMarketDraftRecord`, `DarkMarketListingRecord`, `DarkMarketBidRecord`, `DarkMarketDisclosureRecord`, `DarkMarketDailyListingRecord`, and `DarkMarketNumberCounterRecord`.
- Later tasks rely on listing states `active|sold|unsold|force_delisted`, bid states `current|refunded|settled`, disclosure states `pending|revealed|anonymous`, and draft steps `name|purpose|details|gender|starting_price|preview`.

- [ ] **Step 1: Write the failing migration test**

```python
def test_dark_market_migration_creates_defaults_and_rank_limits(upgraded_connection):
    settings = upgraded_connection.execute(sa.text(
        "select enabled, duration_hours, fee_percent, version from dark_market_settings"
    )).mappings().one()
    assert settings == {"enabled": True, "duration_hours": 3, "fee_percent": 5, "version": 0}
    ranks = upgraded_connection.execute(sa.text(
        "select r.sort_order, l.daily_limit from dark_market_rank_limits l "
        "join ranks r on r.id = l.rank_id order by r.sort_order"
    )).all()
    assert [limit for _, limit in ranks] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5, -1]
```

Also assert all eight new tables exist, `public_number` is unique, one draft per user is unique, one daily count per `(user_id, usage_date)` is unique, and downgrade removes only the new schema.

- [ ] **Step 2: Run the migration test and verify it fails**

Run: `.venv/bin/pytest tests/deploy/test_dark_market_migration.py -q`

Expected: FAIL because revision `20260824_52` and the new tables do not exist.

- [ ] **Step 3: Add the migration and ORM records**

Create the revision with `down_revision = "20260820_51"`. Use `BeijingDateTime`, UUID foreign keys, explicit check constraints, and indexes for:

```python
Index("ix_dark_market_listings_due", "status", "ends_at")
Index("ix_dark_market_bids_listing_created", "listing_id", "created_at")
UniqueConstraint("listing_id", "bidder_id", "amount", "inbound_message_id")
```

Store the listing configuration snapshot (`duration_hours`, `fee_percent`, `announcement_group_id`) on every confirmed listing. Store current highest bid using bid state plus a partial unique index allowing only one `current` bid per listing. Store disclosure choices as nullable booleans so “not answered” is different from “no”. Seed one settings row, one public-number counter starting at 1, and the default rank limits by rank `sort_order`.

- [ ] **Step 4: Run migration and schema tests**

Run: `.venv/bin/pytest tests/deploy/test_dark_market_migration.py tests/deploy/test_artifacts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the schema slice**

```bash
git add migrations/versions/20260824_52_dark_market.py src/dzmm_bot/core/schema.py tests/deploy/test_dark_market_migration.py
git commit -m "feat: add dark market persistence"
```

### Task 2: Pure Validation, Fee, and Player Rendering

**Files:**
- Create: `src/dzmm_bot/core/dark_market.py`
- Create: `tests/core/test_dark_market.py`

**Interfaces:**
- Produces `normalize_listing_field(step: str, content: str) -> str | int`, `minimum_next_bid(starting_price: int, current_price: int | None) -> int`, `calculate_fee(amount: int, fee_percent: int) -> int`, `render_listing_summary(listing: DarkMarketListingView) -> str`, and `render_listing_detail(listing: DarkMarketListingView) -> str`.
- Produces immutable `DarkMarketListingView` with only public fields; it intentionally has no seller or bidder identity attributes.

- [ ] **Step 1: Write failing domain tests**

```python
@pytest.mark.parametrize(("amount", "percent", "fee"), [(1, 5, 1), (20, 5, 1), (21, 5, 2)])
def test_calculate_fee_rounds_up_with_minimum_one(amount, percent, fee):
    assert calculate_fee(amount, percent) == fee

def test_player_view_never_contains_exact_deadline_or_identity():
    view = DarkMarketListingView(12, "旧钥匙", "开门", "未知来历", "private", 10, 18, "active")
    text = render_listing_detail(view)
    assert "竞价中" in text
    assert "截止" not in text
    assert "卖家" not in text
```

Cover each length boundary, whitespace-only input, gender aliases `男/女/保密`, integer price parsing, first bid minimum, later minimum, and fee percent `1–100`.

- [ ] **Step 2: Run tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_dark_market.py -q`

Expected: FAIL because `dzmm_bot.core.dark_market` does not exist.

- [ ] **Step 3: Implement minimal pure helpers**

```python
def calculate_fee(amount: int, fee_percent: int) -> int:
    if not 1 <= fee_percent <= 100:
        raise ValueError("invalid fee percent")
    return max(1, (amount * fee_percent + 99) // 100)

def minimum_next_bid(starting_price: int, current_price: int | None) -> int:
    return starting_price if current_price is None else current_price + 1
```

Keep all player rendering in this module so repository/admin serializers cannot accidentally reuse a record containing identities.

- [ ] **Step 4: Run the pure helper tests**

Run: `.venv/bin/pytest tests/core/test_dark_market.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the domain slice**

```bash
git add src/dzmm_bot/core/dark_market.py tests/core/test_dark_market.py
git commit -m "feat: add dark market domain rules"
```

### Task 3: Settings, Drafts, Quotas, and Listing Confirmation

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Create: `tests/core/test_dark_market_repository.py`

**Interfaces:**
- Produces `DarkMarketSettings`, `DarkMarketRankLimit`, `DarkMarketDraftResult`, and `DarkMarketListingResult` result dataclasses.
- Produces repository methods:

```python
def get_dark_market_settings(self) -> DarkMarketSettings: ...
def set_dark_market_settings(self, *, enabled: bool, announcement_group_id: UUID | None,
                             duration_hours: int, fee_percent: int,
                             rank_limits: dict[UUID, int], expected_version: int) -> DarkMarketSettings: ...
def start_dark_market_draft(self, platform_id: str, now: datetime) -> DarkMarketDraftResult: ...
def advance_dark_market_draft(self, platform_id: str, content: str, now: datetime) -> DarkMarketDraftResult: ...
def cancel_dark_market_draft(self, platform_id: str, now: datetime) -> DarkMarketDraftResult: ...
def confirm_dark_market_listing(self, platform_id: str, inbound_id: UUID,
                                now: datetime) -> DarkMarketListingResult: ...
```

- [ ] **Step 1: Write failing repository tests**

Test: resume one draft rather than create a second; advance all five fields; show preview; reject invalid fields without advancing; cancel; expire after 30 minutes; reject unregistered users; reject disabled/unconfigured markets; apply the correct rank quota; reset quota at Beijing midnight; allocate stable non-reused public numbers; snapshot group/duration/fee; and atomically enqueue the anonymous listing announcement.

```python
def test_confirm_listing_consumes_quota_and_enqueues_anonymous_announcement(repo, now):
    draft = complete_draft(repo, "seller", now)
    result = repo.confirm_dark_market_listing("seller", uuid4(), now)
    assert result.status == "listed"
    assert result.listing.public_number == 1
    assert result.listing.ends_at == now + timedelta(hours=3)
    outbound = claim_one(repo, now)
    assert "商品 #1" in outbound.text
    assert "seller" not in outbound.text
```

- [ ] **Step 2: Run the focused repository tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_dark_market_repository.py -k 'draft or confirm or quota or settings' -q`

Expected: FAIL because the repository interfaces are missing.

- [ ] **Step 3: Implement settings and draft transactions**

Follow existing `_session()` and `_active_session` transaction patterns. Settings validation requires an enabled, non-deleted, listening-enabled group. Use `If-Match` style version comparison inside the locked settings row. Draft answers update only one row per employee and refresh `expires_at = now + timedelta(minutes=30)`.

- [ ] **Step 4: Implement listing confirmation**

Lock settings, rank limit, daily count, public-number counter, and draft. Increment quota and counter only after every validation passes. Persist the listing snapshot, delete the draft, and enqueue one group outbound using the configured group’s `chatroom_id` and `delivery_key` in the same transaction.

- [ ] **Step 5: Run focused and regression tests**

Run: `.venv/bin/pytest tests/core/test_dark_market_repository.py -k 'draft or confirm or quota or settings' tests/core/test_repository.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the listing slice**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_dark_market_repository.py
git commit -m "feat: add dark market listings"
```

### Task 4: Atomic Bidding, Settlement, Disclosure, and Recovery Jobs

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_dark_market_repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Produces repository methods:

```python
def place_dark_market_bid(self, platform_id: str, public_number: int, amount: int,
                          inbound_id: UUID, now: datetime) -> DarkMarketBidResult: ...
def decide_dark_market_disclosure(self, platform_id: str, public_number: int | None,
                                  reveal: bool, inbound_id: UUID,
                                  now: datetime) -> DarkMarketDisclosureResult: ...
def run_dark_market_jobs(self, now: datetime) -> None: ...
def force_delist_dark_market_listing(self, listing_id: UUID, now: datetime) -> DarkMarketListingResult: ...
```

- [ ] **Step 1: Write failing bid tests**

Cover first bid, minimum increment, same-bidder delta freezing, other-bidder full refund, multiple listings, seller self-bid, insufficient balance, duplicate inbound, expired listing, and two concurrent bids serialized by the listing lock.

```python
def test_outbid_refund_and_new_freeze_are_atomic(repo, listing, now):
    repo.place_dark_market_bid("buyer-a", listing.public_number, 20, uuid4(), now)
    repo.place_dark_market_bid("buyer-b", listing.public_number, 25, uuid4(), now)
    assert balance(repo, "buyer-a") == 100
    assert balance(repo, "buyer-b") == 75
    assert ledger_sources(repo) == ["dark_market_bid_hold", "dark_market_bid_refund", "dark_market_bid_hold"]
```

- [ ] **Step 2: Run bid tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_dark_market_repository.py -k bid -q`

Expected: FAIL because `place_dark_market_bid` is missing.

- [ ] **Step 3: Implement bidding with row locks and ledger labels**

Add `_BALANCE_SOURCE_LABELS` entries:

```python
"dark_market_bid_hold": "暗网报价冻结",
"dark_market_bid_refund": "暗网报价退款",
"dark_market_sale_income": "暗网成交收入",
"dark_market_sale_fee": "暗网成交手续费",
"dark_market_force_refund": "暗网强制下架退款",
```

Lock listing first, then affected users by sorted UUID. When the same current bidder raises, debit only `amount - old_amount`; otherwise refund the old bidder before debiting the new bidder. Mark the old bid `refunded`, create one `current` bid, and enqueue the anonymous group price update plus direct outbid refund notice atomically.

- [ ] **Step 4: Write failing settlement and disclosure tests**

Test no-bid flow, ordinary sale, `1/20/21` fee examples, self-sale, exact-deadline bid ordering, force delist, scheduler retry, mutual reveal, either-side refusal, 10-minute timeout, self-sale single decision, multiple pending candidate selection, and duplicate decisions.

```python
def test_sale_is_conservative_and_fee_rounds_up(repo, listing, now):
    repo.place_dark_market_bid("buyer", listing.public_number, 21, uuid4(), now)
    repo.run_dark_market_jobs(listing.ends_at)
    assert balance(repo, "buyer") == 79
    assert balance(repo, "seller") == 19
    assert ledger_amount(repo, "dark_market_sale_fee") == -2
```

- [ ] **Step 5: Implement settlement, disclosure, force-delisting, and jobs**

At settlement, lock the listing and all money rows, calculate the fee with `calculate_fee`, credit the seller with the gross sale amount using `dark_market_sale_income`, then debit the fee using `dark_market_sale_fee`; the resulting balance increase is the required net income. Mark the current bid `settled`, create disclosure state, and enqueue the anonymous result plus both private prompts in the same transaction. Force delisting changes only `active` listings, refunds the current bid, sends one announcement, and never creates disclosure state.

`run_dark_market_jobs(now)` must loop due rows deterministically by `(ends_at, public_number)`, expire drafts, settle listings, and finalize disclosure timeouts. Each item uses its own transaction so one failed item does not block the rest.

- [ ] **Step 6: Wire jobs into the existing recurring job entrypoint**

Call `run_dark_market_jobs(now)` once from `CoreRepository.run_daily_jobs` before group-specific game loops. It is a global job and must not run once per group.

- [ ] **Step 7: Run all market repository and scheduler tests**

Run: `.venv/bin/pytest tests/core/test_dark_market_repository.py tests/core/test_repository.py -q`

Expected: PASS.

- [ ] **Step 8: Commit the transaction slice**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_dark_market_repository.py tests/core/test_repository.py
git commit -m "feat: settle dark market auctions"
```

### Task 5: Private Wizard and Player Command Routing

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_service.py`

**Interfaces:**
- Adds explicit commands `/上架暗网`, `/取消上架`, `/报价`, `/公开`, `/不公开`, and `/登陆暗网`.
- Adds `CoreRepository.consume_dark_market_draft_text(platform_id: str, content: str, now: datetime) -> DarkMarketDraftResult | None` for non-command private answers only.
- Produces `CommandReply(force_group_destination=True, group_chat_id=announcement_group_id)` only for commands that intentionally target the configured market group; ordinary `/登陆暗网` replies stay in the source group.

- [ ] **Step 1: Write failing command tests**

Cover source restrictions and exact syntax:

```python
def test_dark_market_listing_must_start_in_direct_chat(router, direct_message):
    assert "私聊" in router.handle(direct_message._replace(source_type="group"))

def test_login_dark_market_rejects_non_market_group(router, group_message):
    assert router.handle(group_message._replace(content="/登陆暗网")) == "本群不是暗网交易所入口。"
```

Also test `/报价 12 25`, optional disclosure IDs, one/many disclosure candidates, `/确认` only confirming a preview draft, and no dark-market command entering generic game routing.

- [ ] **Step 2: Run command tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_group_commands.py -k dark_market -q`

Expected: FAIL because commands are not registered.

- [ ] **Step 3: Add explicit command routing and replies**

Register all commands in the command tuple and `_COMMAND_DEFINITIONS`. Add small private methods `_dark_market_start`, `_dark_market_cancel`, `_dark_market_confirm`, `_dark_market_bid`, `_dark_market_disclose`, and `_dark_market_login`. Parse only integers and stable public numbers at the command boundary; delegate state and money decisions to the repository.

- [ ] **Step 4: Write failing service tests for guided plain text**

Test that direct non-command text advances an active market draft, explicit `/报数` and `/看牌` still reach their existing handlers, unrelated direct text without a draft is untouched, and two users can hold drafts concurrently.

- [ ] **Step 5: Integrate draft consumption into `CoreService`**

After explicit direct commands and random-event submission commands have had priority, call `consume_dark_market_draft_text` only for remaining non-command direct messages. Convert its result to a private `CommandReply`; do not add draft state to `_DIRECT_COMMANDS` or gameplay locks.

- [ ] **Step 6: Run command and service regression tests**

Run: `.venv/bin/pytest tests/core/test_group_commands.py tests/core/test_service.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the player interface slice**

```bash
git add src/dzmm_bot/core/commands.py src/dzmm_bot/core/service.py src/dzmm_bot/core/repository.py tests/core/test_group_commands.py tests/core/test_service.py
git commit -m "feat: add dark market player commands"
```

### Task 6: Core and Admin HTTP Contracts

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`

**Interfaces:**
- Adds Core/Admin endpoints:

```text
GET   /internal/game/dark-market/settings
PATCH /internal/game/dark-market/settings
GET   /internal/game/dark-market/listings?status=&page=&page_size=
GET   /internal/game/dark-market/listings/{listing_id}
POST  /internal/game/dark-market/listings/{listing_id}/force-delist

GET   /api/game/dark-market/settings
PATCH /api/game/dark-market/settings
GET   /api/game/dark-market/listings?status=&page=&page_size=
GET   /api/game/dark-market/listings/{listing_id}
POST  /api/game/dark-market/listings/{listing_id}/force-delist
```

- [ ] **Step 1: Write failing Core API tests**

Assert strict Pydantic validation, `duration_hours` 1–24, `fee_percent` 1–100, a complete rank-limit set, expected-version conflicts, enabled-group validation, pagination, exact listing detail, and idempotent force-delisting.

- [ ] **Step 2: Run Core API tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_app.py -k dark_market -q`

Expected: FAIL with 404 or missing response models.

- [ ] **Step 3: Add API models and Core endpoints**

Define `DarkMarketSettingsResponse`, `SetDarkMarketSettingsRequest`, `DarkMarketRankLimitResponse`, `DarkMarketListingSummaryResponse`, `DarkMarketListingDetailResponse`, and `PaginatedDarkMarketListingsResponse`. Player-safe fields are not reused here: admin responses intentionally include seller/bidder identities, exact timestamps, and ledger source IDs.

- [ ] **Step 4: Write failing Admin relay tests**

Verify authorization, input shape validation, `If-Match`, `Idempotency-Key`, audit scope `dark-market:*`, and exact Core client paths.

- [ ] **Step 5: Add admin client and relay routes**

Follow existing `versioned_configuration_response`, `_relay_core`, and `idempotent_response` patterns. Force-delisting must use an idempotency key and return the already-ended state on replay.

- [ ] **Step 6: Run Core and Admin API tests**

Run: `.venv/bin/pytest tests/core/test_app.py tests/admin/test_app.py tests/admin/test_repository.py -q`

Expected: PASS.

- [ ] **Step 7: Commit the API slice**

```bash
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: expose dark market administration APIs"
```

### Task 7: Admin Dark Market Screen

**Files:**
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css`
- Modify: `tests/admin/test_package_data.py`

**Interfaces:**
- Adds a “暗网交易所” navigation view and settings modal.
- Consumes the `/api/game/dark-market/*` contracts from Task 6.

- [ ] **Step 1: Write failing package/UI contract assertions**

```python
def test_admin_bundle_contains_dark_market_controls():
    html = package_text("templates/index.html")
    js = package_text("static/admin.js")
    assert 'data-view="dark-market"' in html
    assert "/api/game/dark-market/listings" in js
    assert "force-delist-dark-market" in js
```

- [ ] **Step 2: Run package test and verify failure**

Run: `.venv/bin/pytest tests/admin/test_package_data.py -k dark_market -q`

Expected: FAIL because the controls are absent.

- [ ] **Step 3: Add the settings and listing UI**

The screen contains:

- enabled checkbox;
- announcement-group selector populated only with enabled-listening groups;
- duration hours and fee percent inputs;
- one daily-limit input per current rank (`-1` means unlimited);
- status filter and paginated listing table;
- detail panel with exact deadline, real identities, full bid chain, disclosure choices, fee, and ledger references;
- force-delist button shown only for `active` listings with a confirmation dialog.

Do not show player-safe countdown text in the admin—show the exact Beijing timestamp. Reuse existing cards, modal, table, pagination, toast, and request helpers; add only selectors needed by this view.

- [ ] **Step 4: Run admin asset and endpoint tests**

Run: `.venv/bin/pytest tests/admin/test_package_data.py tests/admin/test_app.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the admin UI slice**

```bash
git add src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/admin/test_package_data.py
git commit -m "feat: add dark market admin console"
```

### Task 8: Help, AI Knowledge, Rules, and Reply Templates

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Modify: `rule.md`
- Modify: `tests/core/test_ai_knowledge.py`
- Modify: `tests/core/test_group_commands.py`
- Create: `migrations/versions/20260824_53_dark_market_commands.py`
- Create: `tests/deploy/test_dark_market_commands_migration.py`

**Interfaces:**
- Adds `/帮助 暗网交易所` and authoritative topic key `dark_market`.
- Seeds command definitions and editable reply templates for all new command scenarios.

- [ ] **Step 1: Write failing help, AI, and seed tests**

Verify the help topic contains every exact player command, says identities remain anonymous unless both agree, says deadlines are hidden, and never suggests AI can bid or reveal users. Verify migration upgrades existing databases without overwriting administrator-edited templates.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_ai_knowledge.py tests/core/test_group_commands.py -k 'dark_market or 暗网' tests/deploy/test_dark_market_commands_migration.py -q`

Expected: FAIL because help, knowledge, and seeds are missing.

- [ ] **Step 3: Add command definitions and reply templates**

Seed definitions for `/上架暗网`, `/取消上架`, `/报价`, `/公开`, `/不公开`, and `/登陆暗网`. Seed scenarios for wrong channel, usage, draft steps, preview, listed, quota exceeded, market unavailable, bid accepted, outbid refunded, insufficient balance, ended, disclosure accepted, disclosure candidates, wrong group, empty market, and force-delisted notification.

- [ ] **Step 4: Add help, AI knowledge, and `rule.md` section 17**

Update topic lists and gameplay guidance using only confirmed rules. Add `## 17. 暗网交易所` to `rule.md`, preserving it as the implemented-rule baseline once code exists.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/pytest tests/core/test_ai_knowledge.py tests/core/test_group_commands.py tests/deploy/test_dark_market_commands_migration.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the knowledge slice**

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/ai_knowledge.py rule.md migrations/versions/20260824_53_dark_market_commands.py tests/core/test_ai_knowledge.py tests/core/test_group_commands.py tests/deploy/test_dark_market_commands_migration.py
git commit -m "docs: add dark market player guidance"
```

### Task 9: End-to-End Verification and Operational Audit

**Files:**
- Modify only files required to fix failures attributable to Tasks 1–8.
- Test: all test suites.

**Interfaces:**
- Verifies the complete feature without deployment.

- [ ] **Step 1: Run formatting and static repository checks**

Run: `git diff --check && .venv/bin/python -m compileall -q src migrations`

Expected: both commands exit 0.

- [ ] **Step 2: Run the complete test suite**

Run: `.venv/bin/pytest -q`

Expected: all tests pass; only the repository’s existing intentional skips remain.

- [ ] **Step 3: Run migration round-trip tests**

Run: `.venv/bin/pytest tests/deploy -q`

Expected: all deployment/migration tests pass from the previous head through `20260824_53` and back down where tested.

- [ ] **Step 4: Audit anonymity and money invariants**

Run:

```bash
rg -n "seller_platform|bidder_platform|employee_number|ends_at" src/dzmm_bot/core/dark_market.py src/dzmm_bot/core/commands.py
rg -n "dark_market_(bid_hold|bid_refund|sale_income|sale_fee|force_refund)" src tests
```

Expected: player rendering contains none of the identity/deadline fields; every money source appears in repository logic and tests.

- [ ] **Step 5: Review the final diff against the spec**

Run: `git diff 2e7d2f7..HEAD --stat && git status --short`

Expected: only dark-market feature files and preserved pre-existing untracked user files appear. Do not stage `.env`, `.DS_Store`, or `docs/BOT_MESSAGE_TRANSPORT_HANDOFF.md`.

- [ ] **Step 6: Commit any verification-only corrections**

```bash
git add migrations/versions/20260824_52_dark_market.py migrations/versions/20260824_53_dark_market_commands.py src/dzmm_bot/core/dark_market.py src/dzmm_bot/core/schema.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/service.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/core/ai_knowledge.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css rule.md tests/core/test_dark_market.py tests/core/test_dark_market_repository.py tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_app.py tests/core/test_ai_knowledge.py tests/admin/test_app.py tests/admin/test_package_data.py tests/deploy/test_dark_market_migration.py tests/deploy/test_dark_market_commands_migration.py
git commit -m "fix: close dark market integration gaps"
```

Skip this commit if verification required no corrections.
