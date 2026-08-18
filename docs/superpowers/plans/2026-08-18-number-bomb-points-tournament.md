# 蹦蹦数字炸弹积分赛 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变普通蹦蹦数字炸弹的前提下，实现固定 8 人、最多 12 轮、支持并列与缺席/退赛扣分的独立积分赛。

**Architecture:** 在现有 number bomb 状态机中增加 `standard` / `points_tournament` 模式，以纯领域函数负责竞赛排名与积分，以数据库字段保存赛制、累计积分和每轮积分。命令、私聊报数、提醒、多群隔离、管理员强制结束复用现有链路，仅在创建、结算、退出、继续和展示处按模式分支。

**Tech Stack:** Python 3.13、SQLAlchemy 2、Alembic、FastAPI、pytest、原生 JavaScript 管理端。

**Spec:** `docs/superpowers/specs/2026-08-18-number-bomb-points-tournament-design.md`

## Global Constraints

- 积分赛入口固定为 `/蹦蹦数字炸弹 积分赛`；普通 `/蹦蹦数字炸弹` 行为不变。
- 积分赛固定 8 人、最多 12 轮；达到 8 人自动开始第 1 轮。
- 积分表固定为第 1 名 `+10`、第 2 名 `+5`、第 3–6 名 `0`、第 7 名 `-3`、第 8 名 `+2`，不新增后台可编辑项。
- 并列采用竞赛排名；缺席者固定 `-3` 且不占名次。
- 积分只在本场累计，不流动摸鱼币、不跨场继承。
- 任一未退赛参与者可提前结束；未完整结算轮次整体作废。
- 私聊数字在本轮结算前不得进入群消息、管理 API、AI 上下文或日志。
- 多群对局独立；同群继续遵守现有玩法互斥。
- 所有行为通过迁移和自动化测试后才可请求部署确认。

---

### Task 1: 纯积分排名领域逻辑

**Files:**
- Modify: `src/dzmm_bot/core/number_bomb.py`
- Modify: `tests/core/test_number_bomb.py`

**Interfaces:**
- Consumes: 现有 `NumberBombEntry`、`NumberBombCalculation` 及其偏离值排序结果。
- Produces: `POINTS_TOURNAMENT_SCORES: Mapping[int, int]`；`NumberBombPointsResult`；`calculate_points_tournament_scores(calculation, absent_player_ids) -> NumberBombPointsResult`。

- [ ] **Step 1: 写失败测试，固定竞赛排名和积分表**

```python
def test_points_tournament_uses_competition_ranking_for_ties():
    calculation = NumberBombCalculation(
        total=360,
        player_count=8,
        multiplier_tenths=10,
        target_numerator=3600,
        target_denominator=80,
        standings=tuple(
            NumberBombStanding(
                NumberBombEntry(f"p{i}", f"玩家{i}", i * 10, i),
                deviation,
                None,
            )
            for i, deviation in enumerate((1, 2, 2, 4, 5, 6, 7, 8), 1)
        ),
        valid=True,
    )
    result = calculate_points_tournament_scores(calculation, ())
    assert [item.rank for item in result.ranked_players] == [1, 2, 2, 4, 5, 6, 7, 8]
    assert [item.points for item in result.ranked_players] == [10, 5, 5, 0, 0, 0, -3, 2]
```

- [ ] **Step 2: 运行测试确认因缺少接口失败**

Run: `.venv/bin/pytest -q tests/core/test_number_bomb.py::test_points_tournament_uses_competition_ranking_for_ties`

Expected: collection/import failure for `calculate_points_tournament_scores`.

- [ ] **Step 3: 实现最小领域类型与竞赛排名**

