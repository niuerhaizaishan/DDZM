# “我有你没有”游戏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** 在 DZMM 多群框架中交付可持久化恢复、可后台管理的“我有你没有”完整游戏，包括报名、轮流发言、扣心回应、超时、自由惩罚和历史记录。

**Architecture:** 使用独立设置、对局、玩家、轮次和回应表保存状态；CoreRepository 通过统一 gameplay gate 和固定锁序推进对局，定时任务依据绝对截止时间幂等补处理。通用指令、群级玩法开关、后台状态与历史接入现有 Core 和有序出站队列，不新增 Worker。

**Tech Stack:** Python 3.13、SQLAlchemy 2、Alembic、FastAPI/Pydantic、原生 HTML/CSS/JavaScript、pytest。

**Spec:** docs/superpowers/specs/2026-08-31-never-have-i-ever-game-design.md

## Global Constraints

- 玩法标识固定为 never_have_i_ever，显示名固定为“我有你没有”。
- 每人固定 5 颗心，结束阈值固定为 ceil(开局人数 / 2)，两项都不配置。
- 默认报名超时 10 分钟、发言超时 60 秒、回应超时 60 秒；三个值只接受正整数。
- /扣 表示没有该经历并失去 1 心；/不扣 表示有该经历且不扣心。
- 自由惩罚阶段无倒计时，只有发起者正常结束；董事会和后台可以强制结束。
- 不产生摸鱼币变化；只记录最终参与事实，发言、选择和惩罚聊天不进入长期记忆。
- 只处理群消息；不同群并行，同群继续受玩法互斥约束。
- 自动通知进入现有 Core 有序出站队列，不从任务直接调用平台。
- 保留当前工作树其他未部署改动；revision 20260831_64 以 20260831_63 为父节点。

---

### Task 1: 数据库迁移、ORM 与群级玩法类型

**Files:**
- Create: migrations/versions/20260831_64_never_have_i_ever.py
- Create: tests/deploy/test_never_have_i_ever_migration.py
- Modify: src/dzmm_bot/core/schema.py
- Modify: src/dzmm_bot/core/group_games.py
- Create: tests/core/test_group_games.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces: NeverHaveIEverSettingsRecord、NeverHaveIEverGameRecord、NeverHaveIEverPlayerRecord、NeverHaveIEverRoundRecord、NeverHaveIEverResponseRecord。
- Produces: GroupGameType 值 never_have_i_ever 和四个专属命令映射。
- Consumes: GroupChatRecord、UserRecord、BeijingDateTime、PRIMARY_GROUP_CHAT_ID。

- [ ] **Step 1: Write failing migration and schema tests**

~~~python
def test_never_have_i_ever_migration_upgrades_revision_63(tmp_path, monkeypatch):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'never-have-i-ever.db'}"
    monkeypatch.setenv("DZMM_DATABASE_URL", database_url)
    config = Config(str(ROOT / "alembic.ini"))
    command.stamp(config, "20260831_63")
    command.upgrade(config, "head")
    tables = set(inspect(create_engine(database_url)).get_table_names())
    assert {
        "never_have_i_ever_settings",
        "never_have_i_ever_games",
        "never_have_i_ever_players",
        "never_have_i_ever_rounds",
        "never_have_i_ever_responses",
    } <= tables


def test_never_have_i_ever_group_game_contract():
    assert "never_have_i_ever" in GROUP_GAME_TYPES
    assert GROUP_GAME_LABELS["never_have_i_ever"] == "我有你没有"
    assert GROUP_GAME_COMMANDS["/我有你没有"] == "never_have_i_ever"
    assert GROUP_GAME_COMMANDS["/扣"] == "never_have_i_ever"
~~~

- [ ] **Step 2: Run tests to verify RED**

Run: .venv/bin/pytest -q tests/deploy/test_never_have_i_ever_migration.py tests/core/test_group_games.py

Expected: FAIL because revision 64, tables and game type do not exist.

- [ ] **Step 3: Add concrete ORM records**

Add a singleton settings row with enabled, signup_timeout_minutes, statement_timeout_seconds, response_timeout_seconds and updated_at.

