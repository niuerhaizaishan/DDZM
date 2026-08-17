# 多群聊管理与群级玩法隔离 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 DZMM 从单一 `DZMM_CHAT_URL` 升级为后台可实时管理的多群系统，同时保持员工与经济全局共享、所有群内临时玩法按群隔离。

**Architecture:** 数据库保存群配置和运行状态，Core 在每条群入站上解析不可变 `group_chat_id`，单 Browser Worker 动态加入多个 Socket 房间。所有群级状态机显式接收群 ID；余额、每日次数、档案和 AI 稳定画像仍使用全局用户维度。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、FastAPI/Pydantic、WebSocket/Aikda tRPC、vanilla JavaScript/HTML、pytest。

## Global Constraints

- 单 Worker 同时加入多个群；新增、停用和重连无需进程重启。
- 员工、余额、部门、档案、物品、AI 额度、稳定画像、活动事实及所有每日次数全局共享。
- 游戏、随机事件、红包、躲猫猫、报名与群级 AI 当前对话按群隔离。
- 同一员工可跨群同时参与；所有余额写入继续按全局用户行加锁，禁止透支。
- 每群提供 `listening_enabled`、`games_enabled`、`random_events_enabled`、`announcements_enabled` 四个开关。
- 普通群出站和 Bot Token 长消息必须显式指定来源群，禁止依赖 `__group__` 或启动时固定群。
- 现有 `.env` 主群自动引导为数据库“主群聊”；未完成引导时 Worker 不静默使用第二套配置。
- 停用/删除前必须无活动玩法，最后一个监听群不可停用；删除为软删除。
- 本次只实现和验证，不执行部署；部署必须等待用户再次确认。

## File Structure

- Create `migrations/versions/20260818_45_multi_group_chat.py`: 群表、历史回填、群外键和按群唯一索引。
- Modify `src/dzmm_bot/core/schema.py`: 群配置/运行态 ORM，并给群级业务增加 `group_chat_id`。
- Modify `src/dzmm_bot/core/repository.py`: 群 CRUD、引导、运行态、群解析、群作用域玩法和多群定时任务。
- Modify `src/dzmm_bot/core/api_models.py`, `src/dzmm_bot/core/app.py`: Core 群配置、Worker 同步、群运行态和多条当前玩法 API。
- Modify `src/dzmm_bot/runtime/contracts.py`: 群目标/状态同步合同。
- Modify `src/dzmm_bot/core/service.py`, `src/dzmm_bot/core/commands.py`: 入站群上下文与回复目标继承。
- Modify `src/dzmm_bot/browser/core_client.py`, `src/dzmm_bot/browser/aikda_socket.py`, `src/dzmm_bot/browser/session.py`, `src/dzmm_bot/browser/worker.py`, `src/dzmm_bot/browser/main.py`: 动态多群收发。
- Modify `src/dzmm_bot/admin/core_client.py`, `src/dzmm_bot/admin/app.py`, `src/dzmm_bot/admin/templates/index.html`, `src/dzmm_bot/admin/static/admin.js`: 群聊管理和多群玩法视图。
- Modify `src/dzmm_bot/ai/social_context.py`, `src/dzmm_bot/core/repository.py`: 当前群 15 轮、跨群最新 30 条和群筛选。
- Create `tests/deploy/test_multi_group_chat_migration.py`; modify core/browser/admin/AI tests covering every boundary.

---

### Task 1: 群聊 ORM、历史迁移与主群引导

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`
- Create: `migrations/versions/20260818_45_multi_group_chat.py`
- Create: `tests/deploy/test_multi_group_chat_migration.py`
- Modify: `tests/core/test_repository.py`
- Modify: `src/dzmm_bot/core/app.py`

**Interfaces:**
- Produces `PRIMARY_GROUP_CHAT_ID = UUID("00000000-0000-0000-0000-000000000001")` in schema/migration shared by value.
- Produces ORM `GroupChatRecord` and `GroupChatRuntimeStateRecord`.
- Produces repository `bootstrap_primary_group(chat_url: str, now: datetime) -> GroupChatConfig` and `group_chat_bootstrap_ready() -> bool`.

- [ ] **Step 1: Write failing migration-shape and backfill tests**

```python
def test_multi_group_migration_backfills_legacy_group_rows(connection):
    upgrade_to_20260817_44(connection)
    seed_legacy_inbound_outbound_and_active_games(connection)
    upgrade_to_head(connection)
    primary = connection.execute(sa.text(
        "select id, name, chatroom_id from group_chats"
    )).one()
    assert str(primary.id) == "00000000-0000-0000-0000-000000000001"
    assert primary.name == "主群聊待引导"
    assert primary.chatroom_id is None
    for table in GROUP_SCOPED_TABLES:
        assert connection.execute(sa.text(
            f"select count(*) from {table} where group_chat_id is null"
        )).scalar_one() == 0
