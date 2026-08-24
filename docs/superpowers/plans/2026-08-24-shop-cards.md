# Shop Card System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing shop with stable item numbers, atomic purchasing and inventory use, ordinary benefit cards, consent-based adult roleplay cards, source-group AI context, and complete admin controls.

**Architecture:** Keep the existing `items` and `user_items` tables as the catalog and inventory source of truth. Add typed system-item metadata, daily bonus/limit records, durable adult-card sessions, consent participants, generation jobs, and temporary common-sense states. Commands remain thin adapters over transactional repository methods; deadlines run through the existing Core job runner; scene generation uses the existing AI worker lease pattern.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL/SQLite tests, vanilla JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-shop-cards-design.md`

## Global Constraints

- Keep every player shop command group-only. Direct messages are accepted only as replies to a pending private scene prompt.
- Preserve the legacy `/发奖金 员工名 数额` and `/发奖金 全部 数额` forms while adding reply-target `/发奖金 数额`.
- Use Beijing dates for all daily limits and bonuses.
- Make every purchase, card reservation, compensation, stock change, balance change, and daily quota change atomic and idempotent.
- Do not persist scene text or generated adult roleplay into stable AI memory.
- Do not deploy during implementation; deployment requires a separate user confirmation after verification.

## Task 1: Define the catalog domain and migrate persistent data

**Files:**
- Create: `src/dzmm_bot/core/shop_cards.py`
- Create: `migrations/versions/20260824_54_shop_cards.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Test: `tests/core/test_shop_cards.py`
- Test: `tests/test_migrations.py`

- [ ] Write failing domain tests for all fixed names, prices, effects, default ranks, adult classification, recipient counts, compensation prices, scratch ranges, and stable ordering.
- [ ] Add immutable `SystemShopItem` definitions and small validation helpers in `shop_cards.py`.
- [ ] Write a migration test that upgrades an existing custom-item database and asserts deterministic public numbers, unique system seeds, preserved legacy fields, and safe downgrade.
- [ ] Add `items.public_number`, `effect_type`, `minimum_rank_order`, `unlimited_stock`, and `system_key`; add `group_chats.adult_shop_enabled` default false.
- [ ] Add durable records for purchase daily usage, per-day AI/game bonus totals and use, item-use idempotency, adult sessions/participants, scene jobs, and common-sense states.
- [ ] Implement migration `54`: number legacy items by `(created_at, id)`, seed fixed system items after the maximum number, and add uniqueness/index constraints.
- [ ] Run `pytest tests/core/test_shop_cards.py tests/test_migrations.py -q`.
- [ ] Commit: `feat: add shop card catalog schema`.

## Task 2: Add atomic catalog, purchase, and numbered inventory operations

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Test: `tests/core/test_repository.py`

- [ ] Write failing repository tests for group-aware catalog visibility, adult switch filtering, rank rejection, insufficient balance, finite/infinite stock, disabled items, gift/scratch shared daily caps, duplicate inbound idempotency, and generic-item purchase.
- [ ] Add result dataclasses for numbered catalog rows, inventory rows, purchase results, and item-use results.
- [ ] Replace legacy active-item reads with numbered group-aware reads while retaining compatibility wrappers used by admin code.
- [ ] Implement `purchase_shop_item` with row locks over user/item/daily usage, source-group checks, rank checks, shared category caps, atomic balance debit, stock decrement, and inventory increment.
- [ ] Return existing purchase result for repeated inbound message IDs without charging twice.
- [ ] Run `pytest tests/core/test_repository.py -q -k 'shop or item or purchase'`.
- [ ] Commit: `feat: add atomic shop purchases`.

## Task 3: Implement ordinary card effects

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Test: `tests/core/test_repository.py`