Add the game fields group_chat_id, host_user_id, active_key, state, initial_player_count, current_speaker_order, round_number, three deadlines, free_punishment_started_at, created_at, started_at, finished_at and finish_reason. Add a partial unique index on group_chat_id where active_key is non-null.

Add the player fields game_id, user_id, roster_order, hearts, state, joined_at, eliminated_at and elimination_reason. Enforce unique game/user, unique game/order, and hearts between 0 and 5.

Add round fields game_id, sequence, speaker_user_id, statement, state, statement_at, response_deadline, settled_at and statement_timed_out. Enforce unique game/sequence.

Add response fields round_id, user_id, choice and submitted_at. Enforce unique round/user and choice in deduct, keep, timeout_deduct.

~~~python
def _never_have_i_ever_threshold(initial_player_count: int) -> int:
    return (initial_player_count + 1) // 2
~~~

- [ ] **Step 4: Add migration revision 64**

The migration creates all five tables, foreign keys, check constraints, unique constraints and the partial active-game index. Its header is:

~~~python
revision: str = "20260831_64"
down_revision: str | None = "20260831_63"
~~~

Downgrade drops response, round, player, game and settings tables in reverse dependency order. Do not edit revision 63.

- [ ] **Step 5: Register the game type**

Add never_have_i_ever to GroupGameType, GROUP_GAME_TYPES and GROUP_GAME_LABELS. Map /我有你没有, /发言, /扣 and /不扣 in GROUP_GAME_COMMANDS.

- [ ] **Step 6: Run tests GREEN**

Run: .venv/bin/pytest -q tests/deploy/test_never_have_i_ever_migration.py tests/core/test_group_games.py tests/core/test_repository.py -k "never_have_i_ever or schema"

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add migrations/versions/20260831_64_never_have_i_ever.py tests/deploy/test_never_have_i_ever_migration.py src/dzmm_bot/core/schema.py src/dzmm_bot/core/group_games.py tests/core/test_group_games.py tests/core/test_repository.py
git commit -m "feat: add never have i ever data model"
~~~

### Task 2: 设置、报名、加入与开局

**Files:**
- Modify: src/dzmm_bot/core/repository.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces immutable projections NeverHaveIEverSettings、NeverHaveIEverPlayerView、NeverHaveIEverResult。
- Produces get_never_have_i_ever_settings、set_never_have_i_ever_settings、start_never_have_i_ever、join_never_have_i_ever、leave_never_have_i_ever、begin_never_have_i_ever。
- Consumes Task 1 ORM records and existing gameplay gate, group switch and rank-based multiplayer-start claim.

- [ ] **Step 1: Write failing signup tests**

~~~python
def test_never_have_i_ever_signup_and_host_start(repository):
    now = datetime(2026, 8, 31, 12, 0, tzinfo=BEIJING)
    for platform_id, name in (("host", "主持"), ("u2", "二号"), ("u3", "三号")):
        repository.create_user(platform_id, name, now, 0)
    created = repository.start_never_have_i_ever("host", now, PRIMARY_GROUP_CHAT_ID)
    assert created.status == "signup_started"
    assert repository.join_never_have_i_ever("u2", now, PRIMARY_GROUP_CHAT_ID).status == "joined"
    assert repository.join_never_have_i_ever("u3", now, PRIMARY_GROUP_CHAT_ID).status == "joined"
    begun = repository.begin_never_have_i_ever("host", now, PRIMARY_GROUP_CHAT_ID)
    assert begun.status == "started"
    assert [(item.number, item.hearts) for item in begun.players] == [(1, 5), (2, 5), (3, 5)]
    assert begun.current_speaker_number == 1
~~~

Add separate explicit tests for non-host start, fewer than three players, duplicate join, nonemployee, disabled setting, disabled group switch, active-game conflict and daily-limit rejection.

Add a 20-player signup/start case to prove the repository does not impose an application-level maximum.

- [ ] **Step 2: Run tests RED**

Run: .venv/bin/pytest -q tests/core/test_repository.py -k "never_have_i_ever and (settings or signup or join or start)"

Expected: FAIL with missing repository contracts.

- [ ] **Step 3: Add result contracts and settings**