```python
POINTS_TOURNAMENT_SCORES = {1: 10, 2: 5, 3: 0, 4: 0, 5: 0, 6: 0, 7: -3, 8: 2}

@dataclass(frozen=True)
class NumberBombPointsPlayer:
    platform_id: str
    rank: int | None
    points: int
    absent: bool

@dataclass(frozen=True)
class NumberBombPointsResult:
    ranked_players: tuple[NumberBombPointsPlayer, ...]

def calculate_points_tournament_scores(calculation, absent_player_ids):
    reported = tuple(
        sorted(
            calculation.standings,
            key=lambda standing: (
                standing.deviation_numerator,
                standing.entry.display_order,
            ),
        )
    )
    ranked = tuple(
        NumberBombPointsPlayer(
            platform_id=standing.entry.platform_id,
            rank=(
                1
                + sum(
                    other.deviation_numerator < standing.deviation_numerator
                    for other in reported
                )
            ),
            points=POINTS_TOURNAMENT_SCORES.get(
                1
                + sum(
                    other.deviation_numerator < standing.deviation_numerator
                    for other in reported
                ),
                0,
            ),
            absent=False,
        )
        for standing in reported
    )
    absent = tuple(
        NumberBombPointsPlayer(platform_id, None, -3, True)
        for platform_id in absent_player_ids
    )
    return NumberBombPointsResult(ranked + absent)
```

实现时直接基于精确的 `Decimal` 偏离值比较；缺席玩家生成 `rank=None, points=-3, absent=True`，不参与名次计算。

- [ ] **Step 4: 补齐边界测试**

覆盖并列第 1、第 7、第 8，一至七名有效报数、多人缺席和全员缺席；断言缺席者不占名次且当轮可能没有第 8 名。

- [ ] **Step 5: 运行领域测试**

Run: `.venv/bin/pytest -q tests/core/test_number_bomb.py`

Expected: all pass.

- [ ] **Step 6: 提交领域逻辑**

```bash
git add src/dzmm_bot/core/number_bomb.py tests/core/test_number_bomb.py
git commit -m "feat: add number bomb tournament scoring"
```

### Task 2: 持久化赛制、积分与退赛状态

**Files:**
- Modify: `src/dzmm_bot/core/schema.py`
- Create: `migrations/versions/20260818_47_number_bomb_points_tournament.py`
- Create: `tests/deploy/test_number_bomb_points_tournament_migration.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Consumes: `NumberBombGameRecord`、`NumberBombMemberRecord`、`NumberBombRoundPlayerRecord`。
- Produces: `NumberBombGameRecord.mode/maximum_rounds`；`NumberBombMemberRecord.total_points/retired_at_round`；`NumberBombRoundPlayerRecord.competition_rank/round_points/result_reason`。

- [ ] **Step 1: 写 schema 与迁移失败测试**

```python
def test_number_bomb_points_columns_exist():
    assert NumberBombGameRecord.__table__.c.mode.default.arg == "standard"
    assert NumberBombGameRecord.__table__.c.maximum_rounds.default.arg == 0
    assert NumberBombMemberRecord.__table__.c.total_points.default.arg == 0
    assert NumberBombMemberRecord.__table__.c.retired_at_round.nullable is True
    assert NumberBombRoundPlayerRecord.__table__.c.competition_rank.nullable is True
    assert NumberBombRoundPlayerRecord.__table__.c.round_points.default.arg == 0
    assert NumberBombRoundPlayerRecord.__table__.c.result_reason.nullable is True