```

`GROUP_SCOPED_TABLES` in the test is the explicit tuple: `inbound_messages`, `outbound_messages`, `undercover_sessions`, `blame_games`, `red_packets`, `number_bomb_games`, `hide_and_seek_games`, `memory_assessment_games`, `random_event_schedules`, `random_events`, `income_report_deliveries`.

- [ ] **Step 2: Run the migration test and verify it fails**

Run: `pytest -q tests/deploy/test_multi_group_chat_migration.py`
Expected: FAIL because revision `20260818_45` and `group_chats` do not exist.

- [ ] **Step 3: Add ORM records, group foreign keys and migration**

Create nullable `chat_url/chatroom_id` only for the fixed pending-bootstrap row. Add group foreign keys to all explicit tables above. Replace each global activity index with a partial unique index on `group_chat_id`; change hide-and-seek selecting uniqueness to `(group_chat_id, user_id)` and schedule/report delivery uniqueness to include `group_chat_id`. Replace the single inbound message-ID index with one unique partial index on `(group_chat_id, platform_message_id)` for group messages and another on `(chatroom_id, platform_message_id)` for direct messages, so identical platform IDs in different rooms do not collide. Keep all daily-count tables unchanged and global.

- [ ] **Step 4: Write failing bootstrap tests**

```python
def test_bootstrap_primary_group_normalizes_env_url_once(repository, now):
    group = repository.bootstrap_primary_group(
        "https://www.aikda.com/chat?c=group-main&utm_source=test#ignored", now
    )
    assert group.name == "主群聊"
    assert group.chat_url == "https://www.aikda.com/chat?c=group-main"
    assert group.chatroom_id == "group-main"
    assert group.listening_enabled and group.games_enabled
    assert group.random_events_enabled and group.announcements_enabled
    assert repository.bootstrap_primary_group(group.chat_url, now).id == group.id
```

- [ ] **Step 5: Implement URL normalization and Core startup bootstrap**

Add `normalize_group_chat_url(url: str, allowed_origin: str | None) -> tuple[str, str]` to repository or a focused `core/group_chats.py` if repository size becomes impractical. `create_server` and `create_app_from_environment` call bootstrap with `settings.chat_url` before serving; missing/invalid URL leaves health degraded and does not activate group business.

- [ ] **Step 6: Run migration/bootstrap tests and commit**

Run: `pytest -q tests/deploy/test_multi_group_chat_migration.py tests/core/test_repository.py -k 'group_chat or bootstrap'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/schema.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/app.py migrations/versions/20260818_45_multi_group_chat.py tests/deploy/test_multi_group_chat_migration.py tests/core/test_repository.py
git commit -m "feat: persist multi-group chat configuration"
```

---

### Task 2: 群聊 CRUD、运行态与 Core/Admin API

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`

**Interfaces:**
- Produces `GroupChatConfig`, `GroupChatRuntimeState`, `GroupChatTarget` dataclasses.
- Repository methods: `list_group_chats(include_deleted: bool = False) -> tuple[GroupChatConfig, ...]`, `create_group_chat(name: str, chat_url: str, listening_enabled: bool, games_enabled: bool, random_events_enabled: bool, announcements_enabled: bool, now: datetime) -> GroupChatConfig`, `update_group_chat(group_id: UUID, *, name: str | None = None, chat_url: str | None = None, listening_enabled: bool | None = None, games_enabled: bool | None = None, random_events_enabled: bool | None = None, announcements_enabled: bool | None = None, now: datetime) -> GroupChatConfig`, `soft_delete_group_chat(group_id: UUID, now: datetime) -> GroupChatConfig`, `enabled_group_targets() -> tuple[GroupChatTarget, ...]`, `record_group_chat_runtime(worker_id: str, statuses: tuple[GroupChatRuntimeUpdate, ...], now: datetime) -> None`.
- Core routes: `GET/POST /internal/group-chats`, `PATCH/DELETE /internal/group-chats/{id}`, `GET /internal/group-chats/targets`, `POST /internal/group-chats/runtime`.
- Admin routes mirror CRUD under `/api/group-chats` with configuration version fencing.

