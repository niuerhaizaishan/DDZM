# 德州扑克单局现金桌 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 DZMM 群聊游戏系统中交付可重启恢复、真实摸鱼币守恒、支持标准无限注与边池的单局德州扑克。

**Architecture:** 使用独立持久化牌局状态机；纯牌型、下注和底池算法放在独立领域模块，数据库仓储负责事务、幂等、余额和截止时间，命令层只做路由与模板渲染。底牌通过现有 Outbound 发件箱和私聊映射投递，管理端只消费公开牌局摘要。

**Tech Stack:** Python 3.12、SQLAlchemy 2、Alembic、FastAPI/Pydantic、vanilla JavaScript/HTML、pytest。

## Global Constraints

- 玩法为单局现金桌，命令 `/德州扑克 带入金额`；默认 2–9 人、带入 20–200、报名与行动限时均为 120 秒。
- 系统只发牌、裁判和结算，不参赌、不抽成；所有正常和作废结算必须严格守恒。
- 小盲为带入 5% 且最低 1，大盲为 10% 且最低 2，均向上取整。
- 牌面显示 `♠️1`、`♥️J`；显示 `1` 的 A 在牌型引擎中仍严格按标准德州扑克处理。
- 翻牌、转牌、河牌前各烧一张；牌堆、底牌和截止时间必须持久化，重启不得重洗或重新计时。
- 底牌只允许进入对应玩家私聊，不得进入后台、普通日志、AI 上下文或群消息。
- 发起人没有结束特权；开局后普通 `/退出` 等同弃牌，仅核心董事会或后台可作废整局。
- 开发必须测试驱动，每个任务只提交本任务相关文件，不提交现有 `.env`、`.DS_Store` 或无关未跟踪文件。

## File Structure

- Create `src/dzmm_bot/core/texas_holdem.py`: 牌、洗牌布局、牌型比较、纯下注轮和边池算法。
- Modify `src/dzmm_bot/core/schema.py`: 德州扑克设置、牌局、玩家、动作、底池和每日发起 ORM。
- Create `migrations/versions/20260817_45_texas_holdem.py`: 新表、约束、默认配置和索引。
- Modify `src/dzmm_bot/core/repository.py`: 事务化生命周期、私聊投递确认、超时、结算、摘要和互斥。
- Modify `src/dzmm_bot/core/commands.py`: 新命令和通用游戏路由。
- Modify `src/dzmm_bot/core/reply_templates.py`: 默认可编辑回复模板。
- Modify `src/dzmm_bot/core/ai_knowledge.py`: 德州扑克玩法知识与精确指令映射。
- Modify `src/dzmm_bot/core/api_models.py`, `src/dzmm_bot/core/app.py`: 设置与公开牌局状态 API。
- Modify `src/dzmm_bot/admin/core_client.py`, `src/dzmm_bot/admin/app.py`: 管理端中转 API。
- Modify `src/dzmm_bot/admin/templates/index.html`, `src/dzmm_bot/admin/static/admin.js`: 德州扑克配置和公开状态界面。
- Create `tests/core/test_texas_holdem.py`: 纯领域算法测试。
- Modify `tests/core/test_repository.py`, `tests/core/test_group_commands.py`: 生命周期、经济、超时与命令集成。
- Modify `tests/core/test_app.py`, `tests/admin/test_app.py`, `tests/browser/test_core_client.py`: API 与管理端合同。
- Create `tests/deploy/test_texas_holdem_migration.py`: SQLite/PostgreSQL 迁移结构合同。

---

### Task 1: 纯德州扑克领域引擎

**Files:**
- Create: `src/dzmm_bot/core/texas_holdem.py`
- Create: `tests/core/test_texas_holdem.py`

**Interfaces:**
- Produces: `Card`, `DealLayout`, `HandRank`, `Pot`, `BettingPlayer`, `BettingRound`, `BettingActionResult` dataclasses.
- Produces: `format_card(card: Card) -> str`, `deal_layout(deck: Sequence[Card], player_count: int) -> DealLayout`, `evaluate_best(cards: Sequence[Card]) -> HandRank`, `build_side_pots(contributions: Mapping[int, int], folded_seats: set[int]) -> tuple[Pot, ...]`, `apply_betting_action(round_state: BettingRound, seat: int, action: str, amount: int | None = None) -> BettingActionResult`.

