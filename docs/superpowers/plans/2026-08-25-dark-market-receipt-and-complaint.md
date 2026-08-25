# Dark Market Receipt Confirmation and Complaint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change dark-market auction settlement into a 72-hour escrowed receipt flow with private counterpart identity, buyer confirmation or complaint, and four compatible market-query commands.

**Architecture:** Extend the existing `dark_market_listings` state machine instead of adding a parallel order subsystem. Keep the winning bid deduction as escrow, centralize the only two terminal transitions in repository helpers, and route player commands through the existing command/template/outbox layers. Extend the existing admin listing contract and renderer for audit visibility.

**Tech Stack:** Python 3.13, SQLAlchemy 2, Alembic, FastAPI/Pydantic, vanilla JavaScript admin UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-dark-market-receipt-and-complaint-design.md`

## Global Constraints

- Receipt timeout is exactly 72 hours from auction settlement.
- `/确认收货` and `/投诉` are direct-message-only buyer commands.
- Complaint refunds the full escrow and deducts an equal penalty from the seller, allowing a negative balance.
- Public identity disclosure begins only after confirmed or automatic receipt; complaint publicly identifies only the seller.
- Historical terminal listings remain unchanged; only listings still `active` at deployment use the new flow.
- `/查看暗网` is canonical; `/登陆暗网`, `/登录暗网`, and `/暗网` remain functional aliases.
- State, money ledger changes, and outbound creation commit atomically and remain idempotent.

---

### Task 1: Persist Receipt State and Expose It Through the Admin Contract

**Files:**
- Create: `migrations/versions/20260825_55_dark_market_receipt.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Test: `tests/core/test_dark_market_repository.py`
- Test: `tests/core/test_app.py`
- Create: `tests/deploy/test_dark_market_receipt_migration.py`

**Interfaces:**
- Produces listing states `awaiting_receipt` and `complained`.
- Produces nullable fields `receipt_started_at: datetime | None`, `receipt_deadline: datetime | None`, and `receipt_resolved_at: datetime | None` on `DarkMarketListingRecord`, `DarkMarketAdminListing`, and `DarkMarketListingResponse`.
- Produces seller and buyer employee-number fields on admin responses.

- [ ] **Step 1: Write failing schema and API contract tests**

Add tests that construct/read an awaiting-receipt listing and assert the three timestamps plus seller/buyer employee numbers appear in the repository admin view and `/internal/dark-market/listings` response.

```python
assert item.state == "awaiting_receipt"
assert item.receipt_deadline == listing.ends_at + timedelta(hours=72)
assert item.seller_employee_number == 1
assert item.buyer_employee_number == 2
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/pytest -q tests/core/test_dark_market_repository.py tests/core/test_app.py -k dark_market`

Expected: FAIL because receipt fields/states do not exist.

- [ ] **Step 3: Add migration and model fields**

Create revision `20260825_55` with down revision `20260824_54`. Drop and recreate `ck_dark_market_listing_state` to include `awaiting_receipt` and `complained`; add the three nullable timezone-aware timestamps. Update the SQLAlchemy model and admin/API dataclasses without rewriting historical rows.

- [ ] **Step 4: Run focused tests and migration upgrade/downgrade tests**

Run: `.venv/bin/pytest -q tests/core/test_dark_market_repository.py tests/core/test_app.py -k dark_market`

Run: `.venv/bin/pytest -q tests/deploy/test_dark_market_receipt_migration.py`

Expected: PASS on a temporary SQLite database upgraded to `20260825_55`.

- [ ] **Step 5: Commit the persistence slice**

```bash
git add migrations/versions/20260825_55_dark_market_receipt.py src/dzmm_bot/core/schema.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/api_models.py tests/core/test_dark_market_repository.py tests/core/test_app.py tests/deploy/test_dark_market_receipt_migration.py
git commit -m "feat: persist dark market receipt state"
```

### Task 2: Replace Immediate Sale Settlement with Escrowed Receipt Resolution

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Test: `tests/core/test_dark_market_repository.py`

**Interfaces:**
- Produces `DarkMarketReceiptResult(status: str, public_number: int | None = None, candidates: tuple[int, ...] = ())`.
- Produces `resolve_dark_market_receipt(platform_id: str, public_number: int | None, action: str, inbound_id: UUID, now: datetime) -> DarkMarketReceiptResult` where `action` is `confirm` or `complain`.
- Produces private settlement messages containing `format_employee_number(...)` results.