~~~python
@dataclass(frozen=True)
class NeverHaveIEverSettings:
    enabled: bool
    signup_timeout_minutes: int
    statement_timeout_seconds: int
    response_timeout_seconds: int


@dataclass(frozen=True)
class NeverHaveIEverResult:
    status: str
    game_id: UUID | None = None
    group_chat_id: UUID | None = None
    display_name: str | None = None
    players: tuple[NeverHaveIEverPlayerView, ...] = ()
    current_speaker_number: int | None = None
    responded_count: int = 0
    expected_response_count: int = 0
    public_message: str | None = None
~~~

set_never_have_i_ever_settings rejects values below 1, locks the singleton and persists all fields.

- [ ] **Step 4: Implement gate-first creation and joining**

start_never_have_i_ever locks gameplay gate, reads settings, locks the user, checks group enablement and group conflicts, claims exactly one existing rank-based multiplayer start count, creates state signup with active_key global and signup deadline, then creates host player number 1.

Extend the accepted multiplayer-start kind set with never_have_i_ever so the existing rank limit and board unlimited behavior apply without a parallel counter.

join_never_have_i_ever locks gate, game and user, only accepts signup, returns already_joined idempotently, and assigns max roster_order + 1. It does not consume a daily count.

- [ ] **Step 5: Implement signup leave and host start**

Ordinary /退出 deletes or marks the signup player withdrawn without renumbering existing players. Host /退出 closes state cancelled, clears active_key and deadline, and retains history rows.

begin_never_have_i_ever verifies actor is host and active signup has at least three non-withdrawn players. It fixes initial_player_count, sets every included player to active with 5 hearts, state awaiting_statement, round_number 1, current_speaker_order to the host’s order, and statement_deadline to now plus the configured seconds.

- [ ] **Step 6: Run tests GREEN**

Run: .venv/bin/pytest -q tests/core/test_repository.py -k "never_have_i_ever and (settings or signup or join or start)"

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: add never have i ever signup"
~~~

### Task 3: 发言、回应、扣心、退出与自由惩罚

**Files:**
- Modify: src/dzmm_bot/core/repository.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces submit_never_have_i_ever_statement、respond_never_have_i_ever、end_never_have_i_ever。
- Produces internal helpers _settle_never_have_i_ever_round_locked、_advance_never_have_i_ever_locked、_enter_never_have_i_ever_free_punishment_locked、_finish_never_have_i_ever_locked。
- Extends Task 2 leave_never_have_i_ever for active states.

- [ ] **Step 1: Write the normal round test RED**

~~~python
def test_never_have_i_ever_statement_responses_and_settlement(repository):
    now = datetime(2026, 8, 31, 12, 0, tzinfo=BEIJING)
    _create_started_never_have_i_ever(repository, now, ("host", "u2", "u3"))
    statement = repository.submit_never_have_i_ever_statement(
        "host", "我得过5km第一", now, PRIMARY_GROUP_CHAT_ID
    )
    assert statement.status == "statement_recorded"
    first = repository.respond_never_have_i_ever(
        "u2", True, now, PRIMARY_GROUP_CHAT_ID
    )
    assert first.status == "response_recorded"
    assert (first.responded_count, first.expected_response_count) == (1, 2)
    settled = repository.respond_never_have_i_ever(
        "u3", False, now, PRIMARY_GROUP_CHAT_ID
    )
    assert settled.status == "round_settled"
    assert [(item.number, item.hearts) for item in settled.players] == [(1, 5), (2, 4), (3, 5)]
    assert settled.current_speaker_number == 2
~~~

The test helper explicitly creates employees, game, joins and starts; it contains no hidden database mutation.

- [ ] **Step 2: Run test RED**

Run: .venv/bin/pytest -q tests/core/test_repository.py::test_never_have_i_ever_statement_responses_and_settlement

Expected: FAIL with missing methods.

- [ ] **Step 3: Implement statement and response recording**

submit_never_have_i_ever_statement validates nonempty trimmed content, locks gate, game, current speaker player and current round state, creates the round with response deadline, clears statement deadline and changes game to awaiting_responses.