- [ ] **Step 1: Write failing card, dealing, hand-rank and side-pot tests**

```python
def test_display_ace_as_one_but_rank_wheel_below_six_high():
    wheel = evaluate_best(cards("SA H2 C3 D4 S5 H9 CK"))
    six_high = evaluate_best(cards("S2 H3 C4 D5 S6 H9 CK"))
    assert format_card(Card("spades", 14)) == "♠️1"
    assert wheel.category_name == "顺子"
    assert six_high > wheel

def test_deal_layout_burns_before_each_board_street():
    layout = deal_layout(tuple(build_deck()), player_count=2)
    assert len(layout.hole_cards) == 2
    assert len(layout.burn_cards) == 3
    assert len(layout.board) == 5
    assert len(set(layout.all_dealt_cards)) == 12

def test_side_pots_exclude_folded_players_but_keep_their_money():
    pots = build_side_pots({1: 100, 2: 60, 3: 20}, folded_seats={2})
    assert [(pot.amount, pot.eligible_seats) for pot in pots] == [
        (60, (1, 3)), (80, (1,)), (40, (1,))
    ]
```

- [ ] **Step 2: Run the new unit file and verify import failures**

Run: `pytest -q tests/core/test_texas_holdem.py`
Expected: FAIL because `dzmm_bot.core.texas_holdem` does not exist.

- [ ] **Step 3: Implement cards, standard evaluator, burn layout and side pots**

Use internal rank values `2..14`, immutable dataclasses and tuple tiebreaks ordered from most significant to least. `HandRank.__lt__` compares `(category, tiebreak)`; category values are high card 0 through straight flush 8. `deal_layout` deals one card per seat per pass, then burn/flop, burn/turn, burn/river.

- [ ] **Step 4: Add failing betting-round tests**

```python
def test_short_all_in_raises_call_amount_without_reopening_raise_rights():
    state = betting_round(stacks={1: 80, 2: 25, 3: 80}, current_bet=20, last_raise=20)
    state = apply_betting_action(state, 1, "call").state
    state = apply_betting_action(state, 2, "all_in").state
    assert state.current_bet == 25
    assert 1 not in state.raise_open_seats
    assert state.to_call(1) == 5

def test_heads_up_preflop_and_postflop_order_helpers():
    assert preflop_first_seat((1, 2), button_seat=1) == 1
    assert postflop_first_seat((1, 2), button_seat=1) == 2
```

- [ ] **Step 5: Implement legal check/call/raise/all-in/fold transitions**

Return a new immutable `BettingRound`; reject illegal actions with `TexasHoldemRuleError(code)`. Track `current_bet`, `last_full_raise`, `acted_seats`, `raise_open_seats`, per-seat `street_bet`, stack, folded and all-in state. A round is complete only when all actionable players acted and matched `current_bet`.

- [ ] **Step 6: Run domain tests and commit**

Run: `pytest -q tests/core/test_texas_holdem.py`
Expected: PASS.

```bash
git add src/dzmm_bot/core/texas_holdem.py tests/core/test_texas_holdem.py
git commit -m "feat: add texas holdem domain engine"
```

---

### Task 2: 持久化模型和迁移

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`
- Create: `migrations/versions/20260817_45_texas_holdem.py`
- Create: `tests/deploy/test_texas_holdem_migration.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Produces ORM classes: `TexasHoldemSettingsRecord`, `TexasHoldemGameRecord`, `TexasHoldemPlayerRecord`, `TexasHoldemActionRecord`, `TexasHoldemPotRecord`, `TexasHoldemDailyStartRecord`.
- `TexasHoldemGameRecord` stores `deck`, `board`, state/street, active key, button/current seat, blind snapshots, current bet/full-raise snapshots, deadlines and settlement flags.
- `TexasHoldemPlayerRecord` stores seat, hole cards, original buy-in, stack, street/total contribution, state, action-right flags and private outbound ID/state.

- [ ] **Step 1: Write failing metadata and migration tests**

```python
def test_texas_holdem_tables_and_active_index_exist(upgraded_connection):
    tables = inspect(upgraded_connection).get_table_names()
    assert {"texas_holdem_settings", "texas_holdem_games", "texas_holdem_players",
            "texas_holdem_actions", "texas_holdem_pots", "texas_holdem_daily_starts"} <= set(tables)
    indexes = inspect(upgraded_connection).get_indexes("texas_holdem_games")
    assert any(index["name"] == "ux_texas_holdem_one_active" and index["unique"] for index in indexes)
```