```

迁移测试从前一 head `20260818_46` 升到 `20260818_47`，断言新增列、非空默认值和 Alembic 单 head。

- [ ] **Step 2: 运行迁移测试确认失败**

Run: `.venv/bin/pytest -q tests/deploy/test_number_bomb_points_tournament_migration.py tests/core/test_repository.py -k number_bomb_points_columns`

Expected: missing revision or missing columns.

- [ ] **Step 3: 增加 SQLAlchemy 字段和 Alembic 迁移**

使用数据库服务端默认值保证历史行兼容：

```python
mode = mapped_column(String(32), nullable=False, default="standard", server_default="standard")
maximum_rounds = mapped_column(Integer, nullable=False, default=0, server_default="0")
total_points = mapped_column(Integer, nullable=False, default=0, server_default="0")
retired_at_round = mapped_column(Integer, nullable=True)
competition_rank = mapped_column(Integer, nullable=True)
round_points = mapped_column(Integer, nullable=False, default=0, server_default="0")
result_reason = mapped_column(String(32), nullable=True)
```

迁移增加约束：mode 仅允许 `standard/points_tournament`；maximum_rounds 仅允许 `0/12`；result_reason 仅允许空值或 `reported/skipped/retired`。

- [ ] **Step 4: 运行 schema 与迁移测试**

Run: `.venv/bin/pytest -q tests/deploy/test_number_bomb_points_tournament_migration.py tests/core/test_repository.py -k number_bomb_points_columns`

Expected: all pass.

- [ ] **Step 5: 提交持久化变更**

```bash
git add src/dzmm_bot/core/schema.py migrations/versions/20260818_47_number_bomb_points_tournament.py tests/deploy/test_number_bomb_points_tournament_migration.py tests/core/test_repository.py
git commit -m "feat: persist number bomb tournament standings"
```

### Task 3: 8 人报名与自动开始

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Consumes: Task 2 的对局/成员字段；现有 `_start_number_bomb_round` 和私聊定位检查。
- Produces: `start_number_bomb_game(platform_id: str, now: datetime, group_chat_id: UUID = PRIMARY_GROUP_CHAT_ID, *, mode: str = "standard") -> NumberBombGameResult`；积分赛第 8 人加入时返回 `NumberBombGameResult(status="round_started")` 和私聊目标。

- [ ] **Step 1: 写失败测试验证模式隔离和第 8 人自动开始**

```python
def test_points_tournament_starts_once_when_eighth_player_joins(repository, now):
    created = repository.start_number_bomb_game("p1", now, mode="points_tournament")
    for index in range(2, 8):
        assert repository.join_number_bomb_game(f"p{index}", now).status == "joined"
    started = repository.join_number_bomb_game("p8", now)
    assert started.status == "round_started"
    assert started.round_number == 1
    assert len(started.players) == 8
    assert repository.number_bomb_game_summary().mode == "points_tournament"
```

增加幂等测试：重复处理第 8 人的相同入站消息不创建第二个 round 1；普通模式 8 人仍不自动开局。

- [ ] **Step 2: 运行聚焦测试确认失败**

Run: `.venv/bin/pytest -q tests/core/test_repository.py -k 'points_tournament_starts_once or standard_number_bomb_does_not_auto_start'`

Expected: unexpected keyword `mode` or signup remains open.

- [ ] **Step 3: 最小实现创建和加入分支**

- `mode="points_tournament"` 时写入 `maximum_rounds=12`。
- 积分赛报名人数上限固定为 8；第 9 人返回 `full`。
- 第 8 人加入事务中直接调用 `_start_number_bomb_round`，确保只创建一次。
- 普通模式保留当前无人数上限、手动 `/开始` 行为。
- 第 8 人加入前复用现有私聊房间校验；缺少私聊时拒绝加入，不能形成无法发牌的满桌。

- [ ] **Step 4: 运行报名与普通模式回归**

Run: `.venv/bin/pytest -q tests/core/test_repository.py -k 'number_bomb and (signup or join or start or points_tournament)'`

Expected: all pass.

- [ ] **Step 5: 提交报名状态机**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: auto start eight-player number bomb tournament"
```