- [ ] **Step 1: Write failing auction-to-escrow tests**

Assert that an auction with a winning bid enters `awaiting_receipt`, preserves buyer frozen balance, leaves seller balance unchanged, creates no disclosure, records a 72-hour deadline, and sends both counterpart identities privately. Add a self-sale assertion that only one direct message is created.

```python
repository.run_dark_market_jobs(listing.ends_at)
assert stored.state == "awaiting_receipt"
assert _balance(repository, "seller") == 100
assert _balance(repository, "buyer-a") == 79
assert disclosure is None
assert "真实卖家（#0001）" in buyer_private.text
```

- [ ] **Step 2: Run tests and verify RED**

Run: `.venv/bin/pytest -q tests/core/test_dark_market_repository.py -k 'sale or receipt or self_sale'`

Expected: FAIL because auctions still pay sellers and create disclosure immediately.

- [ ] **Step 3: Implement awaiting-receipt settlement**

Change `_settle_dark_market_listing` to persist the buyer/final amount/deadline, keep the bid `current`, enqueue the anonymous waiting notice, and enqueue one or two direct counterpart messages. Do not apply seller income, fee, or disclosure here.

- [ ] **Step 4: Write failing confirmation and automatic-confirmation tests**

Cover explicit buyer confirmation, exact 72-hour boundary, one second before boundary, seller/unrelated rejection, candidate selection for multiple orders, duplicate requests, disclosure creation only after success, and message failure not repeating money changes.

```python
result = repository.resolve_dark_market_receipt(
    "buyer-a", listing.public_number, "confirm", inbound_id, now
)
assert result.status == "confirmed"
assert _balance(repository, "seller") == 119
assert disclosure.state == "pending"
```

- [ ] **Step 5: Implement one locked success finalizer**

Add a private `_confirm_dark_market_receipt_locked(session, listing, now)` helper used by both the command and `run_dark_market_jobs`. It changes state once, pays seller, charges the snapped fee, marks the bid settled, creates the disclosure, and enqueues success/public-confirmation messages atomically.

- [ ] **Step 6: Write failing complaint tests**

Cover full buyer refund, seller equal penalty, seller negative balance, no fee/income/disclosure, anonymous buyer in group notice, public seller name and `#0000`-style number, non-buyer rejection, confirmation/complaint races, and repeat idempotency.

```python
result = repository.resolve_dark_market_receipt(
    "buyer-a", listing.public_number, "complain", inbound_id, now
)
assert result.status == "complained"
assert _balance(repository, "buyer-a") == 100
assert _balance(repository, "seller") == 79
assert "买家" not in complaint_notice.text
```

- [ ] **Step 7: Implement complaint finalization and ledger labels**

Use the locked listing transition, mark the bid refunded, apply `dark_market_complaint_refund` and `dark_market_complaint_penalty`, allow the seller result to go negative, and enqueue one group criticism notice. Add Chinese labels to `_BALANCE_SOURCE_LABELS`.

- [ ] **Step 8: Run the complete repository suite**

Run: `.venv/bin/pytest -q tests/core/test_dark_market.py tests/core/test_dark_market_repository.py`

Expected: PASS with no duplicate financial effects.

- [ ] **Step 9: Commit the state-machine slice**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_dark_market_repository.py
git commit -m "feat: add dark market receipt escrow"
```

### Task 3: Add Player Commands, Query Aliases, Templates, and Direct Routing

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Modify: `migrations/versions/20260825_55_dark_market_receipt.py`
- Test: `tests/core/test_group_commands.py`
- Test: `tests/core/test_service.py`
- Test: `tests/core/test_ai_knowledge.py`
- Test: `tests/browser/test_worker.py`

**Interfaces:**
- Canonical query template key is `/查看暗网`; aliases normalize before enabled-command and handler lookup.
- `/确认收货 [商品编号]` maps to `action="confirm"`; `/投诉 [商品编号]` maps to `action="complain"`.
- Active direct-room selection includes the buyer for unexpired `awaiting_receipt` listings.

- [ ] **Step 1: Write failing command tests**

Parameterize all four query spellings, verify only `/查看暗网` is advertised, and cover private-only validation, optional number parsing, multiple-candidate reply, confirmed, complained, not-buyer, already-resolved, and not-joined receipt results.

```python
@pytest.mark.parametrize("command", ["/查看暗网", "/登陆暗网", "/登录暗网", "/暗网"])
def test_dark_market_query_aliases(command):
    assert handler.handle(group_message(command)) is not None
