# Message Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep real-time group messaging responsive during platform CAPTCHA enforcement, continuously reconcile missed messages through an isolated shadow channel, and let an administrator complete IP verification without stopping the primary Socket worker.

**Architecture:** The existing Socket gateway remains the primary path. A new single-flight shadow synchronizer uses copied Cookie/Token credentials in its own executor, reports per-group durable cursors and health to Core, and feeds recovered messages through the existing idempotent inbound path. A separately ported noVNC browser handles the IP CAPTCHA while the main browser and Socket remain alive.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy/Alembic, httpx, python-socketio, Playwright, vanilla JavaScript, pytest.

**Spec:** `docs/superpowers/specs/2026-08-19-message-resilience-design.md`

## Global Constraints

- Socket remains the real-time primary channel.
- Shadow synchronization defaults to 60 seconds with jitter and has at most one request in flight.
- A 418 response retains cursors and retries after 2, 5, then 10 minutes; later retries stay at 10 minutes.
- Recovered messages enter Core immediately and rely on existing platform-message uniqueness for idempotency.
- CAPTCHA verification runs in a separate browser profile and must not stop the primary Browser Worker or Socket.
- Empty heartbeat names never replace the last valid `account_display_name`.
- Do not replay old mention messages during deployment.
- Do not log or persist Cookie values, access tokens, or CAPTCHA traces.

---

### Task 1: Preserve the last valid AI account name

**Files:**
- Modify: `src/dzmm_bot/core/repository.py:17065-17117`
- Test: `tests/core/test_repository.py:8760-8820`

**Interfaces:**
- Consumes: `WorkerHeartbeat.account_display_name: str | None`
- Produces: `CoreRepository.record_worker_heartbeat()` that leaves the stored name unchanged when the incoming name is `None`.

- [ ] **Step 1: Write the failing repository regression test**

```python
def test_worker_heartbeat_without_name_preserves_last_valid_name(repository, now):
    repository.record_worker_heartbeat(
        WorkerHeartbeat(
            "browser-worker-1", LoginState.READY, now,
            account_display_name="饭饭（小狗青巫）.",
        )
    )
    updated = repository.record_worker_heartbeat(
        WorkerHeartbeat(
            "browser-worker-1", LoginState.READY,
            now + timedelta(seconds=5), account_display_name=None,
        )
    )
    assert updated.account_display_name == "饭饭（小狗青巫）."
    assert repository.ai_mention_names() == ("饭饭（小狗青巫）.",)
```

- [ ] **Step 2: Run the exact test and verify that it fails because the stored name becomes `None`**

Run: `pytest tests/core/test_repository.py::test_worker_heartbeat_without_name_preserves_last_valid_name -v`

- [ ] **Step 3: Build the heartbeat upsert update map conditionally**

```python
update_values = {
    "login_state": statement.excluded.login_state,
    "listening": statement.excluded.listening,
    "recorded_at": statement.excluded.recorded_at,
}
if heartbeat.account_display_name is not None:
    update_values["account_display_name"] = statement.excluded.account_display_name
```

- [ ] **Step 4: Run the focused repository tests**

Run: `pytest tests/core/test_repository.py -k 'heartbeat or mention_names' -v`

- [ ] **Step 5: Commit the isolated fix**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "fix: preserve AI mention name across reconnects"
```

### Task 2: Persist shadow synchronization state per group

**Files:**
- Create: `migrations/versions/20260819_50_message_shadow_sync.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Modify: `src/dzmm_bot/runtime/contracts.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/browser/core_client.py`
- Test: `tests/core/test_repository.py`
- Test: `tests/core/test_app.py`
- Test: `tests/browser/test_core_client.py`
- Test: `tests/deploy/test_message_shadow_sync_migration.py`

**Interfaces:**
- Produces: `GroupChatTarget.shadow_cursor_at`, `shadow_cursor_message_id`, `shadow_next_retry_at`, and `shadow_failure_count`.
- Produces: `ShadowSyncRuntimeUpdate` with group ID, state, cursor, attempt/success/retry times, failure count, and error summary.
- Produces: `POST /internal/group-chats/shadow-sync-runtime` and extended target/runtime responses.

- [ ] **Step 1: Write migration and repository tests for default state and round-trip updates**