### Task 4: 每轮积分结算、跳过与 12 轮终局

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_repository.py`
- Modify: `tests/core/test_service.py`

**Interfaces:**
- Consumes: `calculate_points_tournament_scores`；Task 2 持久化字段。
- Produces: `_settle_number_bomb_points_round(session: Session, game: NumberBombGameRecord, round_record: NumberBombRoundRecord, now: datetime) -> NumberBombGameResult`；结果中的 `public_message` 包含当轮名次、积分变化和累计榜。

- [ ] **Step 1: 写失败测试验证正常结算与并列**

创建固定随机倍率的 8 人积分赛，提交构造出并列第 2 的数字，断言：

```python
assert [(p.competition_rank, p.round_points) for p in round_players] == [
    (1, 10), (2, 5), (2, 5), (4, 0), (5, 0), (6, 0), (7, -3), (8, 2)
]
assert "累计积分榜" in settled.public_message
```

- [ ] **Step 2: 写失败测试验证跳过者不占名次**

7 人报数、1 人被跳过：跳过者 `rank=None, points=-3, reason="skipped"`；7 名报数者名次 1–7，最后一名 `-3`，消息中没有第 8 名奖励。

- [ ] **Step 3: 运行结算测试确认失败**

Run: `.venv/bin/pytest -q tests/core/test_repository.py -k 'points_tournament and (settle or skipped)'`

Expected: round players have no rank/points and message has no standings.

- [ ] **Step 4: 实现积分赛结算分支**

- `_settle_number_bomb_round` 在 `game.mode == "points_tournament"` 时调用新函数。
- 同一事务写 `competition_rank/round_points/result_reason` 并原子递增成员 `total_points`。
- reported、skipped、retired 三类结果分别持久化。
- 真心话/大冒险仍按轮次 `% 3` 计算；第 1 名为监督者、第 7 名为受罚者，支持多人并列。
- 全员缺席时不计算 F，所有缺席成员各 `-3`，无监督者和受罚者。

- [ ] **Step 5: 写失败测试验证继续、退赛与自动终局**

覆盖：第 1–11 轮只能由未退赛参与者 `/继续`；退赛者不出现在私聊目标并在后续轮次 `-3`；所有人退赛时自动补齐剩余轮扣分；第 12 轮自动结束并清除 active key。

- [ ] **Step 6: 实现继续、退赛和终局**

- 当前轮已报数者退出时保留当轮 reported 结果，`retired_at_round=round+1`。
- 尚未报数者退出时当前轮作为 skipped `-3`，`retired_at_round=round+1`。
- 每次新轮创建 retired round player，直接写 `round_points=-3, reason="retired"`，不生成私聊消息。
- 第 12 轮结算调用 `_finish_number_bomb_game` 并返回最终榜消息。
- 所有成员退赛时一次事务补齐未开始轮次的 retired 记录后结束。

- [ ] **Step 7: 运行状态机与重启恢复测试**

Run: `.venv/bin/pytest -q tests/core/test_repository.py tests/core/test_service.py -k 'number_bomb and points_tournament'`

Expected: all pass, including reconstructing a new `CoreRepository` over the same database between rounds.

- [ ] **Step 8: 提交积分状态机**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py tests/core/test_service.py
git commit -m "feat: settle number bomb tournament rounds"
```

### Task 5: 参与者提前结束与未完成轮作废

