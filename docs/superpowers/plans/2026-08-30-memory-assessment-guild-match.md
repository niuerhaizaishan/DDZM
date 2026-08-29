# Memory Assessment Guild Match Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, multi-group-safe two-team memory guild match with host-controlled best-of series, private lineup selection, public fastest-correct answering, overtime, admin history, and forced termination.

**Architecture:** Keep the existing single and duel memory-assessment records unchanged. Add focused guild-match tables and a small pure rules module, then expose state transitions through `CoreRepository`; reuse the existing level-5 question generator, duel display duration, outbound recall pipeline, gameplay gate, and duel answer timeout. Route group/direct commands through the existing command/service layers and add read-only/force-end admin APIs plus a history UI.

**Tech Stack:** Python 3.12, SQLAlchemy 2, Alembic, FastAPI/Pydantic, vanilla JavaScript admin UI, pytest.

**Spec:** `docs/superpowers/specs/2026-08-30-memory-assessment-guild-match-design.md`

## Global Constraints

- The feature is group-scoped: one active guild match per group, independent matches across groups.
- Reuse memory level `5`, `duel_recall_seconds`, and `duel_answer_timeout_minutes`; do not add a second rules configuration.
- Hosts are any hired employee, have no daily limit, cannot be rostered, and do not answer.
- No coins, entry fees, rewards, wrong-answer penalties, surrender, or idle/setup timeout.
- Normal series require a previously unused player; overtime permits any roster member.
- Only the first correct answer wins; unanswered deadlines create a draw and do not add a win.
- All planned series must be played even after a team mathematically clinches.
- Existing single-player and duel behavior must remain unchanged.
- All public copy uses the approved separator-and-emoji style.

---

### Task 1: Pure command parsing, validation, ranking, and rendering rules

**Files:**
- Create: `src/dzmm_bot/core/memory_guild_match.py`
- Create: `tests/core/test_memory_guild_match.py`

**Interfaces:**
- Produces: `parse_guild_match_start(content: str) -> int | None`
- Produces: `parse_team_slot_command(command: str) -> tuple[int, str] | None`
- Produces: `parse_series_command(content: str) -> tuple[int, int, int] | None`
- Produces: `split_roster_names(value: str) -> tuple[str, ...]`
- Produces: `render_guild_match_created(...)`, `render_guild_series_ready(...)`, `render_guild_round_result(...)`, and `render_guild_match_finished(...) -> str`

- [ ] **Step 1: Write parser and validation tests**

```python
def test_parse_guild_match_and_series_commands():
    assert parse_guild_match_start("/记忆考核 公会赛 3") == 3
    assert parse_guild_match_start("/记忆考核 公会赛 0") is None
    assert parse_guild_match_start("/记忆考核 公会赛 21") is None
    assert parse_series_command("/第1场 4/7") == (1, 4, 7)
    assert parse_series_command("/第2场 3/5") == (2, 3, 5)
    assert parse_series_command("/第1场 3/7") is None
    assert parse_series_command("/第0场 2/3") is None


def test_split_roster_names_accepts_common_commas_and_rejects_duplicates():
    assert split_roster_names("G，彻, 苏白") == ("G", "彻", "苏白")
    with pytest.raises(ValueError, match="重复"):
        split_roster_names("G，G")
```

- [ ] **Step 2: Run the pure rules tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match.py -q`

Expected: collection fails because `dzmm_bot.core.memory_guild_match` does not exist.

- [ ] **Step 3: Implement the exact parsers and value objects**

```python
@dataclass(frozen=True)
class GuildSeriesRule:
    sequence: int
    win_target: int
    maximum_decisive_rounds: int


def parse_series_command(content: str) -> tuple[int, int, int] | None:
    matched = re.fullmatch(r"/第([1-9]\d*)场\s+([1-9]\d*)/([1-9]\d*)", content.strip())
    if matched is None:
        return None
    sequence, target, total = map(int, matched.groups())
    if total > 99 or total % 2 == 0 or target * 2 != total + 1:
        return None
    return sequence, target, total