```python
update = ShadowSyncRuntimeUpdate(
    group_chat_id=group.id,
    state="healthy",
    cursor_at=now,
    cursor_message_id="message-9",
    last_attempt_at=now,
    last_success_at=now,
    next_retry_at=now + timedelta(seconds=60),
    failure_count=0,
)
repository.record_shadow_sync_runtime("browser-worker-1", (update,), now)
target = repository.enabled_group_targets()[0]
assert target.shadow_cursor_message_id == "message-9"
```

- [ ] **Step 2: Run the new tests and verify missing schema/API failures**

Run: `pytest tests/core/test_repository.py -k shadow_sync tests/core/test_app.py -k shadow_sync tests/deploy/test_message_shadow_sync_migration.py -v`

- [ ] **Step 3: Add nullable shadow state columns to `group_chat_runtime_states`**

Add `shadow_sync_state`, `shadow_cursor_at`, `shadow_cursor_message_id`, `shadow_last_attempt_at`, `shadow_last_success_at`, `shadow_next_retry_at`, `shadow_failure_count`, and `shadow_error_summary`. Migration downgrade removes exactly these columns.

- [ ] **Step 4: Add contracts, repository persistence, and Core endpoints**

```python
@dataclass(frozen=True)
class ShadowSyncRuntimeUpdate:
    group_chat_id: UUID
    state: str
    cursor_at: datetime | None = None
    cursor_message_id: str | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    next_retry_at: datetime | None = None
    failure_count: int = 0
    error_summary: str | None = None
```

Only allow states `idle`, `healthy`, `retrying`, and `captcha_required`. Preserve the prior cursor whenever an update omits a new cursor.

- [ ] **Step 5: Extend Browser CoreClient target parsing and runtime reporting**

Add `sync_shadow_runtime(worker_id, updates, now) -> bool`; never place credentials or message text in its payload.

- [ ] **Step 6: Run Core, browser-client, and migration tests**

Run: `pytest tests/core/test_repository.py -k 'group_chat or shadow_sync' tests/core/test_app.py -k 'group_chat or shadow_sync' tests/browser/test_core_client.py tests/deploy/test_message_shadow_sync_migration.py -v`

- [ ] **Step 7: Commit durable state support**

```bash
git add migrations/versions/20260819_50_message_shadow_sync.py src/dzmm_bot/core/schema.py src/dzmm_bot/runtime/contracts.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/app.py src/dzmm_bot/browser/core_client.py tests/core/test_repository.py tests/core/test_app.py tests/browser/test_core_client.py tests/deploy/test_message_shadow_sync_migration.py
git commit -m "feat: persist message shadow sync state"
```

### Task 3: Implement the isolated HTTP shadow synchronizer

**Files:**
- Create: `src/dzmm_bot/browser/shadow_sync.py`
- Test: `tests/browser/test_shadow_sync.py`

**Interfaces:**
- Consumes: immutable `ShadowSyncRequest` containing origin, Cookie string, access token, and per-group cursors.
- Produces: `ShadowSyncResult` containing parsed `InboundMessage` values plus per-group next cursors and status.
- Produces: `ShadowSyncRunner.submit(request) -> bool`, `take_result() -> ShadowSyncResult | None`, and `close() -> None`.

- [ ] **Step 1: Write failing tests for single-flight behavior, request encoding, parsing, timeout, 418, 401, and 5xx**

```python
def test_shadow_sync_classifies_captcha_without_advancing_cursor(http_server):
    runner = ShadowSyncRunner(client=FakeClient(status=418))
    assert runner.submit(request)
    result = wait_for_result(runner)
    assert result.status == "captcha_required"
    assert result.cursors == request.cursors
    assert result.messages == ()
```

- [ ] **Step 2: Run the new test module and verify imports fail**

Run: `pytest tests/browser/test_shadow_sync.py -v`

- [ ] **Step 3: Implement a one-worker executor and exact tRPC response parser**

Use `httpx.Client(timeout=5)` and `ThreadPoolExecutor(max_workers=1)`. Send one batch of at most 50 group cursors to `chatroom.syncChatroomMessages`. Parse only text messages with valid IDs, senders, timestamps, and room IDs using the same validation rules as `AikdaSocketGateway._accept_message`.

- [ ] **Step 4: Implement result classification**

Return `captcha_required` only for status 418 with `error == "captcha_required"`, `auth_required` for 401/403, `retrying` for timeouts/5xx/invalid responses, and `healthy` for a valid 200 response.

- [ ] **Step 5: Run the shadow synchronizer tests**

Run: `pytest tests/browser/test_shadow_sync.py -v`