**Files:**
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_repository.py`

**Interfaces:**
- Consumes: 现有 `end_number_bomb_game` 与积分赛累计分。
- Produces: 积分赛参与者提前结束结果，公开最终榜；未完成 round 状态变为 `cancelled` 且不写任何 points。

- [ ] **Step 1: 写失败测试验证等待继续时结束**

完成两轮后由任一未退赛参与者结束，断言 active game 释放、最终消息只含两轮累计分、未开始轮次不补分。

- [ ] **Step 2: 写失败测试验证收数中结束**

第三轮仅部分玩家报数后结束，断言 round 3 被取消、所有 round 3 player 的 `round_points` 保持 0 且成员总分等于前两轮。

- [ ] **Step 3: 运行测试确认失败**

Run: `.venv/bin/pytest -q tests/core/test_repository.py -k 'points_tournament and early_end'`

Expected: current behavior finishes without explicit final standings or retains collecting round.

- [ ] **Step 4: 实现提前结束**

- 仅当前对局成员且 `retired_at_round is None` 可以结束；退赛者和非参与者返回 `cannot_end`。
- collecting round 标记 cancelled，清理待发报数提示/提醒，不调用积分结算。
- 使用已持久化的 `total_points` 渲染最终榜并结束对局。

- [ ] **Step 5: 运行提前结束和普通模式回归**

Run: `.venv/bin/pytest -q tests/core/test_repository.py -k 'number_bomb and (early_end or end_game)'`

Expected: all pass;普通模式原结束逻辑不变。

- [ ] **Step 6: 提交提前结束能力**

```bash
git add src/dzmm_bot/core/repository.py tests/core/test_repository.py
git commit -m "feat: allow tournament participants to end early"
```

### Task 6: 群指令、回复模板、帮助与 AI 知识

**Files:**
- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Modify: `tests/core/test_group_commands.py`
- Modify: `tests/core/test_ai_knowledge.py`

**Interfaces:**
- Consumes: Task 3–5 repository statuses and public messages。
- Produces: `/蹦蹦数字炸弹 积分赛`、积分赛 `/当前游戏`、`/继续`、`/退出`、`/结束游戏` 的用户文案和帮助说明。

- [ ] **Step 1: 写失败的命令流程测试**

测试第 8 人 `/加入` 返回“第 1/12 轮”群消息加 8 条私聊提示；`/当前游戏` 包含当前积分；第 12 轮或提前结束返回最终榜。

- [ ] **Step 2: 写失败的帮助与 AI 路由测试**

```python
assert "/蹦蹦数字炸弹 积分赛" in help_reply
assert "第1名 +10" in help_reply
assert route_ai_topics("积分赛第七名扣几分", ()) == ("number_bomb",)
```

- [ ] **Step 3: 运行命令测试确认失败**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py tests/core/test_ai_knowledge.py -k 'number_bomb and (points or tournament or help)'`

Expected: command returns usage or help omits tournament.

- [ ] **Step 4: 实现精确命令解析与模板**

- 仅接受 `/蹦蹦数字炸弹` 和 `/蹦蹦数字炸弹 积分赛` 两种创建格式。
- 新增 signup `N/8`、round `N/12`、缺席扣分、退赛、等待继续、最终榜模板。
- 通用 `/加入 /继续 /退出 /结束游戏 /当前游戏` 继续通过 active gameplay summary 命中正确群的积分赛。
- 私聊 `/报数` 继续支持多群序号选择，不在群内回显数字。

- [ ] **Step 5: 更新帮助、命令库和 AI 权威知识**

命令库 syntax 设为 `/蹦蹦数字炸弹；/蹦蹦数字炸弹 积分赛`；帮助写明积分表、并列、跳过、退赛和提前结束；AI 知识上下文读取当前赛制与轮次，但不读取未结算数字。

- [ ] **Step 6: 运行命令与 AI 测试**

Run: `.venv/bin/pytest -q tests/core/test_group_commands.py tests/core/test_ai_knowledge.py`

Expected: all pass.

- [ ] **Step 7: 提交用户交互**

```bash
git add src/dzmm_bot/core/commands.py src/dzmm_bot/core/reply_templates.py src/dzmm_bot/core/repository.py src/dzmm_bot/core/ai_knowledge.py tests/core/test_group_commands.py tests/core/test_ai_knowledge.py
git commit -m "feat: expose number bomb points tournament commands"
```

### Task 7: 核心 API 与管理端当前积分赛

**Files:**
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `tests/core/test_app.py`
- Modify: `tests/admin/test_app.py`

**Interfaces:**
- Consumes: `number_bomb_game_summary()` 中的 mode、round_number、maximum_rounds、total_points、retired。
- Produces: 公开管理模型仅含已公开状态，不含 collecting round 的 submitted value。

- [ ] **Step 1: 写失败 API 测试**

断言 `/internal/gameplay/current` 的 number bomb item 返回：

```json
{
  "mode": "points_tournament",
  "round_number": 4,
  "maximum_rounds": 12,
  "participants": [{"display_name": "玩家", "total_points": 15, "retired": false}]
}
```