respond_never_have_i_ever locks gate, game, round and player. It rejects speaker, nonparticipant, withdrawn or eliminated players and wrong phase. It inserts exactly one response choice. A duplicate unique key returns already_responded without changing the stored choice. Hearts are not changed until settlement.

- [ ] **Step 4: Add invalid-response tests**

Cover non-current speaker statement, empty statement, speaker self-response, eliminated response, nonparticipant, wrong phase, duplicate response and no early disclosure of the stored choice.

- [ ] **Step 5: Implement one-time settlement**

~~~python
def _apply_never_have_i_ever_deduction(player, now, reason):
    player.hearts = max(0, player.hearts - 1)
    if player.hearts == 0:
        player.state = "eliminated"
        player.eliminated_at = now
        player.elimination_reason = reason
~~~

_settle_never_have_i_ever_round_locked creates timeout_deduct rows for active non-speakers without a response, applies one deduction for deduct and timeout_deduct choices, marks the round settled, and calls advance. It returns public data containing the statement, three stable response lists and current hearts.

_advance_never_have_i_ever_locked compares eliminated plus withdrawn players to (initial_player_count + 1) // 2. On threshold it enters free_punishment and clears all deadlines. Otherwise it finds the next active roster order with wraparound, increments round_number, enters awaiting_statement and creates a fresh statement deadline.

- [ ] **Step 6: Implement active-game exit**

Current speaker leaving before statement becomes withdrawn with 0 hearts and advances immediately. During awaiting_responses, a leaving player becomes withdrawn, is removed from expected responders and any existing response is ignored at settlement. If remaining expected responders are all complete, settle immediately. Any exit that reaches threshold enters free_punishment.

- [ ] **Step 7: Implement normal and forced finish helpers**

Host end is valid only in free_punishment. Finish clears active_key and deadlines, stores completed or forced_ended plus reason and time, sorts final ranking by hearts descending then roster order, and records one idempotent never_have_i_ever fact for every player included at start. It never calls balance mutation helpers.

- [ ] **Step 8: Run state tests GREEN**

Run: .venv/bin/pytest -q tests/core/test_repository.py -k "never_have_i_ever and (statement or response or deduct or leave or punishment or end)"

Expected: PASS.

- [ ] **Step 9: Commit**

~~~bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: implement never have i ever rounds"
~~~

### Task 4: 定时任务、边界与恢复

**Files:**
- Modify: src/dzmm_bot/core/repository.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces run_never_have_i_ever_jobs(now) returning an immutable tuple of results with group_chat_id and public_message.
- Consumes Task 3 settlement, advance and finish helpers.

- [ ] **Step 1: Write exact-boundary tests RED**

~~~python
def test_never_have_i_ever_response_timeout_is_idempotent(repository):
    now, deadline = _game_waiting_for_never_have_i_ever_responses(repository)
    assert repository.run_never_have_i_ever_jobs(
        deadline - timedelta(microseconds=1)
    ) == ()
    first = repository.run_never_have_i_ever_jobs(deadline)
    second = repository.run_never_have_i_ever_jobs(deadline + timedelta(seconds=1))
    assert [item.status for item in first] == ["round_settled"]
    assert second == ()
~~~

Add full tests for signup expiration and statement timeout deducting the speaker once.

- [ ] **Step 2: Run timeout tests RED**

Run: .venv/bin/pytest -q tests/core/test_repository.py -k "never_have_i_ever and (timeout or deadline or recovery)"

Expected: FAIL because the job runner is absent.

- [ ] **Step 3: Implement gate-first due-game processing**

run_never_have_i_ever_jobs normalizes Beijing time, acquires gameplay gate before any game/player row, discovers candidate IDs, locks each game, rechecks state and deadline after lock, and performs one of:
- signup at/after deadline: expired and active_key cleared;
- awaiting_statement: deduct current speaker once, then advance;
- awaiting_responses: settle the round once.

Use now >= deadline semantics. Each result carries the exact group ID and fully rendered public text.

- [ ] **Step 4: Integrate with run_daily_jobs**

Call run_never_have_i_ever_jobs while the daily-job transaction owns gameplay gate. Enqueue each public_message with group_chat_destination. Repeated ticks must create no duplicate outbound.

