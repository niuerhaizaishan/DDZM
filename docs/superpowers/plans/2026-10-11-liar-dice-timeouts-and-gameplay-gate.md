# Liar Dice Timeouts & Gameplay Gate Implementation Plan

> **Status:** implemented on branch `nuo/performance_ganize` (2026-10-11). Tasks below are checked off with the verification command that actually ran.

**Goal:** Stop three observed defects in the liar dice (大话骰子) feature and in the cross-gameplay mutex: a round that silently disappears mid-game, an ignored `N个X` call with no explanation, and the private "your dice" message that omits the wild point — while keeping two long-running games from coexisting in one group.

**Architecture:** Two independent gate helpers stay separate and are *each* completed rather than merged: `_group_has_active_gameplay` (every gameplay type plus random events) gains the performance stage, and `_has_active_game` gains the three ledger-backed types that were missing (`red_packet`, `liar_dice`, `truth_trade`). Liar dice gains three admin-configurable deadlines (signup / dealing / waiting-for-continue) that a sweeper checks on every pass, with the rule "only act when a deadline exists" so historical games are never force-ended by the deploy itself, and with every automatic ending announced in the group.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x, Alembic, FastAPI, PostgreSQL 16 (prod) / SQLite (unit tests), vanilla JS admin console.

## Global Constraints

- Never merge the two gate helpers; each keeps its own callers and its own exclusive checks.
- `_has_active_game` intentionally does not consult random events or performance jobs — those callers check them themselves.
- Liar dice settings are **global**: a single row keyed to the primary group applies to every group. Do not read settings per group.
- Every new setting must be reachable from the admin console, and taking effect must be proven (not just stored).
- A sweeper may only end a game whose deadline is already set; the first pass after deploy only backfills deadlines.
- Migration `20261011_103` must leave exactly one Alembic head and must be reversible.
- All user-facing copy lives in one place per concept; no copy is duplicated across call sites.

## Tasks

- [x] **Task 1 — complete both gate helpers.** `_group_has_active_gameplay` calls `_group_has_active_performance`; `_has_active_game` covers `red_packet` / `liar_dice` / `truth_trade` via `active_key is not None`. The performance scheduler passes `include_performance=False` so the stage cannot block itself. Verified: `tests/core/test_gameplay_gate.py` (28 cases) plus a stash-check that the old code fails exactly 5 of them.
- [x] **Task 2 — explain conflicts instead of deadlocking.** `/继续` and `/当前游戏` list every active game with that game's own end command. Verified: `tests/core/test_group_commands.py`, `tests/core/test_app.py` (286 passed).
- [x] **Task 3 — three deadlines.** `liar_dice_settings.signup_timeout_minutes` (default 5), `continue_timeout_minutes` (default 5), `deal_timeout_seconds` (default 180, replacing a hard-coded 10-minute signup window); `liar_dice_games.round_end_deadline` and `dealing_deadline`. Each automatic ending announces itself. Verified: `tests/core/test_liar_dice.py`.
- [x] **Task 4 — ignored calls are explained.** A participant who calls out of turn gets a state-aware hint (signup / dealing / round ended); an outsider or a group with no game stays silent. Verified: three cases in `tests/core/test_liar_dice.py` counting outbound rows.
- [x] **Task 5 — one source of truth for the wild point.** `liar_dice.wild_note()` is used by the private hand (`/看骰`), the group opening, the status view and the dealing message. Verified: `test_liar_dice_private_hand_mentions_the_wild_point`.
- [x] **Task 6 — settings plumbed to the console.** `api_models` → core endpoints → admin whitelist → `core_client` → admin panel + status cards. Verified: core API cases (defaults, bulk update, legacy single-field request, out-of-range 422), admin case proving the whitelist does not drop fields (removing one field turns it red), and service-level cases showing 7 minutes actually governs the sweep. Commit: `feat: expose the liar dice timeout settings in the admin console`.
- [x] **Task 7 — migration covered.** `tests/deploy/test_liar_dice_timeouts_migration.py` builds its own tables, asserts defaults 5/5/180 and `NULL` deadlines for pre-existing rows, asserts reversibility, and asserts the rendered PostgreSQL DDL.

## User-facing copy (single source of truth)

```
【大话骰子】第 N 轮你的骰子：🎲5 🎲5 🎲2 🎲2 🎲5
🃏 本轮万能点：🎲4（可顶任何点数；有人叫过它之后失效）
私聊发 /看骰 可随时重看。
```

```
⏳ 报名 5 分钟内没人 /开始将自动取消；每回合 120 秒，超时自动跳到最后。
```

```
⏰【大话骰子】本轮结束后 5 分钟没人 /继续，本局已自动结束。
发 /大话骰子数据 可看本局战绩。
```

```
本轮已作废或已结束，发 /继续 开下一轮，或 /结束游戏 收尾。
```

## Verification

| Check | Command | Result |
|---|---|---|
| Gates cover both directions | `pytest tests/core/test_gameplay_gate.py` | 28 passed |
| No self-blocking performance | `pytest tests/core/test_performance_scheduler.py tests/core/test_performance_commands.py` | 33 passed |
| Liar dice behaviour | `pytest tests/core/test_liar_dice.py` | 22 passed |
| Core + admin regression | `pytest tests/core tests/admin` | 1890 passed, 17 skipped, 0 failed |
| Migration unit | `pytest tests/deploy/test_liar_dice_timeouts_migration.py` | 2 passed |
| Migration on real PostgreSQL | fresh DB → `alembic upgrade head` | exit 0, single head `20261011_103`, 191 tables |
| New columns on real PostgreSQL | `information_schema.columns` | 3 integers `NOT NULL` default `5`/`5`/`180`; 2 `timestamp with time zone`, nullable |
| Incremental path + reversibility | `upgrade 20261010_102` → insert row → `upgrade head` → `downgrade -1` → `upgrade head` | row preserved (240/true/4 → 240/true/4/5/5/180), columns dropped and restored, version back to head |

## Non-goals

- Do not merge the two gates; do not touch the performance stage or the random-event vote internals.
- Do not add announcements to other games' forced endings (all games already announce through the shared `/结束游戏` template).
- Do not clean up historical dual-game rows; the conflict message gives the way out.
- Do not make liar dice settings per-group.