- [ ] **Step 1: Write failing repository safety tests**

```python
def test_group_chat_duplicate_and_last_enabled_guards(repository, now):
    primary = ready_primary_group(repository, now)
    assert repository.create_group_chat(
        "第二群", "https://www.aikda.com/chat?c=group-2", True, True, True, True, now
    ).chatroom_id == "group-2"
    with pytest.raises(GroupChatConflict, match="duplicate_chatroom"):
        repository.create_group_chat(
            "重复群", "https://www.aikda.com/chat?c=group-2", True, True, True, True, now
        )
    repository.update_group_chat(primary.id, listening_enabled=False, now=now)
    with pytest.raises(GroupChatConflict, match="last_enabled_group"):
        repository.update_group_chat(group_id_for(repository, "group-2"), listening_enabled=False, now=now)
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `pytest -q tests/core/test_repository.py tests/core/test_app.py tests/admin/test_app.py -k group_chat`
Expected: FAIL with missing methods and routes.

- [ ] **Step 3: Implement CRUD, soft delete, activity guard and audit**

Lock the target group for update. Validate unique name, normalized URL and same origin. Before disabling/deleting call `group_has_active_gameplay(group_id, now)`. Soft delete sets all switches false plus `deleted_at`; runtime state becomes disabled. Write an `AuditEventRecord` containing only non-sensitive before/after fields.

- [ ] **Step 4: Implement Pydantic and versioned admin APIs**

Use explicit models; never return Cookie, Token or authorization data. Runtime updates do not bump config revision. `POST/PATCH/DELETE` admin calls use the existing `versioned_configuration_response`, `If-Match` and idempotency key flow.

- [ ] **Step 5: Run API tests and commit**

Run: `pytest -q tests/core/test_app.py tests/admin/test_app.py -k group_chat`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py tests/core/test_repository.py tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: manage group chats through admin api"
```

---

### Task 3: Runtime 合同与单 Worker 动态多群 Socket

**Files:**
- Modify: `src/dzmm_bot/runtime/contracts.py`
- Modify: `src/dzmm_bot/browser/core_client.py`
- Modify: `src/dzmm_bot/browser/aikda_socket.py`
- Modify: `src/dzmm_bot/browser/session.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Modify: `src/dzmm_bot/browser/main.py`
- Modify: `tests/browser/test_core_client.py`
- Modify: `tests/browser/test_aikda_socket.py`
- Modify: `tests/browser/test_session.py`
- Modify: `tests/browser/test_worker.py`
- Modify: `tests/runtime/test_production_entrypoints.py`

**Interfaces:**
- Adds immutable `GroupChatTarget(group_chat_id, chatroom_id, chat_url)` and `GroupChatRuntimeUpdate` contracts.
- `CoreClient.group_chat_targets() -> tuple[GroupChatTarget, ...]` and `sync_group_chat_runtime(updates, now) -> bool`.
- `ChatGateway.configure_group_rooms(targets)` replaces the single fixed group assumption while preserving direct-room methods.

- [ ] **Step 1: Write failing multi-room Socket tests**

```python
def test_gateway_accepts_only_configured_groups_and_known_direct_rooms(gateway):
    gateway.configure_group_rooms((target("group-a"), target("group-b")))
    gateway.configure_direct_rooms(("direct-1",))
    emit_message(gateway, "group-a", "ga-1")
    emit_message(gateway, "group-b", "gb-1")
    emit_message(gateway, "direct-1", "dm-1")
    emit_message(gateway, "unknown-room", "bad-1")
    assert [(m.source_type, m.chatroom_id) for m in gateway.read_new()] == [
        ("group", "group-a"), ("group", "group-b"), ("direct", "direct-1")
    ]