同时递归扫描响应，断言不存在 `submitted_number`、`reported_number` 或任意当前轮数字值。

- [ ] **Step 2: 运行 API 测试确认失败**

Run: `.venv/bin/pytest -q tests/core/test_app.py -k 'number_bomb and points_tournament'`

Expected: response fields missing.

- [ ] **Step 3: 扩展公开 API 模型和适配器**

只添加赛制、轮次、累计分、退赛和是否已报数布尔值；保持数字私密。

- [ ] **Step 4: 写失败管理端静态契约测试**

断言管理脚本渲染“积分赛”“第 N/12 轮”“累计积分”“已退赛”，并继续提供目标群 force-end data attributes；脚本中不得出现 `submitted_number`。

- [ ] **Step 5: 实现管理端展示**

复用现有 number bomb 当前对局卡片，按 `mode` 条件追加积分赛信息；不新增可编辑积分设置。

- [ ] **Step 6: 运行核心与管理端测试及 JS 语法检查**

Run: `.venv/bin/pytest -q tests/core/test_app.py tests/admin/test_app.py -k 'number_bomb or gameplay'`

Run: `node --check src/dzmm_bot/admin/static/admin.js`

Expected: all pass and node exits 0.

- [ ] **Step 7: 提交 API 与管理端**

```bash
git add src/dzmm_bot/core/api_models.py src/dzmm_bot/core/app.py src/dzmm_bot/admin/core_client.py src/dzmm_bot/admin/static/admin.js tests/core/test_app.py tests/admin/test_app.py
git commit -m "feat: show number bomb tournament standings in admin"
```

### Task 8: 规则同步、全量回归与交付门禁

**Files:**
- Modify: `rule.md`
- Modify: `tests/deploy/test_artifacts.py` only if the existing artifact contract explicitly enumerates the new migration or rule file.

**Interfaces:**
- Consumes: Tasks 1–7 完成的功能。
- Produces: 可审计规则、全量验证证据和等待部署确认的干净分支。

- [ ] **Step 1: 更新 rule.md 第 13 节**

加入独立积分赛入口、固定 8 人/12 轮、积分表、竞赛并列、缺席/退赛、真心话/大冒险、第 7 名受罚、第 1 名监督和参与者提前结束规则；保留普通模式原文。

- [ ] **Step 2: 运行积分赛聚焦套件**

Run: `.venv/bin/pytest -q tests/core/test_number_bomb.py tests/core/test_repository.py tests/core/test_service.py tests/core/test_group_commands.py tests/core/test_ai_knowledge.py tests/core/test_app.py tests/admin/test_app.py -k 'number_bomb or points_tournament'`

Expected: all selected tests pass.

- [ ] **Step 3: 运行全量测试**

Run: `.venv/bin/pytest -q`

Expected: all tests pass; skips and existing deprecation warnings may remain but no failures/errors.

- [ ] **Step 4: 运行部署与静态门禁**

Run: `.venv/bin/pytest -q tests/deploy tests/runtime/test_contracts.py tests/runtime/test_production_entrypoints.py`

Run: `.venv/bin/alembic heads`

Expected: deployment/runtime tests pass and exactly one head `20260818_47`.

Run: `node --check src/dzmm_bot/admin/static/admin.js`

Run: `git diff --check`

Run: `rg -n 'submitted_number|reported_number' src/dzmm_bot/admin src/dzmm_bot/ai`

Expected: JavaScript and diff checks exit 0; privacy scan returns no current-round number field exposure.

- [ ] **Step 5: 提交规则与最终测试调整**

```bash
git add rule.md tests/deploy/test_artifacts.py
git commit -m "docs: add number bomb tournament rules"
```

- [ ] **Step 6: 检查分支并停止在部署确认前**

Run: `git status --short`

Expected: no output. Report commit head, migration head, focused/full/deploy test counts, and explicitly state production has not been deployed.