- [ ] **Step 2: Run migration test and verify it fails**

Run: `pytest -q tests/deploy/test_texas_holdem_migration.py`
Expected: FAIL because revision `20260817_45` and tables do not exist.

- [ ] **Step 3: Add ORM classes and Alembic revision**

Set `revision = "20260817_45"`, `down_revision = "20260817_44"`. Add defaults: enabled true, min/max players 2/9, min/max buy-in 20/200, daily start limit 1, signup/action timeout 120, small/big blind percent 5/10. Add unique constraints on `(game_id, seat_number)`, `(game_id, user_id)`, action `inbound_message_id`, and `(user_id, play_date)`.

- [ ] **Step 4: Run migration and schema tests, then commit**

Run: `pytest -q tests/deploy/test_texas_holdem_migration.py tests/core/test_repository.py -k 'texas_holdem or schema'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/schema.py migrations/versions/20260817_45_texas_holdem.py tests/deploy/test_texas_holdem_migration.py tests/core/test_repository.py
git commit -m "feat: persist texas holdem games"
```

---

### Task 3: 报名、开局与私聊发牌

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Produces dataclasses: `TexasHoldemSettings`, `TexasHoldemPlayerView`, `TexasHoldemResult`, `TexasHoldemSummary`.
- Produces repository methods: `get_texas_holdem_settings() -> TexasHoldemSettings`, `set_texas_holdem_settings(enabled: bool, minimum_players: int, maximum_players: int, minimum_buy_in: int, maximum_buy_in: int, daily_start_limit: int, signup_timeout_seconds: int, action_timeout_seconds: int, small_blind_percent: int, big_blind_percent: int) -> TexasHoldemSettings`, `start_texas_holdem_signup(platform_id: str, buy_in: int, now: datetime) -> TexasHoldemResult`, `join_texas_holdem(platform_id: str, now: datetime) -> TexasHoldemResult`, `leave_texas_holdem(platform_id: str, now: datetime) -> TexasHoldemResult`, `start_texas_holdem_hand(platform_id: str, now: datetime) -> TexasHoldemResult`, `texas_holdem_summary(now: datetime) -> TexasHoldemSummary`.
- Extends outbound completion for `delivery_kind == "texas_holdem_card"`.

- [ ] **Step 1: Write failing signup and refund tests**

```python
def test_texas_holdem_signup_debits_equal_buy_in_and_exit_refunds(repository, now):
    add_user_with_direct_chat(repository, "p1", "甲", 100, now)
    result = repository.start_texas_holdem_signup("p1", 20, now)
    assert result.status == "created"
    assert repository.find_user("p1").balance == 80
    assert repository.leave_texas_holdem("p1", now).status == "signup_left"
    assert repository.find_user("p1").balance == 100

def test_daily_limit_counts_only_after_start(repository, now):
    for platform_id, name in (("p1", "甲"), ("p2", "乙")):
        add_user_with_direct_chat(repository, platform_id, name, 100, now)
    first = repository.start_texas_holdem_signup("p1", 20, now)
    assert repository.leave_texas_holdem("p1", now).status == "signup_left"
    second = repository.start_texas_holdem_signup("p1", 20, now)
    assert repository.join_texas_holdem("p2", now).status == "joined"
    assert repository.start_texas_holdem_hand("p2", now).status == "dealing"
    confirm_private_outbounds_and_settle_by_fold(repository, second.game_id, now)
    assert repository.start_texas_holdem_signup("p1", 20, now).status == "daily_limit"
```

- [ ] **Step 2: Run focused repository tests and verify failures**

Run: `pytest -q tests/core/test_repository.py -k texas_holdem`
Expected: FAIL because repository methods do not exist.

- [ ] **Step 3: Implement settings, signup, join, leave and atomic buy-in/refund**

Use the existing transaction context and `_apply_balance_change`. Add balance source labels `texas_holdem_buy_in`, `texas_holdem_refund`, `texas_holdem_settlement`, `texas_holdem_abort_refund`. Validate active gameplay conflict, direct chat, limits, integer buy-in and capacity before debit.

- [ ] **Step 4: Write failing dealing and delivery-ack tests**