```

- [ ] **Step 2: Run browser tests and verify failures**

Run: `pytest -q tests/browser/test_aikda_socket.py tests/browser/test_worker.py -k 'group or room'`
Expected: FAIL because the gateway still owns one `chatroom_id`.

- [ ] **Step 3: Refactor gateway/session to configured group sets**

Maintain separate `_group_chatroom_ids` and `_direct_chatroom_ids`; unknown rooms are discarded, never classified as direct. Join/rejoin each enabled group, maintain per-room history reconciliation, and continue after one room error. `BrowserSession` keeps one authenticated page only for token/cookies; it does not navigate one page per group.

- [ ] **Step 4: Add worker live-sync and failure-isolation tests**

```python
def test_worker_adds_and_removes_groups_without_restart(worker, core, session, now):
    core.group_targets = [target("group-a")]
    worker.run_once()
    assert session.configured_group_ids == {"group-a"}
    core.group_targets = [target("group-a"), target("group-b")]
    worker.run_once()
    assert session.configured_group_ids == {"group-a", "group-b"}
    core.group_targets = [target("group-b")]
    worker.run_once()
    assert session.configured_group_ids == {"group-b"}
    assert core.runtime_updates[-1]["group-a"].connection_state == "disabled"
```

- [ ] **Step 5: Implement periodic target sync and per-group runtime reporting**

Worker fetches targets at startup and a short fixed interval, applies additions/removals, and reports pending/connected/failed/disabled plus last timestamps. Keep the last successful target snapshot during transient Core fetch failure, but do not accept business messages that Core later rejects.

- [ ] **Step 6: Run browser/runtime tests and commit**

Run: `pytest -q tests/browser tests/runtime/test_production_entrypoints.py`
Expected: PASS.

```bash
git add src/dzmm_bot/runtime/contracts.py src/dzmm_bot/browser/core_client.py src/dzmm_bot/browser/aikda_socket.py src/dzmm_bot/browser/session.py src/dzmm_bot/browser/worker.py src/dzmm_bot/browser/main.py tests/browser tests/runtime/test_production_entrypoints.py
git commit -m "feat: listen to multiple group rooms"
```

---

### Task 4: Core 入站解析、显式群出站和长消息目标

**Files:**
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/browser/worker.py`
- Modify: `src/dzmm_bot/browser/bot_api.py`
- Modify: `tests/core/test_service.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/browser/test_worker.py`
- Modify: `tests/browser/test_bot_api.py`

**Interfaces:**
- `InboundRecord.group_chat_id` and `OutboundRecord.group_chat_id` become the Core group truth.
- `CoreService.receive_inbound` resolves group messages before command/AI processing and creates all group replies with explicit destination/group.
- `enqueue_system_outbound(text: str, *, recall_after_seconds: int | None = None, memory_round_id: UUID | None = None, group_chat_id: UUID | None = None, destination_chatroom_id: str | None = None, delivery_kind: str = "group") -> OutboundRecord` requires non-null group and destination fields for group delivery; the same `group_chat_id` keyword is added to `enqueue_outbound` and `enqueue_image_outbound`.

- [ ] **Step 1: Write failing inbound rejection and reply-target tests**

```python
def test_group_reply_inherits_source_group_and_disabled_group_is_rejected(service, repository, factory, now):
    add_group(repository, "group-a", enabled=True)
    add_group(repository, "group-b", enabled=False)
    accepted = receive(service, "m-a", "p1", "/余额", now, chatroom_id="group-a")
    rejected = receive(service, "m-b", "p1", "/余额", now, chatroom_id="group-b")
    outbound = outbound_for(factory, accepted.message_id)
    assert outbound.destination_chatroom_id == "group-a"
    assert outbound.delivery_key == "group-a"
    assert rejected.inserted is False

def test_same_platform_message_id_is_unique_per_room(service, repository, now):
    add_group(repository, "group-a", enabled=True)
    add_group(repository, "group-b", enabled=True)
    assert receive(service, "same-id", "p1", "/余额", now, chatroom_id="group-a").inserted
    assert receive(service, "same-id", "p1", "/余额", now, chatroom_id="group-b").inserted
    assert not receive(service, "same-id", "p1", "/余额", now, chatroom_id="group-a").inserted
```

- [ ] **Step 2: Run focused Core/browser tests and verify failures**

