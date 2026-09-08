# Company Story Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an administrator configure one DZMM novel link and let `/公司的故事集` send that novel as a clickable share card in group or direct chat.

**Architecture:** Store the configured novel URL in the existing singleton game settings record and expose it through the existing game-settings API and modal. Convert the validated URL to its UUID when handling the command, enqueue a `share` outbound record, and let Browser Worker send `{type: "share", shareType: "novel", resourceId: ...}` through the existing WebSocket transport.

**Tech Stack:** Python 3, FastAPI, SQLAlchemy/Alembic, vanilla admin JavaScript, pytest.

**Spec:** User-approved conversation on 2026-09-08: a global administrator-editable link; `/公司的故事集` works in group and direct chats; it sends only the configured novel share card; an unset link returns a clear message.

## Global Constraints

- Use exactly share content `{ "type": "share", "shareType": "novel", "resourceId": "<UUID>" }`.
- Store one global DZMM/Aikda novel URL; do not create a story library.
- Do not add unrelated configuration or delivery behavior.

---

### Task 1: Persist and expose the configured novel URL

**Files:**
- Modify: `src/dzmm_bot/core/schema.py:180-194`
- Create: `migrations/versions/20260908_72_company_story_novel.py`
- Modify: `src/dzmm_bot/core/repository.py:2864-2880,22644-22675`
- Modify: `src/dzmm_bot/core/api_models.py:649-666`
- Modify: `src/dzmm_bot/core/app.py:1412-1432,3422-3430`
- Test: `tests/core/test_app.py`

**Interfaces:**
- Produces: `GameSettingsRecord.company_story_novel_url: str | None` and `set_game_settings(..., company_story_novel_url: str | None)`.
- Produces: game-settings GET/PATCH JSON with `company_story_novel_url`.

- [x] **Step 1: Write the failing API test**

```python
def test_game_settings_store_company_story_novel_url(client, headers):
    url = "https://www.aikda.com/novel/66408bb3-60a0-40e1-a434-ee40efee4d27"
    response = client.patch("/internal/game/settings", headers=headers, json={
        "currency_name": "摸鱼币", "onboarding_bonus": 0,
        "checkin_reward": 5, "weekly_attendance_reward": 20,
        "company_story_novel_url": url,
    })
    assert response.status_code == 200
    assert response.json()["company_story_novel_url"] == url
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q tests/core/test_app.py::test_game_settings_store_company_story_novel_url`

Expected: FAIL because the existing request model rejects the new field.

- [x] **Step 3: Implement the database, repository, and API contract**

```python
company_story_novel_url: Mapped[str | None] = mapped_column(String(4096))
```

Validate the setting as an empty value or an `https://<host>/novel/<UUID>` link. Add the migration with a nullable column so existing settings remain valid.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest -q tests/core/test_app.py::test_game_settings_store_company_story_novel_url`

Expected: PASS.

### Task 2: Add the administrator setting control

**Files:**
- Modify: `src/dzmm_bot/admin/templates/index.html:388-430`
- Modify: `src/dzmm_bot/admin/static/admin.js:500-530,1650-1680,2760-2790`
- Test: `tests/admin/test_app.py`

**Interfaces:**
- Consumes: `company_story_novel_url` from the existing game-settings API.
- Produces: the value in the existing economy/game-settings modal and saves it through the existing PATCH endpoint.

- [x] **Step 1: Write the failing admin-page test**

```python
def test_admin_game_settings_modal_includes_company_story_novel_url(client):
    page = client.get("/").text
    assert 'id="settings-company-story-novel-url"' in page
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q tests/admin/test_app.py::test_admin_game_settings_modal_includes_company_story_novel_url`

Expected: FAIL because the setting control does not yet exist.

- [x] **Step 3: Implement the minimal modal control and request field**

```html
<label>公司故事集小说链接
  <input id="settings-company-story-novel-url" type="url" placeholder="https://www.aikda.com/novel/...">
</label>
```

Load its current value when opening the modal and include its trimmed value in the existing game-settings save payload.

- [x] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest -q tests/admin/test_app.py::test_admin_game_settings_modal_includes_company_story_novel_url`

Expected: PASS.

### Task 3: Send the configured novel card for the command

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`, `src/dzmm_bot/core/commands.py`, `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/browser/session.py`, `src/dzmm_bot/browser/aikda_socket.py`, `src/dzmm_bot/browser/worker.py`
- Test: `tests/core/test_group_commands.py`, `tests/core/test_app.py`, `tests/browser/test_aikda_socket.py`, `tests/browser/test_worker.py`

**Interfaces:**
- Consumes: `GameSettingsRecord.company_story_novel_url`.
- Produces: an outbound claim with `content_type="novel"` and the URL UUID as its text payload.
- Produces: `{ "type": "share", "shareType": "novel", "resourceId": "<UUID>" }` through the Browser WebSocket sender.

- [x] **Step 1: Write the failing command test**

```python
def test_company_story_collection_enqueues_configured_novel(...):
    # Group and direct commands each enqueue a novel outbound record.
    assert (outbound.content_type, outbound.text) == ("novel", resource_id)
```

- [x] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py::test_company_story_collection_enqueues_configured_novel_share`

Expected: FAIL because the command and share outbound fields do not exist.

- [x] **Step 3: Implement the smallest share delivery path**

```python
content = {"type": "share", "shareType": "novel", "resourceId": outbound.text}
```

Add a `send_share_to` gateway method, route share messages directly through the Browser WebSocket sender (never the long-message bot), and queue it without a text body. Handle `/公司的故事集` in the normal command dispatcher for group and direct inbound; queue a text error when the setting is absent.

- [x] **Step 4: Run focused command and WebSocket tests**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py::test_company_story_collection_enqueues_configured_novel_share tests/browser/test_aikda_socket.py -k 'share or novel' tests/browser/test_worker.py -k share`

Expected: PASS.

### Task 4: Verify migration and regression safety

**Files:**
- Test: `tests/deploy/test_company_story_novel_migration.py`

- [x] **Step 1: Write migration test**

```python
def test_company_story_novel_migration_adds_nullable_setting_column(connection):
    # Upgrade the pre-feature game_settings table and assert the URL column is nullable.
```

- [x] **Step 2: Run it to verify the migration round-trip**

Run: `.venv/bin/pytest -q tests/deploy/test_company_story_novel_migration.py`

Expected: FAIL because the migration revision is missing.

- [x] **Step 3: Add the Alembic migration and run verification**

Run: `.venv/bin/pytest -q tests/deploy/test_company_story_novel_migration.py tests/core/test_app.py::test_game_settings_store_company_story_novel_url tests/admin/test_app.py::test_admin_game_settings_modal_includes_company_story_novel_url tests/core/test_group_commands.py::test_company_story_collection_enqueues_configured_novel_share tests/browser/test_aikda_socket.py`

Expected: PASS.

- [x] **Step 4: Run final targeted regression suite and diff check**

Run: `.venv/bin/pytest -q tests/core/test_app.py tests/admin/test_app.py tests/core/test_group_commands.py tests/browser/test_aikda_socket.py tests/browser/test_worker.py tests/deploy/test_company_story_novel_migration.py && git diff --check`

Expected: PASS and no whitespace errors.