```python
def test_hand_waits_for_every_private_card_delivery(repository, now):
    game = prepared_two_player_signup(repository, now)
    started = repository.start_texas_holdem_hand("p2", now)
    assert started.status == "dealing"
    first, second = started.card_outbound_ids
    confirm(repository, first, now)
    assert repository.texas_holdem_summary(now).state == "dealing"
    confirm(repository, second, now)
    summary = repository.texas_holdem_summary(now)
    assert summary.state == "preflop"
    assert summary.current_seat == summary.button_seat  # heads-up small blind acts first
```

- [ ] **Step 5: Implement deterministic injected shuffle, blinds and private outbounds**

Add optional `texas_holdem_random: RandomSource` to `CoreRepository.__init__`, persist the shuffled deck and DealLayout, debit blind chips from player stacks into contributions, enqueue one private card message per player and transition only after all acknowledgements. A failed private delivery keeps the hand in `dealing`; the recovery job re-enqueues that player's same persisted cards and only a legal board/admin abort refunds the hand.

- [ ] **Step 6: Run focused tests and commit**

Run: `pytest -q tests/core/test_repository.py -k texas_holdem`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: add texas holdem signup and dealing"
```

---

### Task 4: 下注状态机、超时和原子结算

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Produces: `act_texas_holdem(platform_id: str, action: Literal["check", "call", "raise", "all_in", "fold"], amount: int | None, inbound_message_id: UUID, now: datetime) -> TexasHoldemResult`.
- Produces: `run_texas_holdem_jobs(now: datetime) -> list[str]`, `abort_texas_holdem(game_id: UUID, now: datetime) -> bool`, `get_texas_holdem_private_cards(platform_id: str, now: datetime) -> TexasHoldemResult`.
- Consumes Task 1 `apply_betting_action`, `evaluate_best`, `build_side_pots`.

- [ ] **Step 1: Write failing four-street and early-fold settlement tests**

```python
def test_heads_up_check_call_flow_reaches_showdown_and_conserves_money(repository, now):
    started_two_player_hand(repository, now, buy_in=20)
    play_actions(repository, now, [
        ("p1", "call", None), ("p2", "check", None),
        ("p2", "check", None), ("p1", "check", None),
        ("p2", "check", None), ("p1", "check", None),
        ("p2", "check", None), ("p1", "check", None),
    ])
    assert repository.texas_holdem_summary(now).state is None
    assert repository.find_user("p1").balance + repository.find_user("p2").balance == 200

def test_last_unfolded_player_wins_without_revealing_cards(repository, now):
    started_three_player_hand(repository, now, buy_in=20)
    act(repository, "p1", "fold", now)
    act(repository, "p2", "fold", now)
    settlement = repository.latest_texas_holdem_settlement()
    assert settlement.winner_platform_ids == ("p3",)
    assert all(card not in settlement.public_message for card in settlement.all_hole_card_texts)
```

- [ ] **Step 2: Run focused tests and verify failures**

Run: `pytest -q tests/core/test_repository.py -k 'texas_holdem and (action or showdown or fold)'`
Expected: FAIL because action methods do not exist.

- [ ] **Step 3: Implement transactional actions, street advancement, pots and settlement**

Lock the game and acting player; reject stale deadline, wrong seat, duplicate inbound action and illegal rule transitions. Persist action record and player/round snapshot, reveal the next board street, or settle. Before crediting balances assert `sum(final_stacks) == sum(original_buy_in)`; write all credits and final state in one transaction.

- [ ] **Step 4: Add timeout, restart and abort tests**

```python
def test_timeout_checks_when_free_and_folds_when_facing_bet(repository, now):
    game = started_two_player_hand(repository, now)
    repository.run_texas_holdem_jobs(game.action_deadline)
    assert latest_action(repository, game.id).action == "fold"  # preflop small blind faces blind

def test_board_abort_restores_original_buy_ins_after_bets(repository, now):
    game = started_three_player_hand(repository, now)
    place_raise_and_call(repository, now)
    assert repository.abort_texas_holdem(game.id, now)
    assert balances(repository, "p1", "p2", "p3") == (100, 100, 100)
```

- [ ] **Step 5: Implement persistent deadline jobs and exact abort**

Call `run_texas_holdem_jobs` from `run_daily_jobs`. Use the stored absolute deadline; auto-check only when `to_call == 0`, otherwise auto-fold. Abort refunds each `original_buy_in`, clears the active key and reverses the successful daily-start count exactly once.

- [ ] **Step 6: Run repository suite and commit**

Run: `pytest -q tests/core/test_repository.py`
Expected: PASS.

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: settle texas holdem hands"
```