- [ ] **Step 5: Add deterministic race coverage**

Use existing repository transaction barriers where PostgreSQL is available to race final response against timeout. Assert one round settlement, one next round and one deduction set. SQLite tests assert repeated due-job execution is idempotent.

- [ ] **Step 6: Run tests GREEN**

Run: .venv/bin/pytest -q tests/core/test_repository.py -k "never_have_i_ever or daily_jobs"

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: expire never have i ever turns"
~~~

### Task 5: 指令、模板、当前游戏与记忆过滤

**Files:**
- Modify: src/dzmm_bot/core/commands.py
- Modify: src/dzmm_bot/core/reply_templates.py
- Modify: src/dzmm_bot/core/repository.py
- Modify: src/dzmm_bot/core/service.py
- Modify: tests/core/test_group_commands.py
- Modify: tests/core/test_service.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces group handlers for /我有你没有, /发言, /扣, /不扣。
- Extends /加入, /退出, /开始, /结束游戏 and /当前游戏 for game_type never_have_i_ever。
- Produces ActiveGameplaySummary and GameplayAdminSummary projections with hearts and response progress。

- [ ] **Step 1: Write group flow test RED**

~~~python
def test_never_have_i_ever_group_command_flow():
    service, repository, factory = _service()
    now = datetime(2026, 8, 31, 12, 0, tzinfo=BEIJING)
    for platform_id, name in (("host", "主持"), ("u2", "二号"), ("u3", "三号")):
        _receive(service, f"join-{platform_id}", platform_id, f"/入职 {name}", now)
    _receive(service, "create", "host", "/我有你没有", now)
    _receive(service, "game-join-2", "u2", "/加入", now)
    _receive(service, "game-join-3", "u3", "/加入", now)
    _receive(service, "begin", "host", "/开始", now)
    _receive(service, "statement", "host", "/发言 我得过5km第一", now)
    assert "发送 /扣 或 /不扣" in _latest_reply(factory)
    _receive(service, "deduct", "u2", "/扣", now)
    _receive(service, "keep", "u3", "/不扣", now)
    assert "2. 二号：❤️❤️❤️❤️🖤" in _latest_reply(factory)
~~~

- [ ] **Step 2: Run command test RED**

Run: .venv/bin/pytest -q tests/core/test_group_commands.py -k never_have_i_ever

Expected: FAIL because commands are unknown.

- [ ] **Step 3: Register commands and reply scenarios**

Add the four commands to direct command sets. Add explicit reply templates for creation, joining, start, wrong actor, response progress, settlement, statement timeout, response timeout, free punishment, normal end, signup expiration and forced end.

~~~python
TemplateDefinition(
    "/扣",
    "recorded",
    "回应成功",
    "{编号}号 {昵称} 已选择（{已回应人数}/{应回应人数}）。",
    ("{编号}", "{昵称}", "{已回应人数}", "{应回应人数}", "{日期}"),
)
~~~

- [ ] **Step 4: Route generic commands**

For /加入, /退出, /开始 and /结束游戏, inspect active_gameplay_summary in the current group and dispatch to the new repository methods when game_type is never_have_i_ever. The host’s normal /结束游戏 is accepted only in free_punishment; a board member’s /结束游戏 calls the force-end path in any active state; ordinary participants are rejected. Never search another group. Reject all four dedicated commands in private chat.

- [ ] **Step 5: Extend current-game projections**

Expose actor role, own number/hearts, current speaker, response progress and active deadline. Compute available commands by state:
- signup: host gets /开始 and /退出; other members get /退出;
- awaiting_statement: speaker gets /发言 内容 and /退出; other active players get /退出;
- awaiting_responses: eligible responder gets /扣, /不扣 and /退出; other active players get /退出;
- free_punishment: host gets /结束游戏; others get no game action.

- [ ] **Step 6: Add help and AI gameplay guidance**

Add /帮助 游戏 entries for create, join, start, statement, responses and end. Add a knowledge card explaining five hearts and half-player threshold.

Classify all dedicated commands, automatic game messages and ordinary chatter during free_punishment as gameplay-excluded input. Verify only the final fact remains in AI activity data.

- [ ] **Step 7: Run command and service tests GREEN**