- [ ] Write failing tests for gift recipient validation and payouts, uniform bounded scratch outcomes with an injected RNG, AI bonus credit, game bonus credit, disabled-owned-card use, generic no-effect behavior, and duplicate-use idempotency.
- [ ] Implement a transactional inventory reservation/consumption primitive keyed by inbound message ID.
- [ ] Implement the four gift effects and balance ledger labels; burn the price/payout difference into the system.
- [ ] Implement scratch A/B/C result generation at use time and credit the result atomically.
- [ ] Implement current-Beijing-day AI and multiplayer-game bonus records; consume base allowance before bonus allowance.
- [ ] Integrate AI bonus consumption into `try_enqueue_ai_request`.
- [ ] Integrate multiplayer bonus fallback at the existing limit gates for memory duel, undercover, blame, number bomb, and Texas Hold'em without changing each game's base rules.
- [ ] Run focused repository tests for every ordinary effect and every affected quota gate.
- [ ] Commit: `feat: add ordinary shop card effects`.

## Task 4: Add group-only player commands and reply-target bonuses

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/runtime/contracts.py` only if an existing reference field is insufficient
- Modify: command-template seed migration or defaults used by this repository
- Test: `tests/core/test_group_commands.py`
- Test: `tests/core/test_service.py`

- [ ] Write failing command tests for numbered `/商店`, `/购买 序号`, numbered `/我的物品`, `/使用 序号`, group-only rejection, reply target resolution, generic-item no-effect, and all legacy bonus forms.
- [ ] Register the new commands and templates with exact usage/error/success messages.
- [ ] Render infinite stock as `不限` and hide adult goods when the source group's switch is off.
- [ ] Route ordinary self-use and reply-target cards to repository operations.
- [ ] Resolve `/发奖金 数额` from the referenced sender while preserving name and `全部` parsing.
- [ ] Confirm command/private-flow messages remain excluded from AI memory.
- [ ] Run `pytest tests/core/test_group_commands.py tests/core/test_service.py -q -k 'shop or purchase or inventory or bonus or use'`.
- [ ] Commit: `feat: add shop player commands`.

## Task 5: Implement adult-card reservation and scene collection

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/service.py`
- Test: `tests/core/test_repository.py`
- Test: `tests/core/test_service.py`

- [ ] Write failing tests for switch-off rejection, private-room preflight, M-card self flow, single/multi recipient reservation, no self/duplicates, common-sense active-state conflict, 30-minute selection timeout, cancellable stages, and restart persistence.
- [ ] Implement `/使用` reservation without consuming the card until the session reaches its terminal path.
- [ ] Enqueue the private scene prompt through the user's known direct destination and consume the next eligible 1–200 character direct text as the scene.
- [ ] Implement `/邀请参与 会话编号` by reply, with stable session numbers and required participant counts.
- [ ] Implement M-card announcement immediately after scene collection without creating consent or AI work.
- [ ] Implement `/取消使用 会话编号` only during scene/participant collection and return the reserved card.
- [ ] Run focused adult session/service tests.
- [ ] Commit: `feat: add adult card setup flows`.

## Task 6: Add per-recipient consent and compensation

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/jobs.py` or the existing periodic job entrypoint
- Test: `tests/core/test_repository.py`
- Test: `tests/core/test_service.py`

- [ ] Write failing tests for authorization notices, reply-message binding, one decision per target, all-consent success, refusal, partial timeout, exact 50% system compensation, no stock return, and duplicate job execution.
- [ ] Post one source-group authorization notification per target containing card, user, participants, and full scene.
- [ ] Accept `/同意使用` and `/拒绝使用` only when replying to that target's authorization notice.
- [ ] Start fulfillment only after every target agrees; on any refusal or 10-minute timeout atomically consume the card, compensate the buyer, and close all remaining decisions.
- [ ] Add restart-safe timeout processing to the existing Core job loop.
- [ ] Run focused consent/timeout tests.
- [ ] Commit: `feat: add adult card consent workflow`.

## Task 7: Generate scenes asynchronously and manage common-sense states

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/ai/core_client.py`
- Modify: `src/dzmm_bot/ai/worker.py`
- Modify: `src/dzmm_bot/core/ai_context.py` or the existing AI prompt builder
- Test: `tests/ai/test_worker.py`
- Test: `tests/core/test_ai_context.py`
- Test: `tests/core/test_repository.py`