---

### Task 5: 群指令、回复模板、帮助与 AI 知识

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_ai_knowledge.py`

**Interfaces:**
- Registers `/德州扑克`, `/过牌`, `/跟注`, `/加注`, `/全下`, `/弃牌`, `/看牌`.
- Extends unified `/加入`, `/退出`, `/开始`, `/当前游戏`, `/结束游戏` for `game_type == "texas_holdem"`.

- [ ] **Step 1: Write failing command-routing tests**

```python
def test_texas_holdem_commands_create_join_start_and_reply_to_actions():
    service, repository, factory = _service(texas_holdem_random=Random(7))
    prepare_users_and_direct_chats(repository)
    assert "德州扑克报名" in receive(service, "p1", "/德州扑克 20")
    assert "已加入" in receive(service, "p2", "/加入")
    assert "正在私聊发牌" in receive(service, "p2", "/开始")

def test_private_look_cards_never_returns_cards_in_group():
    service, repository, factory = prepared_started_service()
    group = receive_message(service, "look-group", "p1", "/看牌", source_type="group")
    direct = receive_message(
        service, "look-direct", "p1", "/看牌",
        source_type="direct", chatroom_id="direct-p1",
    )
    assert "请在私聊中发送 /看牌" in replies_for(factory, group.message_id)[0]
    assert any(suit in replies_for(factory, direct.message_id)[0] for suit in "♠♥♣♦")
```

- [ ] **Step 2: Run command tests and verify failures**

Run: `pytest -q tests/core/test_group_commands.py -k texas_holdem`
Expected: FAIL because commands are not registered.

- [ ] **Step 3: Implement command parsing and templates**

Parse `/德州扑克` with exactly one integer, `/加注` with exactly one integer total, and no arguments for other actions. Map repository status codes to managed templates. Action replies include actor, amount, pot, stack and next seat; automatic messages use system outbound. Board `/结束游戏` must call exact abort; non-board callers receive a permission response.

- [ ] **Step 4: Add help and AI knowledge assertions**

Assert `/帮助 德州扑克` lists every command and that `AI_KNOWLEDGE_TOPICS["texas_holdem"]` maps only to valid command definitions. Include `texas_holdem` in API topic literals and admin topic selector in Task 7.

- [ ] **Step 5: Run command/knowledge tests and commit**

Run: `pytest -q tests/core/test_group_commands.py tests/core/test_ai_knowledge.py`
Expected: PASS.

```bash
git add src/dzmm_bot/core/commands.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/core/ai_knowledge.py tests/core/test_group_commands.py tests/core/test_ai_knowledge.py
git commit -m "feat: expose texas holdem commands"
```

---

### Task 6: Core 和管理中转 API

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`
- Modify: `tests/browser/test_core_client.py`

**Interfaces:**
- Adds `TexasHoldemSettingsResponse` and `SetTexasHoldemSettingsRequest` with exact validated ranges.
- Adds core/admin `GET/PATCH /game/texas-holdem/settings` routes under their existing `/internal` and `/api` prefixes.
- Extends `GameplayParticipantResponse` with optional seat/state/stack/street contribution/total contribution and `GameplaySummaryResponse` with optional button/current seat, board, pot, action deadline, to-call and legal actions.

- [ ] **Step 1: Write failing settings and public-summary API tests**

```python
def test_texas_holdem_settings_round_trip(client):
    response = client.patch("/internal/game/texas-holdem/settings", json={
        "enabled": True, "minimum_players": 2, "maximum_players": 9,
        "minimum_buy_in": 20, "maximum_buy_in": 200, "daily_start_limit": 1,
        "signup_timeout_seconds": 120, "action_timeout_seconds": 120,
        "small_blind_percent": 5, "big_blind_percent": 10,
    })
    assert response.status_code == 200

def test_current_gameplay_never_serializes_hole_cards(client):
    payload = client.get("/internal/gameplay/current").json()
    assert "hole_cards" not in repr(payload)
```

- [ ] **Step 2: Run focused API tests and verify failures**

Run: `pytest -q tests/core/test_app.py tests/admin/test_app.py -k texas_holdem`
Expected: FAIL with missing routes/models.

- [ ] **Step 3: Implement Pydantic models, routes and client methods**