```

- [ ] **Step 2: Run command tests and verify RED**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_ai_knowledge.py -k dark_market`

Expected: FAIL because aliases and receipt commands are not registered.

- [ ] **Step 3: Implement command normalization and reply templates**

Normalize the three legacy query aliases to `/查看暗网` before `_COMMANDS`, enabled-command, and handler dispatch. Add only canonical command definitions for `/查看暗网`, `/确认收货`, and `/投诉`; seed editable scenario templates in migration 55 and in default definitions. Add receipt commands to AI knowledge and help text.

- [ ] **Step 4: Write failing Browser Worker and room-selection tests**

Assert unknown direct rooms accept `/确认收货` and `/投诉`, ordinary text remains ignored, and unexpired awaiting buyers are selected through `/internal/direct-inbound/rooms` but disappear at the exact receipt deadline.

- [ ] **Step 5: Implement direct routing**

Add the two receipt commands to `_DIRECT_ENTRY_COMMANDS` and add an awaiting-receipt buyer selector to `direct_inbound_chatroom_ids(now)` using the existing consolidated union.

- [ ] **Step 6: Run focused command and Worker tests**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_ai_knowledge.py tests/browser/test_worker.py -k 'dark_market or direct_entry or direct_inbound'`

Expected: PASS.

- [ ] **Step 7: Commit the command slice**

```bash
git add migrations/versions/20260825_55_dark_market_receipt.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/ai_knowledge.py src/dzmm_bot/browser/worker.py tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_ai_knowledge.py tests/browser/test_worker.py
git commit -m "feat: add dark market receipt commands"
```

### Task 4: Show Receipt and Complaint Audit Data in the Admin UI

**Files:**
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Test: `tests/admin/test_app.py`
- Test: `tests/admin/test_package_data.py`

**Interfaces:**
- Consumes the extended `DarkMarketListingResponse` fields from Task 1.
- Produces labels for `awaiting_receipt` and `complained` plus receipt deadline/resolution and employee-number audit text.

- [ ] **Step 1: Write failing admin contract/package tests**

Extend the fake listing response with receipt timestamps and employee numbers. Assert list/detail JSON preserves them and packaged JavaScript contains both Chinese state labels and receipt audit field rendering.

- [ ] **Step 2: Run admin tests and verify RED**

Run: `.venv/bin/pytest -q tests/admin/test_app.py tests/admin/test_package_data.py -k dark_market`

Expected: FAIL because the renderer does not know the new states/fields.

- [ ] **Step 3: Implement the minimal renderer update**

Map `awaiting_receipt` to “待收货” and `complained` to “已投诉”. Show counterpart employee numbers, escrow amount, receipt deadline, resolution time, final fee, and terminal status in list/detail cards. Keep force-delist visible only for `active`.

- [ ] **Step 4: Run admin tests**

Run: `.venv/bin/pytest -q tests/admin/test_app.py tests/admin/test_package_data.py -k dark_market`

Expected: PASS.

- [ ] **Step 5: Commit the admin slice**

```bash
git add src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/templates/index.html tests/admin/test_app.py tests/admin/test_package_data.py
git commit -m "feat: show dark market receipt audits"
```

### Task 5: Full Verification and Deployment Readiness

**Files:**
- Modify only files required to correct failures caused by Tasks 1–4.

**Interfaces:**
- Verifies the complete feature without adding new behavior.

- [ ] **Step 1: Run migration verification on a fresh database**

Run: `.venv/bin/pytest -q tests/deploy/test_dark_market_receipt_migration.py tests/deploy/test_dark_market_migration.py tests/deploy/test_dark_market_commands_migration.py`

Expected: PASS with the temporary database upgraded to `20260825_55` and historical dark-market rows preserved.

- [ ] **Step 2: Run all automated tests**

Run: `.venv/bin/pytest -q`

Expected: zero failures.

- [ ] **Step 3: Run static syntax and diff checks**

Run: `.venv/bin/python -m compileall -q src tests migrations`

Run: `git diff --check`

Expected: both commands exit 0.

- [ ] **Step 4: Review migration and financial invariants**

Confirm active listings are not rewritten, old terminal rows remain valid, receipt and complaint transitions are one-way, buyer escrow is conserved, seller penalty can go negative, and outbox records share the business transaction.

- [ ] **Step 5: Report deployment readiness without deploying**

Report the final commit IDs, test counts, migration head, and any preserved unrelated working-tree files. Wait for explicit deployment authorization.