- [ ] **Step 6: Commit the isolated synchronizer**

```bash
git add src/dzmm_bot/browser/shadow_sync.py tests/browser/test_shadow_sync.py
git commit -m "feat: add isolated message shadow synchronizer"
```

### Task 4: Integrate shadow synchronization with Socket and Worker scheduling

**Files:**
- Modify: `src/dzmm_bot/browser/aikda_socket.py`
- Modify: `src/dzmm_bot/browser/session.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Modify: `src/dzmm_bot/browser/main.py`
- Test: `tests/browser/test_aikda_socket.py`
- Test: `tests/browser/test_session.py`
- Test: `tests/browser/test_worker.py`

**Interfaces:**
- Consumes: Task 2 persisted cursors and Task 3 `ShadowSyncRunner`.
- Produces: credential snapshots updated only on the gateway owner thread.
- Produces: immediate idempotent inbound dispatch and persisted retry scheduling.

- [ ] **Step 1: Write failing Worker tests for healthy polling, duplicate delivery, Socket disconnect, and 418 backoff**

```python
def test_shadow_messages_are_dispatched_while_socket_is_connected(context):
    context.shadow.complete(messages=[message], status="healthy")
    context.worker.run_once()
    assert context.core.inbound == [message]
    assert context.gateway.close_calls == 0
```

Also assert retry delays of 120, 300, and 600 seconds, retention of the prior cursor on failures, and immediate scheduling after an explicit Socket disconnect.

- [ ] **Step 2: Run the focused Worker tests and verify failures**

Run: `pytest tests/browser/test_worker.py -k 'shadow or disconnect' tests/browser/test_aikda_socket.py -k credential -v`

- [ ] **Step 3: Snapshot credentials on the gateway owner thread**

When Socket authentication succeeds, pass the already obtained access token and Cookie string to the shadow runner. Do not call Playwright providers from the shadow executor.

- [ ] **Step 4: Schedule polling without blocking normal work**

Worker run loops only submit or collect a shadow future. Use a deterministic injectable jitter source in tests. On healthy results, queue messages immediately and report cursors; on 418, report retained cursors and backoff; on 401/403, enter the existing authentication-loss path.

- [ ] **Step 5: Keep failed reconciliation durable**

Replace the current pop-and-forget history reconciliation behavior. A failed group remains represented by its persisted cursor and next retry time; no failed room is silently discarded.

- [ ] **Step 6: Run all Browser tests**

Run: `pytest tests/browser -v`

- [ ] **Step 7: Commit Worker integration**

```bash
git add src/dzmm_bot/browser/aikda_socket.py src/dzmm_bot/browser/session.py src/dzmm_bot/browser/worker.py src/dzmm_bot/browser/main.py tests/browser/test_aikda_socket.py tests/browser/test_session.py tests/browser/test_worker.py
git commit -m "feat: reconcile missed messages beside socket"
```

### Task 5: Add the independent CAPTCHA verification desktop and leases

**Files:**
- Modify: `migrations/versions/20260819_50_message_shadow_sync.py`
- Modify: `src/dzmm_bot/auth_desktop.py`
- Modify: `src/dzmm_bot/runtime/settings.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/browser/core_client.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Modify: `src/dzmm_bot/browser/main.py`
- Test: `tests/admin/test_auth_desktop.py`
- Test: `tests/core/test_repository.py`
- Test: `tests/core/test_app.py`
- Test: `tests/browser/test_worker.py`

**Interfaces:**
- Produces worker commands `start_access_verification`, `finish_access_verification`, and `cancel_access_verification`.
- Produces a manual-operation lease with purpose `login` or `access_verification`.
- Produces verification noVNC port `settings.novnc_port + 1`, VNC port 15901, CDP port 19223, and display `:98`.

- [ ] **Step 1: Write failing desktop tests proving two browser stacks use distinct resources**

```python
def test_verification_desktop_does_not_require_primary_browser_to_stop(tmp_path):
    controller = verification_controller(
        tmp_path, browser_stopped=lambda: False, login_state=lambda: "ready"
    )
    controller.start()
    commands = controller_commands()
    assert "--remote-debugging-port=19223" in commands.chrome
    assert commands.xvfb[:2] == ("Xvfb", ":98")
```

- [ ] **Step 2: Write failing lease/API/Worker tests**