Run: `pytest -q tests/core/test_service.py tests/core/test_group_commands.py tests/browser/test_worker.py -k 'group_target or disabled_group or bot'`
Expected: FAIL because group outputs still fall back to `__group__`.

- [ ] **Step 3: Implement explicit group context through service and repository**

Add a `GroupMessageContext(group_chat_id, chatroom_id)` value passed to command handling or attached to the accepted inbound. Direct messages keep no group ID. Reject unknown/disabled group before activity, AI or memory eligibility. Reference snapshots only survive when inbound and outbound target the same group.

- [ ] **Step 4: Route Bot Token by each outbound target**

Remove BrowserWorker's fixed `_bot_chatroom_id` decision. For a long group outbound, call `bot_sender.send_to(outbound.destination_chatroom_id, text)`; missing destination is a permanent contract failure. Short messages use `session.send_to` with the same destination.

- [ ] **Step 5: Run Core/browser routing tests and commit**

Run: `pytest -q tests/core/test_service.py tests/core/test_group_commands.py tests/browser/test_worker.py tests/browser/test_bot_api.py`
Expected: PASS.

```bash
git add src/dzmm_bot/core/service.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/app.py src/dzmm_bot/browser/worker.py src/dzmm_bot/browser/bot_api.py tests/core/test_service.py tests/core/test_group_commands.py tests/browser/test_worker.py tests/browser/test_bot_api.py
git commit -m "feat: route messages to explicit groups"
```

---

### Task 5: 通用玩法上下文、开关与后台多条当前玩法

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`

**Interfaces:**
- Changes `active_gameplay_summary(group_chat_id, platform_id, now)` and `force_end_gameplay(group_chat_id, game_type, game_id, now)`.
- Produces `current_gameplay_admin_summaries(now) -> tuple[GameplayAdminSummary, ...]`.
- Adds `assert_group_can_create_game(group_chat_id, now)`; existing-game operations bypass only the create switch, not listening.

- [ ] **Step 1: Write failing same-game-in-two-groups tests**

```python
def test_unified_gameplay_routes_only_source_group(repository, now):
    ga, gb = two_groups(repository, now)
    create_number_bomb(repository, ga.id, "p1", now)
    create_number_bomb(repository, gb.id, "p2", now)
    assert repository.active_gameplay_summary(ga.id, "p1", now).game_id != \
        repository.active_gameplay_summary(gb.id, "p2", now).game_id
    assert repository.active_gameplay_summary(ga.id, "p2", now).role == "not_joined"
```

- [ ] **Step 2: Run gameplay routing tests and verify failures**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py -k 'gameplay and group'`
Expected: FAIL because current summaries are global.

- [ ] **Step 3: Thread group ID through universal routes and create switches**

Every group command reads `InboundRecord.group_chat_id`; `/当前游戏`, `/加入`, `/退出`, `/开始`, `/继续`, `/跳过`, `/结束游戏` never search another group. `games_enabled=false` blocks only create entrypoints; already-active join/action/exit/settlement continues.

- [ ] **Step 4: Replace the singular admin current-game response with a list**

Each item contains group ID/name, game type/id, public state and participants. Force-end identity is `(group_chat_id, game_type, game_id)` and retains `If-Match`. No secret role/number/card fields enter the response.

- [ ] **Step 5: Run routing/API tests and commit**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py tests/admin/test_app.py -k 'gameplay or group'`
Expected: PASS for general routing contracts; specific game behavior follows Tasks 6–8.

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/core_client.py tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: scope gameplay routing by group"
```

---

### Task 6: 红包、躲猫猫与记忆考核按群隔离

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_red_packet.py`

**Interfaces:**
- All create/join/action/expire methods for red packet, hide-and-seek and memory assessment accept `group_chat_id`.
- Daily play/start records remain keyed only by `(user_id, play_date)`.

- [ ] **Step 1: Write failing cross-group isolation and global-limit tests**

```python
def test_red_packets_are_per_group_but_daily_limit_is_global(repository, now):
    ga, gb = two_groups(repository, now)
    packet_a = repository.create_red_packet(ga.id, "p1", 2, 10, now)
    packet_b = repository.create_red_packet(gb.id, "p2", 2, 10, now)
    assert packet_a.status == packet_b.status == "created"
    assert repository.claim_red_packet(ga.id, "p3", now).packet_id == packet_a.packet_id
    assert repository.claim_red_packet(gb.id, "p3", now).packet_id == packet_b.packet_id