Run: .venv/bin/pytest -q tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_repository.py -k never_have_i_ever

Expected: PASS.

- [ ] **Step 8: Commit**

~~~bash
git add src/dzmm_bot/core/commands.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/service.py tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_repository.py
git commit -m "feat: expose never have i ever commands"
~~~

### Task 6: Core 管理 API、当前状态、历史与强制结束

**Files:**
- Modify: src/dzmm_bot/core/api_models.py
- Modify: src/dzmm_bot/core/app.py
- Modify: src/dzmm_bot/core/repository.py
- Modify: tests/core/test_app.py
- Modify: tests/core/test_repository.py

**Interfaces:**
- Produces GET/PATCH /internal/game/never-have-i-ever/settings。
- Produces GET /internal/game/never-have-i-ever/history and GET /internal/game/never-have-i-ever/history/{game_id}。
- Extends GET /internal/gameplay/current and force-end for never_have_i_ever。

- [ ] **Step 1: Write Core API tests RED**

~~~python
def test_never_have_i_ever_settings_api(app_context, headers):
    client, repository = app_context
    response = client.get(
        "/internal/game/never-have-i-ever/settings", headers=headers
    )
    assert response.json()["statement_timeout_seconds"] == 60
    patched = client.patch(
        "/internal/game/never-have-i-ever/settings",
        headers=headers,
        json={
            "enabled": True,
            "signup_timeout_minutes": 12,
            "statement_timeout_seconds": 45,
            "response_timeout_seconds": 75,
        },
    )
    assert patched.status_code == 200
    assert patched.json()["response_timeout_seconds"] == 75
~~~

Add explicit tests for current-game heart fields, history pagination/detail, stale force-end rejection, mismatched group rejection and successful forced end.

- [ ] **Step 2: Run API tests RED**

Run: .venv/bin/pytest -q tests/core/test_app.py -k never_have_i_ever

Expected: FAIL with missing routes and models.

- [ ] **Step 3: Add typed models and endpoints**

~~~python
class NeverHaveIEverSettingsResponse(ApiModel):
    enabled: bool
    signup_timeout_minutes: int
    statement_timeout_seconds: int
    response_timeout_seconds: int


class SetNeverHaveIEverSettingsRequest(ApiModel):
    enabled: bool
    signup_timeout_minutes: int = Field(ge=1)
    statement_timeout_seconds: int = Field(ge=1)
    response_timeout_seconds: int = Field(ge=1)
~~~

History list returns items, total, page, page_size and pages. Detail returns players, rounds and responses in stable order and preserves statement text.

- [ ] **Step 4: Extend admin summary and force end**

Add player hearts, state, current speaker and response progress to GameplaySummaryResponse only when game_type is never_have_i_ever.

Add never_have_i_ever to force_end_gameplay names. Lock gate then exact game; verify group and active key; call finish helper with forced_ended/admin_forced and enqueue the standard forced-end template.

- [ ] **Step 5: Run Core tests GREEN**

Run: .venv/bin/pytest -q tests/core/test_app.py tests/core/test_repository.py -k "never_have_i_ever or force_end_gameplay"

Expected: PASS.

- [ ] **Step 6: Commit**

~~~bash
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/core/repository.py tests/core/test_app.py tests/core/test_repository.py
git commit -m "feat: manage never have i ever games"
~~~

### Task 7: Admin Client、页面与多群开关

**Files:**
- Modify: src/dzmm_bot/admin/core_client.py
- Modify: src/dzmm_bot/admin/app.py
- Modify: src/dzmm_bot/admin/templates/index.html
- Modify: src/dzmm_bot/admin/static/admin.js
- Modify: src/dzmm_bot/admin/static/admin.css
- Modify: tests/admin/test_app.py

**Interfaces:**
- Produces admin proxy routes under /api/game/never-have-i-ever。
- Consumes Task 6 endpoints and existing authenticated admin shell。

- [ ] **Step 1: Write admin contract tests RED**