Assert login and verification leases are mutually exclusive; verification start leaves `login_state`, `_listening`, and the primary gateway unchanged; successful shadow sync automatically completes verification and requests an immediate all-group sync.

- [ ] **Step 3: Generalize `AuthDesktopController` resource parameters without changing login defaults**

Parameterize display number, CDP port, VNC port, required login state, and the “primary browser must be stopped” precondition. Existing login construction retains exactly `:99`, 19222, 15900, and the existing preconditions.

- [ ] **Step 4: Add lease purpose and verification Core endpoints**

Add a non-null `purpose` column with server default `login` to `manual_login_leases`. Repository methods enforce a single row across both purposes. Worker auto-completion may clear only an `access_verification` lease.

- [ ] **Step 5: Wire verification commands into Browser Worker**

Start/finish/cancel only operate on the independent controller. They never call `BrowserSession.stop()`, never set listening false, and never change login state. A healthy shadow result closes the verification controller and reports completion to Core.

- [ ] **Step 6: Run desktop, Core, and Worker verification tests**

Run: `pytest tests/admin/test_auth_desktop.py tests/core/test_repository.py -k 'manual or verification' tests/core/test_app.py -k 'manual or verification' tests/browser/test_worker.py -k verification -v`

- [ ] **Step 7: Commit verification orchestration**

```bash
git add migrations/versions/20260819_50_message_shadow_sync.py src/dzmm_bot/auth_desktop.py src/dzmm_bot/runtime/settings.py src/dzmm_bot/core/schema.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/browser/core_client.py src/dzmm_bot/browser/worker.py src/dzmm_bot/browser/main.py tests/admin/test_auth_desktop.py tests/core/test_repository.py tests/core/test_app.py tests/browser/test_worker.py
git commit -m "feat: verify platform access without stopping socket"
```

### Task 6: Expose verification and shadow health in the admin console

**Files:**
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css`
- Test: `tests/admin/test_app.py`

**Interfaces:**
- Consumes: Task 2 runtime fields and Task 5 access-verification lease/endpoints.
- Produces authenticated `/api/access-verification/*` routes and `/access-verification-console` noVNC proxy.

- [ ] **Step 1: Write failing admin route and rendered-markup tests**

Assert only authenticated administrators can start/finish/cancel verification, lease ownership is enforced, the verification console proxies only loopback `novnc_port + 1`, and status markup contains distinct Socket and shadow-sync labels.

- [ ] **Step 2: Run focused admin tests and verify missing routes/elements**

Run: `pytest tests/admin/test_app.py -k 'access_verification or shadow_sync' -v`

- [ ] **Step 3: Add the access-verification card and controls**

Render state, last attempt, last success, next retry, and error summary. Starting verification opens the dedicated authenticated iframe without changing the existing login controls.

- [ ] **Step 4: Add authenticated noVNC HTTP and WebSocket proxy routes**

Use a separate console session cookie/path and a `NoVNCClient`/`NoVNCWebSocketConnector` targeting loopback `settings.novnc_port + 1`. Never accept a client-provided upstream host or port.

- [ ] **Step 5: Show per-group shadow status in group management**

Keep Socket connection status and shadow state separate. Do not label a group “connected” based solely on HTTP sync success.

- [ ] **Step 6: Run all admin tests**

Run: `pytest tests/admin -v`

- [ ] **Step 7: Commit the admin feature**

```bash
git add src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/admin/test_app.py
git commit -m "feat: manage platform access verification"
```

### Task 7: Full verification and release readiness

**Files:**
- Modify only files required by failures caused by Tasks 1-6.

**Interfaces:**
- Produces a locally complete, committed implementation ready for deployment approval.

- [ ] **Step 1: Run formatting and static checks already configured by the project**

Run: `git diff --check`

- [ ] **Step 2: Run the complete test suite**

Run: `pytest -q`

- [ ] **Step 3: Verify Alembic has one head and upgrade/downgrade round-trips in migration tests**

Run: `alembic heads`

Expected: exactly one head, `20260819_50`.

- [ ] **Step 4: Review the final diff for secrets and unrelated changes**

Run: `git status --short && git diff HEAD~6 --stat && rg -n 'access_token|Cookie:' src tests migrations/versions/20260819_50_message_shadow_sync.py`

Expected: no token or Cookie values are present; only intentional field names and test fixtures appear.

- [ ] **Step 5: Report local completion and wait for explicit deployment authorization**

Do not deploy, alter production data, or restore the production worker name until the user explicitly approves deployment.