- [ ] Write failing lease/idempotency tests for scene claims, retries, completion, maximum 800 characters, and single public result.
- [ ] Add Core claim/complete/fail endpoints and AI client methods for shop-scene jobs.
- [ ] Build the generation prompt from only the approved card type, group, participant names/profiles, and approved scene.
- [ ] Have the AI worker process shop jobs independently of normal AI requests and publish one reply to the original `/使用` message.
- [ ] For common-sense cards, create a source-group-only timed state instead of a scene job; inject it only when AI discusses the target in that group.
- [ ] Add restart-safe expiry and restoration announcement plus an idempotent admin force-end operation.
- [ ] Run focused AI worker/context/state tests.
- [ ] Commit: `feat: add shop scene generation and temporary context`.

## Task 8: Expose administration APIs

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Test: `tests/core/test_app.py`
- Test: `tests/admin/test_app.py`

- [ ] Write failing API tests for the per-group adult switch, editable item enabled/rank/stock mode/stock quantity, immutable system name/price/effect, transaction and consent logs, scene-job retry, active/history state listing, and force end.
- [ ] Extend group APIs with `adult_shop_enabled` while retaining optimistic concurrency behavior.
- [ ] Add catalog update endpoints restricted to allowed fields and stock replenishment semantics.
- [ ] Add paginated audit endpoints for purchases, uses, decisions, compensation, and jobs.
- [ ] Add retry and common-sense force-end endpoints with idempotent repository operations.
- [ ] Proxy the new APIs through admin with existing authentication and CSRF rules.
- [ ] Run `pytest tests/core/test_app.py tests/admin/test_app.py -q -k 'shop or item or adult or group_chat'`.
- [ ] Commit: `feat: add shop administration APIs`.

## Task 9: Complete the admin interface

**Files:**
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css`
- Test: `tests/admin/test_static_ui.py`

- [ ] Write failing static-contract tests for the adult-group switch, numbered catalog table, editable item controls, audit filters, active state controls, and retry buttons.
- [ ] Extend the existing group editor with the adult shop switch.
- [ ] Upgrade the shop view to show number/type/effect/rank/enabled/stock mode and edit only permitted fields.
- [ ] Add purchase/use/authorization/job logs and active/history temporary-state panels.
- [ ] Add force-end and retry actions with confirmation, busy states, and refreshed data.
- [ ] Run `pytest tests/admin/test_static_ui.py -q`.
- [ ] Commit: `feat: add shop administration interface`.

## Task 10: Update help, rules, and full-system regression coverage

**Files:**
- Modify: `rule.md`
- Modify: command/help seeds used by the application
- Modify: `src/dzmm_bot/core/commands.py`
- Test: `tests/core/test_group_commands.py`
- Test: `tests/core/test_repository.py`
- Test: `tests/test_migrations.py`

- [ ] Add player-facing rules for buying, inventory, replies, consent, timeouts, compensation, group boundaries, and temporary common-sense behavior.
- [ ] Add exact command guidance to `/帮助` and the AI gameplay guide without exposing admin-only operations.
- [ ] Add an end-to-end happy path for an ordinary card and a multi-recipient consent card, plus refusal, timeout, restart, cross-group, and duplicate-delivery cases.
- [ ] Run `ruff check .`.
- [ ] Run `pytest -q` and require zero failures.
- [ ] Inspect `git diff --check`, migration head count, and `git status --short`; preserve unrelated untracked files.
- [ ] Commit: `docs: document shop card gameplay`.

## Completion Gate

- [ ] Run the full verification suite again immediately before reporting completion.
- [ ] Request a code review and resolve every Critical or Important finding.
- [ ] Report implemented behavior, exact verification counts, commits, and any operational migration steps.
- [ ] Stop before deployment and wait for explicit deployment confirmation.
