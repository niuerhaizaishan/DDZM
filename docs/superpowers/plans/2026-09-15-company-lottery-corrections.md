# Company Lottery Corrections Implementation Plan

> **For agentic workers:** Execute inline with test-driven development; this is a surgical correction of the existing lottery implementation.

**Goal:** Align company lottery behavior with the approved fixed 10-choose-4 design and existing multi-group routing rules.

**Architecture:** Keep the existing global lottery and ledger. Constrain the supported red-ball selection to four, route lottery announcements only to groups eligible for announcements, validate guided entries against the same enabled-group rule as purchases, snapshot the payout settings on each round, and render actual payout amounts accurately.

**Tech Stack:** Python, SQLAlchemy/Alembic, FastAPI, pytest, vanilla JavaScript.

**Spec:** `docs/superpowers/specs/2026-09-14-company-lottery-design.md`

## Tasks

### Task 1: Lock the fixed number shape

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`, `src/dzmm_bot/admin/app.py`, `src/dzmm_bot/admin/templates/index.html`, `src/dzmm_bot/admin/static/admin.js`, `src/dzmm_bot/core/repository.py`
- Test: `tests/core/test_company_lottery.py`, `tests/admin/test_app.py`

- [ ] Add failing tests that reject a red-ball count other than four.
- [ ] Verify the tests fail because the current API accepts those settings.
- [ ] Restrict the public and repository configuration paths to four red balls, while retaining red-pool and blue-pool configuration.
- [ ] Verify the tests pass.

### Task 2: Preserve group routing rules

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`, `src/dzmm_bot/core/commands.py`
- Test: `tests/core/test_company_lottery_repository.py`, `tests/core/test_company_lottery_commands.py`

- [ ] Add failing tests for skipped announcements in a disabled/announcement-disabled group and for rejecting draft continuation from an unmanaged group.
- [ ] Verify the tests fail against the current implementation.
- [ ] Route announcements through listening-and-announcement-enabled groups and require an enabled group for draft continuation.
- [ ] Verify the tests pass.

### Task 3: Lock per-round settlement and render actual payouts

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`, new Alembic migration, `src/dzmm_bot/core/repository.py`, `src/dzmm_bot/admin/static/admin.js`, `src/dzmm_bot/admin/templates/index.html`
- Test: `tests/core/test_company_lottery_repository.py`, `tests/deploy/test_company_lottery_migration.py`

- [ ] Add failing tests showing a rule edit cannot change an already open round and a mixed capped payout announcement retains each actual amount.
- [ ] Verify the tests fail.
- [ ] Persist the settlement-relevant snapshot at round creation, use it at drawing, and render winner amounts truthfully; correct global-ledger wording.
- [ ] Verify focused tests and the broader lottery/admin suite pass.