~~~python
def test_never_have_i_ever_admin_surface():
    html = INDEX_HTML.read_text()
    script = ADMIN_JS.read_text()
    assert 'id="never-have-i-ever-settings-form"' in html
    assert '["never_have_i_ever", "我有你没有"' in script
    assert "/api/game/never-have-i-ever/history" in script
    assert 'data-game-type="never_have_i_ever"' in script
~~~

Add relay tests for settings GET/PATCH, current state through existing gameplay endpoint, history pagination, detail and force end.

- [ ] **Step 2: Run admin tests RED**

Run: .venv/bin/pytest -q tests/admin/test_app.py -k never_have_i_ever

Expected: FAIL because the admin surface is absent.

- [ ] **Step 3: Extend Core client and proxy routes**

Add protocol and concrete methods:
- get_never_have_i_ever_settings
- set_never_have_i_ever_settings
- list_never_have_i_ever_history(page, page_size)
- get_never_have_i_ever_detail(game_id)

Add authenticated relay routes. Validate all timeout inputs as positive integers and page size from 1 to 100.

- [ ] **Step 4: Add settings, current and history UI**

Add a settings form with enabled, signup minutes, statement seconds and response seconds.

Current-game rendering shows group, state, host, round, speaker, deadline, response progress and each player’s escaped name plus hearts. The force-end button sends game_type never_have_i_ever.

History shows pagination and a detail modal containing stable roster, final ranking, each statement and response. Escape all names and statements with escapeHtml. Derive heart glyphs from an integer; never trust stored HTML.

- [ ] **Step 5: Add per-group toggle**

Add ["never_have_i_ever", "我有你没有", "never-have-i-ever"] to the existing group-game option list. Reuse the master game switch behavior and existing update request.

- [ ] **Step 6: Run admin tests GREEN**

Run: .venv/bin/pytest -q tests/admin/test_app.py -k "never_have_i_ever or group_game"

Expected: PASS.

- [ ] **Step 7: Commit**

~~~bash
git add src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/admin/test_app.py
git commit -m "feat: add never have i ever admin UI"
~~~

### Task 8: 全流程验收与回归

**Files:**
- Modify: tests/deploy/test_artifacts.py
- Modify: docs/superpowers/plans/2026-08-31-never-have-i-ever-game.md only to mark completed steps during execution.

**Interfaces:**
- Consumes all prior tasks.
- Produces verified merge-ready code; deployment requires a separate explicit request.

- [ ] **Step 1: Add deployment artifact assertion**

~~~python
def test_never_have_i_ever_deployment_artifacts():
    migration = (
        ROOT / "migrations/versions/20260831_64_never_have_i_ever.py"
    ).read_text()
    assert 'down_revision: str | None = "20260831_63"' in migration
    assert "never_have_i_ever_games" in migration
    assert "never_have_i_ever_responses" in migration
~~~

- [ ] **Step 2: Run focused feature tests**

~~~bash
.venv/bin/pytest -q   tests/deploy/test_never_have_i_ever_migration.py   tests/core/test_group_games.py   tests/core/test_repository.py   tests/core/test_group_commands.py   tests/core/test_service.py   tests/core/test_app.py   tests/admin/test_app.py   -k never_have_i_ever
~~~

Expected: all selected tests PASS.

- [ ] **Step 3: Run adjacent gameplay regressions**

~~~bash
.venv/bin/pytest -q   tests/core/test_repository.py   tests/core/test_group_commands.py   tests/core/test_service.py   tests/core/test_app.py   tests/admin/test_app.py   tests/browser/test_worker.py
~~~

Expected: PASS with only documented skips.

- [ ] **Step 4: Run full verification**

~~~bash
.venv/bin/pytest -q
git diff --check
git status --short
~~~

Expected: zero failures; diff check exits 0; status contains only intended feature changes plus preserved pre-existing dirty files.

- [ ] **Step 5: Review against every spec section**

Confirm evidence for fixed hearts, ceiling threshold, unlimited punishment, host-only normal end, board/admin force end, exact timeout boundaries, multi-group isolation, no balance transactions, history detail and memory filtering.

- [ ] **Step 6: Commit integration assertions**

~~~bash
git add tests/deploy/test_artifacts.py docs/superpowers/plans/2026-08-31-never-have-i-ever-game.md
git commit -m "test: verify never have i ever integration"
~~~