def test_memory_daily_count_is_shared_across_groups(repository, now):
    ga, gb = two_groups(repository, now)
    exhaust_single_memory_limit(repository, ga.id, "p1", now)
    assert repository.start_memory_assessment(gb.id, "p1", now).status == "daily_limit"
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `pytest -q tests/core/test_red_packet.py tests/core/test_repository.py tests/core/test_group_commands.py -k 'red_packet or hide_and_seek or memory_assessment'`
Expected: existing single-group tests expose missing group arguments or cross-group conflicts.

- [ ] **Step 3: Scope all state queries and timeout jobs by group**

Use `group_chat_id` in game creation, selection, duel join, answers, claims, expiry and notification targets. Keep daily count queries unchanged. Expiry notifications enqueue to the owning group explicitly.

- [ ] **Step 4: Run focused suites and commit**

Run: `pytest -q tests/core/test_red_packet.py tests/core/test_repository.py tests/core/test_group_commands.py -k 'red_packet or hide_and_seek or memory_assessment'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py tests/core/test_red_packet.py tests/core/test_repository.py tests/core/test_group_commands.py
git commit -m "feat: isolate economy games by group"
```

---

### Task 7: 谁是卧底、甩锅与蹦蹦数字炸弹按群隔离

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_group_commands.py`

**Interfaces:**
- Undercover/blame/number-bomb repository lifecycle methods take `group_chat_id` first.
- Private input resolvers return stable per-command candidates `PrivateGameCandidate(index, group_chat_id, group_name, game_id)`.

- [ ] **Step 1: Write failing simultaneous-session tests**

```python
def test_same_multiplayer_game_can_run_in_two_groups(repository, now):
    ga, gb = two_groups(repository, now)
    ua = repository.start_undercover_signup(ga.id, "p1", 4, now)
    ub = repository.start_undercover_signup(gb.id, "p2", 4, now)
    assert ua.status == ub.status == "created"
    assert ua.session_id != ub.session_id

def test_ambiguous_private_number_bomb_requires_group_index(repository, now):
    ga, gb = two_groups(repository, now, names=("甲群", "乙群"))
    start_number_bomb_for_same_player(repository, ga.id, gb.id, "p1", now)
    result = repository.resolve_number_bomb_private_target("p1", group_index=None, now=now)
    assert result.status == "ambiguous"
    assert [(c.index, c.group_name) for c in result.candidates] == [(1, "乙群"), (2, "甲群")]
```

- [ ] **Step 2: Run focused multiplayer tests and verify failures**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py -k 'undercover or blame or number_bomb'`
Expected: global active indexes/methods prevent two sessions.

- [ ] **Step 3: Scope all session, job and force-end queries by group**

Replace global active lookups with `group_chat_id` predicates. Every automatic reminder, temperature, vote expiry, deal completion and settlement targets its owning group. Daily blame-game starts remain global per employee.

- [ ] **Step 4: Implement deterministic private ambiguity formats**

When one candidate exists, retain `/报数 数字` and `/看牌`. When multiple candidates exist, return groups sorted by `(name, id)` and require `/报数 群序号 数字` or `/看牌 群序号`; reject stale/out-of-range indexes with the refreshed candidate list.

- [ ] **Step 5: Run multiplayer suites and commit**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py -k 'undercover or blame or number_bomb or private_target'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py tests/core/test_repository.py tests/core/test_group_commands.py
git commit -m "feat: isolate multiplayer games by group"
```

---

### Task 8: 随机事件、定时结算与多群公告

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_app.py`

**Interfaces:**
- `schedule_random_events(now)` iterates groups with `random_events_enabled` and creates group-scoped schedules.
- Random event join/chat/exit/tip/force-end methods require group ID for group commands.
- `enqueue_announcement_for_groups(job_key, text, now)` writes one outbound per listening group with announcements enabled and unique `(job_key, group_chat_id)` delivery record.

- [ ] **Step 1: Write failing per-group scheduling tests**