```

Implement roster splitting with `[，,、]`, trimmed non-empty names, stable order, and duplicate rejection. Implement message renderers with the exact `━━━━━━━━━━━━━━`, `🏆`, `⚔️`, `🔴`, `🔵`, `🧠`, `📊`, `🎙️`, `🤝`, and `✨` vocabulary from the spec.

- [ ] **Step 4: Add deterministic rendering tests**

```python
def test_render_finished_match_uses_approved_visual_style():
    text = render_guild_match_finished(
        champion_name="女仆公馆队",
        team1_score=2,
        team2_score=1,
        series_lines=("第1场：4 : 2", "第2场：3 : 4", "第3场：4 : 1"),
    )
    assert text.startswith("━━━━━━━━━━━━━━\n🏆 公会赛结束")
    assert "👑 冠军：女仆公馆队" in text
    assert "📊 最终大比分：2 : 1" in text
```

- [ ] **Step 5: Run and commit**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match.py -q`

Expected: all tests pass.

```bash
git add src/dzmm_bot/core/memory_guild_match.py tests/core/test_memory_guild_match.py
git commit -m "feat: add memory guild match rules"
```

---

### Task 2: Persistent guild-match schema and production migration

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`
- Create: `migrations/versions/20260830_62_memory_guild_matches.py`
- Create: `tests/deploy/test_memory_guild_match_migration.py`

**Interfaces:**
- Produces ORM records: `MemoryGuildMatchRecord`, `MemoryGuildTeamRecord`, `MemoryGuildMemberRecord`, `MemoryGuildSeriesRecord`, `MemoryGuildRoundRecord`, `MemoryGuildAnswerRecord`
- Associates a recalled outbound through `MemoryGuildRoundRecord.outbound_message_id`; do not add a guild-match column to `OutboundRecord`.

- [ ] **Step 1: Write a migration test from revision 61 to head**

```python
def test_upgrade_61_to_head_creates_memory_guild_tables(migrated_database):
    inspector = sa.inspect(migrated_database)
    assert {
        "memory_guild_matches",
        "memory_guild_teams",
        "memory_guild_members",
        "memory_guild_series",
        "memory_guild_rounds",
        "memory_guild_answers",
    } <= set(inspector.get_table_names())
    assert "ux_memory_guild_one_active_per_group" in {
        index["name"] for index in inspector.get_indexes("memory_guild_matches")
    }