Follow existing number-bomb versioned settings flow. Validate `minimum_players <= maximum_players`, `minimum_buy_in <= maximum_buy_in`, `small_blind_percent < big_blind_percent`, and positive timeouts. Public summaries must be assembled from explicit allowed fields rather than dumping ORM objects.

- [ ] **Step 4: Run API/client tests and commit**

Run: `pytest -q tests/core/test_app.py tests/admin/test_app.py tests/browser/test_core_client.py -k 'texas_holdem or gameplay'`
Expected: PASS.

```bash
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/app.py tests/core/test_app.py tests/admin/test_app.py tests/browser/test_core_client.py
git commit -m "feat: add texas holdem admin api"
```

---

### Task 7: 管理端德州扑克配置与公开状态

**Files:**
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/admin/static/admin.css` only if existing components cannot express the layout
- Modify: `tests/admin/test_app.py`
- Modify: `tests/admin/test_package_data.py`

**Interfaces:**
- Adds navigation/view `texas-holdem`, settings card/modal, save flow and current public hand card.
- Reuses global current gameplay force-end button with `game_type == "texas_holdem"`.

- [ ] **Step 1: Add failing static-page contract tests**

```python
def test_admin_page_contains_texas_holdem_controls(admin_html):
    assert 'data-view="texas-holdem"' in admin_html
    assert 'id="texas-holdem-settings-card"' in admin_html
    assert 'id="save-texas-holdem-settings"' in admin_html
    assert "底牌不会出现在管理端" in admin_html
```

- [ ] **Step 2: Run admin tests and verify failures**

Run: `pytest -q tests/admin/test_app.py tests/admin/test_package_data.py -k texas_holdem`
Expected: FAIL because controls are absent.

- [ ] **Step 3: Implement settings form and state renderer**

Use the existing `requestGame`, config version/If-Match and modal patterns. Render enabled state, 2–9, 20–200, daily limit, 120-second timers and 5/10 blind percentages. Current state renders board strings, total pot, seat/player public data and current actor; never accepts or renders a hole-card property.

- [ ] **Step 4: Add AI knowledge topic option and game labels**

Add `texas_holdem: "德州扑克"` to navigation metadata, gameplay labels and AI knowledge selector. Keep the existing current-game force-end confirmation and version fencing.

- [ ] **Step 5: Run admin tests and commit**

Run: `pytest -q tests/admin`
Expected: PASS.

```bash
git add src/dzmm_bot/admin/templates/index.html src/dzmm_bot/admin/static/admin.js src/dzmm_bot/admin/static/admin.css tests/admin/test_app.py tests/admin/test_package_data.py
git commit -m "feat: manage texas holdem in admin"
```

---

### Task 8: 全链路回归、文档一致性和部署准备

**Files:**
- Modify only files required by failures discovered in this task.
- Verify: `rule.md`
- Verify: `docs/superpowers/specs/2026-08-17-texas-holdem-single-hand-cash-game-design.md`

**Interfaces:**
- No new interface; validates all previous tasks together.

- [ ] **Step 1: Run migration chain and deploy artifact tests**

Run: `pytest -q tests/deploy tests/runtime/test_contracts.py tests/runtime/test_production_entrypoints.py`
Expected: PASS, Alembic head is `20260817_45`.

- [ ] **Step 2: Run focused end-to-end gameplay suites**

Run: `pytest -q tests/core/test_texas_holdem.py tests/core/test_repository.py tests/core/test_group_commands.py tests/core/test_app.py tests/admin/test_app.py`
Expected: PASS.

- [ ] **Step 3: Run complete test suite**

Run: `pytest -q`
Expected: all tests pass with only the repository's existing intentional skips.

- [ ] **Step 4: Inspect security and money invariants**

Run:

```bash
rg -n "hole_cards|texas_holdem_card" src/dzmm_bot/admin src/dzmm_bot/ai
rg -n "texas_holdem_(buy_in|refund|settlement|abort_refund)" src/dzmm_bot/core
git diff --check
```

Expected: no admin/AI hole-card serialization; all four balance sources exist and are labeled; no whitespace errors.

- [ ] **Step 5: Verify the implementation worktree is clean**

```bash
git status --short
```

Expected: no tracked changes remain after any integration fix has been committed with the exact files changed by that fix; only explicitly ignored pre-existing local files may appear.