```python
def test_random_event_schedule_is_per_enabled_group(repository, now):
    ga = add_group(repository, "group-a", random_events=True)
    gb = add_group(repository, "group-b", random_events=True)
    add_group(repository, "group-c", random_events=False)
    repository.schedule_random_events(now)
    schedules = repository.list_today_random_event_schedules_all_groups(now.date())
    assert {item.group_chat_id for item in schedules} == {ga.id, gb.id}
```

- [ ] **Step 2: Write failing one-settlement/many-announcements test**

```python
def test_global_activity_reward_settles_once_and_announces_to_enabled_groups(repository, now):
    ga = add_group(repository, "group-a", announcements=True)
    gb = add_group(repository, "group-b", announcements=True)
    add_group(repository, "group-c", announcements=False)
    repository.run_daily_jobs(now)
    repository.run_daily_jobs(now)
    assert activity_reward_transaction_count(repository, now.date()) == 1
    assert announcement_group_ids(repository, "activity", now.date()) == {ga.id, gb.id}
```

- [ ] **Step 3: Run random-event/job tests and verify failures**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py -k 'random_event or income_report or activity_reward or attendance'`
Expected: global schedule uniqueness and destination-less outbounds fail multi-group assertions.

- [ ] **Step 4: Implement group-scoped random events and idempotent announcement fan-out**

Global scene cards, submissions and settings remain shared. Game conflicts and skip decisions query only the schedule's group. Separate global settlement keys from per-group delivery keys; repeated jobs may retry unsent groups but never repeat balance mutations.

- [ ] **Step 5: Run event/job tests and commit**

Run: `pytest -q tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py -k 'random_event or income_report or activity_reward or attendance or announcement'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/commands.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py
git commit -m "feat: schedule events and announcements per group"
```

---

### Task 9: AI 当前群上下文、跨群最新与后台消息筛选

**Files:**
- Modify: `src/dzmm_bot/ai/social_context.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `tests/ai/test_social_context.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`

**Interfaces:**
- `ai_conversation_history(inbound_id, limit=15)` filters group messages by current inbound `group_chat_id`.
- Cross-employee latest evidence returns `RecentEmployeeMessage(content, group_name, received_at)` across enabled groups, limit 30.
- Employee history admin endpoint accepts optional `group_chat_id` filter.

- [ ] **Step 1: Write failing context-isolation tests**

```python
def test_ai_current_history_stays_in_group_but_latest_employee_evidence_crosses_groups(repository, now):
    ga, gb = two_groups(repository, now, names=("甲群", "乙群"))
    seed_ai_exchange(repository, ga.id, "p1", "甲群话题", now)
    seed_ai_exchange(repository, gb.id, "p1", "乙群话题", now)
    history = repository.ai_conversation_history(current_inbound_in(ga.id), limit=15)
    latest = repository.latest_employee_messages("p1", limit=30)
    assert "甲群话题" in history_as_text(history)
    assert "乙群话题" not in history_as_text(history)
    assert {(m.group_name, m.content) for m in latest} == {
        ("甲群", "甲群话题"), ("乙群", "乙群话题")
    }
```

- [ ] **Step 2: Run AI/repository tests and verify failures**

Run: `pytest -q tests/ai/test_social_context.py tests/core/test_repository.py tests/core/test_app.py tests/admin/test_app.py -k 'social_context or conversation or employee_history'`
Expected: current history includes both groups or lacks group labels.

- [ ] **Step 3: Implement group-filtered current context and cross-group evidence labels**

Stable impression candidate selection remains cross-group but only from configured enabled group messages. Commands/game/random-event messages keep existing exclusions. Deleted-group history remains available to admin audit but does not produce new evidence.

- [ ] **Step 4: Add backend employee-message group filter**

Expose group options and optional filter without changing employee identity or memory records. Default is all groups; direct messages remain excluded from ordinary group-history view.

- [ ] **Step 5: Run AI/admin tests and commit**

Run: `pytest -q tests/ai/test_social_context.py tests/core/test_repository.py tests/core/test_app.py tests/admin/test_app.py -k 'social_context or conversation or employee_history or group_filter'`
Expected: PASS.

```bash
git add src/dzmm_bot/ai/social_context.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py tests/ai/test_social_context.py tests/core/test_repository.py tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: make ai context group aware"
```