```

- [ ] **Step 2: Run the migration test and verify failure**

Run: `.venv/bin/pytest tests/deploy/test_memory_guild_match_migration.py -q`

Expected: FAIL because revision 62 and the six tables do not exist.

- [ ] **Step 3: Add schema records with explicit constraints**

```python
class MemoryGuildMatchRecord(Base):
    __tablename__ = "memory_guild_matches"
    __table_args__ = (
        CheckConstraint("planned_series_count BETWEEN 1 AND 20"),
        Index(
            "ux_memory_guild_one_active_per_group",
            "group_chat_id",
            unique=True,
            sqlite_where=text("active_key IS NOT NULL"),
            postgresql_where=text("active_key IS NOT NULL"),
        ),
    )
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    group_chat_id: Mapped[UUID] = mapped_column(ForeignKey("group_chats.id"), nullable=False)
    host_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    active_key: Mapped[str | None] = mapped_column(String(32))
    planned_series_count: Mapped[int] = mapped_column(Integer, nullable=False)
    current_series_number: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    champion_team_id: Mapped[UUID | None] = mapped_column(Uuid)
    finish_reason: Mapped[str | None] = mapped_column(String(64))
    forced_by_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(BeijingDateTime, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(BeijingDateTime)
```

Use these exact relational constraints:

- `memory_guild_teams`: unique `(match_id, slot)` and unique `(match_id, name)`.
- `memory_guild_members`: include both `match_id` and `team_id`; unique `(match_id, user_id)` and unique `(team_id, roster_order)`.
- `memory_guild_series`: unique `(match_id, sequence)`; player references point to member rows from the same match and are validated transactionally.
- `memory_guild_rounds`: unique `(series_id, sequence)` and unique nullable `outbound_message_id`.
- `memory_guild_answers`: primary UUID plus a unique `platform_message_id` string so replayed platform messages cannot create duplicate attempts.

Store member display-name snapshots and team-name snapshots for stable history. `MemoryGuildRoundRecord` stores answer, display seconds, state, answer deadline, outbound message ID, winning user, result, and timestamps. `MemoryGuildAnswerRecord` stores every submitted text, correctness, user, and timestamp.

- [ ] **Step 4: Create revision 62 without rewriting revision 61**

Set `revision = "20260830_62"` and `down_revision = "20260827_61"`. Create all foreign keys, checks, partial unique index, and lookup indexes. The downgrade drops the six tables in reverse dependency order.

- [ ] **Step 5: Run migration and metadata tests**

Run: `.venv/bin/pytest tests/deploy/test_memory_guild_match_migration.py tests/deploy/test_artifacts.py -q`

Expected: all tests pass, and upgrading an already-stamped revision-61 database reaches revision 62.

- [ ] **Step 6: Commit**

```bash
git add src/dzmm_bot/core/schema.py migrations/versions/20260830_62_memory_guild_matches.py tests/deploy/test_memory_guild_match_migration.py
git commit -m "feat: persist memory guild matches"
```

---

### Task 3: Match creation, team configuration, gameplay locking, and summaries

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/group_games.py`
- Create: `tests/core/test_memory_guild_match_repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Produces immutable views: `MemoryGuildMatchResult`, `MemoryGuildMatchView`, `MemoryGuildTeamView`, `MemoryGuildMemberView`
- Produces `start_memory_guild_match(platform_id: str, planned_series_count: int, now: datetime, group_chat_id: UUID) -> MemoryGuildMatchResult`
- Produces `set_memory_guild_team_name(...) -> MemoryGuildMatchResult`
- Produces `set_memory_guild_roster(...) -> MemoryGuildMatchResult`
- Extends `active_gameplay_summary`, `_group_has_active_group_game`, `user_has_active_game_context`, `current_gameplay_admin_summary`, and `force_end_gameplay` with `memory_guild`.

- [ ] **Step 1: Write creation and configuration failures first**

```python
def test_host_creates_and_overwrites_two_teams(repository, hired_users, now):
    created = repository.start_memory_guild_match("host", 3, now, PRIMARY_GROUP_CHAT_ID)
    assert created.status == "created"
    assert repository.set_memory_guild_team_name("host", 1, "女仆公馆队", now).status == "team_updated"
    assert repository.set_memory_guild_team_name("host", 1, "新女仆公馆队", now).team1.name == "新女仆公馆队"


def test_roster_rejects_host_cross_team_duplicate_and_unknown_user(...):
    assert set_roster(("host",)).status == "host_cannot_play"
    assert set_second_roster(("G",)).status == "member_in_other_team"
    assert set_roster(("不存在",)).status == "unknown_member"
```

Also test disabled group type, performance block, random event conflict, every existing multiplayer conflict, same-group one-active behavior, and parallel creation in two groups.

- [ ] **Step 2: Run repository tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match_repository.py -q`

Expected: FAIL because repository interfaces are absent.

- [ ] **Step 3: Implement gate-first creation and team replacement**

```python
def start_memory_guild_match(self, platform_id, planned_series_count, now, group_chat_id):
    with self.transaction():
        with self._session() as session:
            self._lock_gameplay_gate(session)
            host = session.scalar(select(UserRecord).where(UserRecord.platform_id == platform_id).with_for_update())
            # validate hired user, group setting, performance/random-event/game conflicts
            match = MemoryGuildMatchRecord(
                group_chat_id=group_chat_id,
                host_user_id=host.id,
                state="configuring",
                active_key="global",
                planned_series_count=planned_series_count,
                created_at=now,
            )
            session.add(match)
            return MemoryGuildMatchResult("created", match_id=match.id)
```

Resolve roster names against the existing unique employee name rule, lock all involved users in UUID order, delete/replace only the selected team's member rows, and reject host/cross-team duplicates before mutation. Do not call `_claim_rank_multiplayer_start`; guild matches have no daily limit.

- [ ] **Step 4: Integrate active-game summaries and force ending**

Add `memory_guild` to game labels and the gameplay/admin summary. Host role exposes `/结束游戏`; team members expose no exit/surrender; board force-end routes to `_finish_memory_guild_match_locked(..., reason="board_forced")`. Background/admin force end uses `reason="admin_forced"`. Both clear `active_key`, preserve settled history, set no champion, and enqueue the approved forced-end notification.

- [ ] **Step 5: Run gameplay-lock regression tests**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match_repository.py tests/core/test_repository.py -q -k 'memory_guild or active_gameplay or force_end or group_game'`

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/group_games.py tests/core/test_memory_guild_match_repository.py tests/core/test_repository.py
git commit -m "feat: configure memory guild matches"
```

---

### Task 4: Series creation and private lineup selection

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_memory_guild_match_repository.py`

**Interfaces:**
- Produces `create_memory_guild_series(host_platform_id: str, sequence: int, win_target: int, maximum_decisive_rounds: int, now: datetime, group_chat_id: UUID) -> MemoryGuildMatchResult`
- Produces `memory_guild_lineup_candidates(platform_id: str) -> tuple[PrivateGameCandidate, ...]`
- Produces `select_memory_guild_player(actor_platform_id: str, selected_name: str, now: datetime, group_chat_id: UUID | None = None) -> MemoryGuildMatchResult`

- [ ] **Step 1: Write sequential-series and roster-size tests**

```python
def test_first_series_requires_complete_locked_rosters(repository, configured_match, now):
    result = repository.create_memory_guild_series("host", 1, 4, 7, now, PRIMARY_GROUP_CHAT_ID)
    assert result.status == "insufficient_roster"


def test_series_numbers_are_sequential_and_previous_must_be_settled(...):
    assert create_series(sequence=2).status == "invalid_sequence"
    create_series(sequence=1)
    assert create_series(sequence=2).status == "previous_series_active"
```

- [ ] **Step 2: Write private lineup and overtime tests**

```python
def test_first_valid_team_selection_locks_and_public_pairing_waits_for_both(...):
    first = repository.select_memory_guild_player("team1-member", "G", now, group_id)
    assert first.status == "lineup_recorded"
    assert first.public_message is None
    duplicate = repository.select_memory_guild_player("other-team1-member", "彻", now, group_id)
    assert duplicate.status == "lineup_locked"
    second = repository.select_memory_guild_player("team2-member", "玩家A", now, group_id)
    assert second.status == "series_ready"
    assert "G" in second.public_message and "玩家A" in second.public_message


def test_regular_series_rejects_used_player_but_overtime_allows_it(...):
    assert regular_reuse.status == "player_already_used"
    assert overtime_reuse.status == "series_ready"
```

- [ ] **Step 3: Implement creation and selection under one lock order**

Every mutating entry acquires gameplay gate, then match, series, teams/members, and users in stable order. On first series creation, verify both team names exist, both rosters have at least `planned_series_count` members, and freeze configuration. A series with `sequence <= planned_series_count` is regular; a later series is accepted only when planned series are settled and team scores are tied.

- [ ] **Step 4: Implement multi-group direct candidates**

Return only matches where the actor belongs to a team and the current series is waiting for that team's selection. With one candidate, `/上场 名称` resolves directly; with multiple candidates, require `/上场 群序号 名称` and reject stale indices by recomputing the candidate list.

- [ ] **Step 5: Run and commit**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match_repository.py -q -k 'series or lineup or overtime'`

Expected: all selected tests pass.

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_memory_guild_match_repository.py
git commit -m "feat: add guild match lineups"
```

---

### Task 5: Question recall, public answering, draw timeout, and settlement

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `tests/core/test_memory_guild_match_repository.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/browser/test_worker.py`

**Interfaces:**
- Extends `CommandReply` with `memory_guild_round_id: UUID | None = None`
- Produces `start_memory_guild_round(host_platform_id: str, now: datetime, group_chat_id: UUID) -> MemoryGuildMatchResult`
- Produces `answer_memory_guild_round(platform_id: str, platform_message_id: str, answer: str, now: datetime, group_chat_id: UUID) -> MemoryGuildMatchResult`
- Produces `run_memory_guild_jobs(now: datetime) -> tuple[MemoryGuildMatchResult, ...]`
- Extends `enqueue_outbound`/`enqueue_system_outbound` and `confirm_outbound_recalled` to associate and open a `MemoryGuildRoundRecord`.

- [ ] **Step 1: Write start/recall lifecycle tests**

```python
def test_only_host_starts_level_five_round_and_recall_opens_answering(...):
    denied = repository.start_memory_guild_round("player", now, group_id)
    assert denied.status == "host_only"
    started = repository.start_memory_guild_round("host", now, group_id)
    assert started.level == 5
    assert started.display_seconds == settings.duel_recall_seconds
    outbound = repository.enqueue_system_outbound(
        started.public_message,
        recall_after_seconds=started.display_seconds,
        memory_guild_round_id=started.round_id,
        group_chat_id=group_id,
        destination_chatroom_id=chatroom_id,
    )
    confirm_recalled(outbound)
    assert repository.memory_guild_round(started.round_id).state == "answering"
```

- [ ] **Step 2: Write first-correct, retry, outsider, and draw tests**

```python
def test_wrong_answers_retry_and_first_correct_wins_atomically(...):
    assert answer("spectator", canonical).status == "not_current_player"
    assert answer("red", "错").status == "incorrect"
    assert answer("red", canonical).status == "round_won"
    assert answer("blue", canonical).status == "round_closed"


def test_deadline_without_correct_answer_records_draw(...):
    results = repository.run_memory_guild_jobs(answer_deadline)
    assert results[0].status == "round_drawn"
    assert results[0].series.team1_wins == 0
    assert results[0].series.team2_wins == 0
```

Add a PostgreSQL concurrency test where both correct submissions race and assert exactly one `correct=True` winning transition and one team win increment.

- [ ] **Step 3: Implement round generation and outbound association**

Fetch level 5 from `MemoryAssessmentLevelRuleRecord`; generate with `_memory_assessment_answer(settings.character_set, rule.answer_length)`. Create a `showing` round and return a `CommandReply` whose recall metadata points to that guild round. Extend outbound enqueue code so exactly one outbound can populate `MemoryGuildRoundRecord.outbound_message_id` while preserving the existing memory-assessment path.

- [ ] **Step 4: Open answer window only after successful recall**

In `confirm_outbound_recalled`, after locking the outbound, check both `MemoryAssessmentRoundRecord` and `MemoryGuildRoundRecord`. For a guild round in `showing`, set `state="answering"`, set `answer_deadline = now + timedelta(minutes=settings.duel_answer_timeout_minutes)`, and update match/series states atomically. A send or recall failure must leave the round non-answerable.

- [ ] **Step 5: Implement answer and settlement transitions**

Lock gate → match → series → round before inserting an attempt. Wrong attempts remain auditable and return `incorrect`. First correct sets round winner, increments the selected player's team score, and either returns to `waiting_round_start`, settles the series, waits for the next planned series, waits for overtime, or finishes the match. Record only final participation facts in AI memory; never record answer text or game commands.

- [ ] **Step 6: Add timeout processing to daily jobs**

`run_memory_guild_jobs` selects `answering` rounds with `answer_deadline <= now` using `FOR UPDATE SKIP LOCKED`, marks them `drawn`, and enqueues the approved `🤝` draw message to the bound group. Call it from `run_daily_jobs` after obtaining the gameplay gate in the same global lock order used by other game jobs.

- [ ] **Step 7: Run lifecycle and worker regressions**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match_repository.py tests/core/test_repository.py tests/browser/test_worker.py -q -k 'memory_guild or recall or daily_jobs'`

Expected: all selected tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/dzmm_bot/core/repository.py src/dzmm_bot/core/schema.py src/dzmm_bot/core/service.py tests/core/test_memory_guild_match_repository.py tests/core/test_repository.py tests/browser/test_worker.py
git commit -m "feat: run memory guild match rounds"
```

---

### Task 6: Group/direct command routing, templates, help, and AI guidance

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/service.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_service.py`

**Interfaces:**
- Routes public commands `/记忆考核 公会赛 N`, `/队伍1`, `/队伍2`, `/队伍1人员`, `/队伍2人员`, `/第N场 W/T`, `/开始对战`, `/答案`, `/结束游戏`
- Routes direct `/上场 玩家名称` and `/上场 群序号 玩家名称`

- [ ] **Step 1: Write an end-to-end command-flow test**

```python
def test_memory_guild_command_flow(factory, repository):
    send_group("host", "/记忆考核 公会赛 3")
    send_group("host", "/队伍1 女仆公馆队")
    send_group("host", "/队伍1人员 G，彻，苏白")
    send_group("host", "/队伍2 摸鱼事务所队")
    send_group("host", "/队伍2人员 A，B，C")
    send_group("host", "/第1场 4/7")
    send_direct("G", "/上场 G")
    send_direct("A", "/上场 A")
    reply = send_group("host", "/开始对战")
    assert reply.recall_after_seconds == settings.duel_recall_seconds
    assert reply.memory_guild_round_id is not None
```

- [ ] **Step 2: Run command tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_group_commands.py tests/core/test_service.py -q -k memory_guild`

Expected: FAIL because new commands are not routed.

- [ ] **Step 3: Add explicit and dynamic command normalization**

Add fixed commands `/队伍1`, `/队伍2`, `/队伍1人员`, `/队伍2人员`, `/开始对战`, `/上场`. Before `_COMMANDS` rejection, recognize `re.fullmatch(r"/第[1-9]\d*场", command)` and normalize it to the internal command definition `/公会赛场次` while retaining the original content for parsing. Add `/上场` to `_DIRECT_COMMANDS`; reject it in group chats with a private-only reply.

- [ ] **Step 4: Route host/team/answer/end permissions**

Use repository statuses to produce exact setup errors, multi-group candidate lists, locked-lineup messages, and the approved public pairing/result layouts. `/答案` first checks an active guild round in the current group; otherwise preserve existing single/duel behavior. `/结束游戏` lets the host end `memory_guild`; the existing board path keeps working through `force_end_gameplay`.

- [ ] **Step 5: Register templates and help text**

Add editable reply scenarios for created/configured/series-ready/round-started/incorrect/drawn/round-won/series-won/overtime/finished/forced errors. Update `/帮助 记忆考核` and AI knowledge to explain the new exact commands without changing normal memory extraction prompts.

- [ ] **Step 6: Verify command gating and memory exclusion**

Test disabled per-group memory game switch, performance blocking, dynamic `/第N场` command enablement, direct routing, non-host failures, board force end, and that `/答案` plus configuration commands are not stored as player conversational evidence.

- [ ] **Step 7: Run and commit**

Run: `.venv/bin/pytest tests/core/test_group_commands.py tests/core/test_service.py -q -k 'memory or guild'`

Expected: all selected tests pass and existing single/duel command tests remain green.

```bash
git add src/dzmm_bot/core/commands.py src/dzmm_bot/core/service.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/core/ai_knowledge.py src/dzmm_bot/core/repository.py tests/core/test_group_commands.py tests/core/test_service.py
git commit -m "feat: expose memory guild match commands"
```

---

### Task 7: Core/admin APIs, current state, force end, and paginated history UI

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`
- Modify: `tests/admin/test_core_client.py`

**Interfaces:**
- Produces `GET /internal/game/memory-assessment/guild/current`
- Produces `GET /internal/game/memory-assessment/guild/history?page=1&page_size=20`
- Produces `GET /internal/game/memory-assessment/guild/history/{match_id}`
- Uses existing forced-game endpoint with `game_type="memory_guild"`
- Admin proxies the same resources under `/api/memory-assessment/guild/...`

- [ ] **Step 1: Write API contract tests**

```python
def test_guild_history_is_paginated_and_detail_contains_rounds(client, headers, seeded_match):
    page = client.get("/internal/game/memory-assessment/guild/history?page=1&page_size=20", headers=headers)
    assert page.status_code == 200
    assert page.json()["total"] == 1
    detail = client.get(f"/internal/game/memory-assessment/guild/history/{seeded_match.id}", headers=headers)
    assert detail.json()["teams"][0]["name"] == "女仆公馆队"
    assert detail.json()["series"][0]["rounds"][0]["result"] in {"won", "drawn"}
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `.venv/bin/pytest tests/core/test_app.py tests/admin/test_app.py tests/admin/test_core_client.py -q -k memory_guild`

Expected: FAIL with 404 or missing client methods.

- [ ] **Step 3: Add typed Pydantic responses and repository readers**

Define summary/page/detail models with exact UUIDs, names, snapshots, states, scores, timestamps, winner IDs, forced-end metadata, series, rounds, and answer attempts. Keep the list endpoint compact; load nested rounds/answers only in detail. Bound page size to `1..100` and return 404 for unknown match IDs.

- [ ] **Step 4: Add Core and admin proxy routes**

Follow the existing authenticated Core and admin proxy patterns. Extend `CoreClient` protocol and HTTP implementation with `get_memory_guild_current`, `list_memory_guild_history`, and `get_memory_guild_detail`.

- [ ] **Step 5: Add current state and history panes**

In the existing “记忆考核” admin view, add tabs/cards for:

- Current guild match: group, host, state, two rosters, current pairing, small-round score, big score, and a force-end button.
- Guild history: paginated rows with time, group, teams, final score, champion/forced status; clicking opens complete series and round details.

Render server-provided text with `textContent`/escaping, never raw user-controlled HTML. Preserve the existing single/duel settings layout.

- [ ] **Step 6: Add UI contract tests**

Assert the page contains the guild current/history controls, endpoints are invoked with page parameters, force-end sends `memory_guild` and group ID, and detail renders `🏆`, team scores, pairings, draws, and forced-end reason.

- [ ] **Step 7: Run and commit**

Run: `.venv/bin/pytest tests/core/test_app.py tests/admin/test_app.py tests/admin/test_core_client.py -q -k 'memory_guild or memory_assessment'`

Expected: all selected tests pass.

```bash
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/core/test_app.py tests/admin/test_app.py tests/admin/test_core_client.py
git commit -m "feat: manage memory guild match history"
```

---

### Task 8: Recovery, multi-group integration, documentation, and full verification

**Files:**
- Modify: `rule.md`
- Modify: `tests/core/test_memory_guild_match_repository.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/deploy/test_artifacts.py`

**Interfaces:**
- Consumes all interfaces from Tasks 1–7.
- Produces a release-ready feature with migration, regression coverage, and player/admin documentation.

- [ ] **Step 1: Add restart and idempotency tests**

```python
def test_restart_preserves_showing_and_answering_deadlines(...):
    started = start_round()
    reopened_repository = repository_from_same_database()
    assert reopened_repository.current_memory_guild_match(group_id).round_id == started.round_id
    assert reopened_repository.run_memory_guild_jobs(before_deadline) == ()
    assert reopened_repository.run_memory_guild_jobs(at_deadline)[0].status == "round_drawn"
```

Also replay duplicate inbound IDs, duplicate lineup selection, duplicate correct answers, duplicate timeout jobs, and duplicate force-end requests; assert no duplicate score increment or public settlement.

- [ ] **Step 2: Add two-group and conflict matrix tests**

Start guild matches in A and B, independently configure/start/answer them, and prove messages, candidates, deadlines, history, and force-end operations remain group-scoped. In one group, assert mutual exclusion against random event, number bomb, blame, undercover, Texas Hold'em, existing duel, and performance.

- [ ] **Step 3: Add the finalized rules to `rule.md`**

Document the player flow and exact commands from the approved spec, including no coin flow, all planned series, private lineup selection, normal-player reuse restriction, overtime exception, no surrender, no idle timeout, and administrative force end.

- [ ] **Step 4: Run formatting/static checks**

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 5: Run focused feature tests**

Run: `.venv/bin/pytest tests/core/test_memory_guild_match.py tests/core/test_memory_guild_match_repository.py tests/core/test_group_commands.py tests/core/test_service.py tests/core/test_app.py tests/admin/test_app.py tests/admin/test_core_client.py tests/browser/test_worker.py tests/deploy/test_memory_guild_match_migration.py -q`

Expected: all focused tests pass.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`

Expected: full suite passes with only the repository's documented skips.

- [ ] **Step 7: Verify production migration path without deployment**

Run the repository's migration check from revision 61 to head against a temporary database, then confirm `alembic heads` reports only `20260830_62`. Do not deploy; the user requested implementation first and deployment only after later confirmation.

- [ ] **Step 8: Commit final integration**

```bash
git add rule.md tests/core/test_memory_guild_match_repository.py tests/core/test_group_commands.py tests/deploy/test_artifacts.py
git commit -m "test: verify memory guild match flow"
```