---

### Task 10: 后台群聊管理和多群玩法界面

**Files:**
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css`
- Modify: `tests/admin/test_app.py`
- Modify: `tests/admin/test_package_data.py`

**Interfaces:**
- Adds admin view `group-chats`, create/edit modal, four switches and runtime cards.
- Current gameplay view lists zero or more active groups and force-ends using group/type/game identity.
- Employee messages add “全部群聊/单群” filter.

- [ ] **Step 1: Add failing HTML/static contract tests**

```python
def test_admin_page_contains_multi_group_controls(admin_html):
    assert 'data-view="group-chats"' in admin_html
    assert 'id="group-chat-list"' in admin_html
    assert 'id="group-chat-name"' in admin_html
    assert 'id="group-chat-url"' in admin_html
    for switch in ("listening", "games", "random-events", "announcements"):
        assert f'id="group-chat-{switch}-enabled"' in admin_html
```

- [ ] **Step 2: Run admin tests and verify failures**

Run: `pytest -q tests/admin/test_app.py tests/admin/test_package_data.py -k 'group_chat or gameplay'`
Expected: controls and multi-game renderer are absent.

- [ ] **Step 3: Implement group list, modal, status and safety errors**

Use existing request, toast, modal, config version and If-Match patterns. Show normalized URL and read-only chatroom ID, four switches, connection state, last send/receive and sanitized error. Disable delete until the group is disabled; render server conflict messages for active/last-group guards.

- [ ] **Step 4: Implement multi-game and employee-message group filters**

Current game cards show group name and public state; each force-end button carries group ID, type and game ID. Employee history defaults to all groups and reloads on filter selection.

- [ ] **Step 5: Run admin suite and commit**

Run: `pytest -q tests/admin`
Expected: PASS.

```bash
git add src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/admin/test_app.py tests/admin/test_package_data.py
git commit -m "feat: add multi-group admin console"
```

---

### Task 11: 全链路回归、迁移合同与德州扑克后续兼容

**Files:**
- Modify only files directly required by integration failures.
- Modify: `docs/superpowers/plans/2026-08-17-texas-holdem-implementation.md` to use migration `20260818_46` with down revision `20260818_45` and require `group_chat_id` in its game table/API signatures.
- Verify: `rule.md`
- Verify: `docs/superpowers/specs/2026-08-17-multi-group-chat-management-design.md`

**Interfaces:**
- No new runtime interface; confirms every existing gameplay uses the group contract and future德州扑克 starts group-aware.

- [ ] **Step 1: Update the unexecuted德州扑克 plan revision and group contract**

Replace its planned migration name/revision with `20260818_46_texas_holdem.py` / `20260818_46`, down revision `20260818_45`; add non-null `group_chat_id` and per-group active index to the planned Texas Hold'em game table and all repository create/route signatures.

- [ ] **Step 2: Run migration and runtime contract tests**

Run: `pytest -q tests/deploy tests/runtime`
Expected: PASS; Alembic head is `20260818_45` until德州扑克 is implemented.

- [ ] **Step 3: Run focused multi-group suites**

Run: `pytest -q tests/core tests/browser tests/ai tests/admin -k 'group or gameplay or random_event or red_packet or memory or undercover or blame or number_bomb or hide_and_seek'`
Expected: PASS.

- [ ] **Step 4: Run complete test suite**

Run: `pytest -q`
Expected: all tests pass with only existing intentional skips.

- [ ] **Step 5: Inspect destination, secret and uniqueness invariants**

Run:

```bash
rg -n 'delivery_key="__group__"|destination_chatroom_id=None' src/dzmm_bot/core src/dzmm_bot/browser
rg -n 'cookie|authorization|bot_api_token' src/dzmm_bot/admin
rg -n 'one_active|active_key|group_key' src/dzmm_bot/core/schema.py migrations/versions/20260818_45_multi_group_chat.py
git diff --check
```

Expected: no active group outbound uses the single-group fallback; admin responses contain no secrets; every active uniqueness rule is group-scoped; no whitespace errors.

- [ ] **Step 6: Verify branch state without deploying**

Run: `git status --short && git log --oneline --decorate -12`
Expected: implementation branch contains reviewed task commits, no tracked changes remain, and no deploy command has been executed.
