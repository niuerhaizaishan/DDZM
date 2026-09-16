# 随机事件全公司投票与事件广告卡 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **状态：Task 1–12 全部完成**（分支 `feat/random-event-vote`，18 个提交，见文末验收结语）。

**Goal:** 把随机事件"到点随机抽一个场景"改成"提前公布 3 个随机候选 → 全公司投票 → 票高者当选"，并新增付费商品「事件广告卡」，让投稿作者把自己的作品送上第 4 个候选位（只买曝光、不改票数）。

**Architecture:** 投票是**挂在目标场次上的独立对象**，不新增 `random_events.state`，定稿前场次一直是 `pending`；截止（开场前 10 分钟）时把赢家按现有 `_set_random_event_schedule_snapshot` 冻结到场次行，**开场/报名/进行/打赏/结束全链路零改动**。候选抽取**严格复用**现有 `_fill_random_event_schedule_snapshot` 的选池与三档优先逻辑，只是抽 3 个互不相同的场景。广告卡走商店既有的 `effect_type` 分支 + 公演那套"单表 draft + 私聊回填"向导，确认即填入第 4 位。

**Tech Stack:** Python 3.12+、SQLAlchemy 2、Alembic、FastAPI/Pydantic、原生 JavaScript/HTML、pytest。

**Spec:** `docs/superpowers/specs/2026-09-15-random-event-vote-and-ad-slot-design.md`

## Global Constraints

- 投票**全公司唯一一份**；目标场次是主群的下一场（后台其它群的「允许随机事件」已关闭）。
- **每人一票，可改票**；允许作者投自己的作品；**不按职级加权**（`ranks.vote_weight` 全库只用于展示）。
- 3 个随机候选**必须复用** `_fill_random_event_schedule_snapshot`（`repository.py:22040`）的选池与三档优先（没演过且没排过 → 没排过 → 全部）与同一随机源 `secrets.randbelow`；3 个场景互不相同；**档位不足允许跨档补齐**，池子整体不足 3 个才减少候选数。候选只从**配了事件模板**的启用场景里选（没模板演不出来）。随机候选数可配 `1`–`5`。
- 第 4 位：开投时 `vacant`，显示「📣 事件广告卡招商中」且**不可投**；被买下后是**正式候选**（`/事件投票 4` 可投，票高者当选），票数不额外加权。广告位数可配 `0`–`2`，配几个就建几个空位。
- 截止 = 目标场次 `scheduled_at − 10 分钟`，**必须早于**开场前 5 分钟的现有【随机事件预告】（`repository.py:21319-21372`）；定稿必须发生在预告之前。
- 平票三级判定：演出次数少（只数已结束场次，复用 `repository.py:3636-3643` 的写法）→ 投稿晚（`random_event_submissions.submitted_at`；后台自建场景无投稿记录，退化为 `random_event_scenes.created_at`）→ 随机。判定结果要在公告里写明。
- 目标场次被标 `skipped` 时，投票**顺延**到再下一个 `pending` 场次，**已投的票与已填入的第 4 位都保留**；无后续场次则作废。
- **不新增 `random_events.state`**，不改那条部分唯一索引（`schema.py:1846-1852`）与 8 处状态元组。
- 广告卡：购买**无门槛**；`/使用` **强制**必须选一件自己的已审核通过作品；**只在投票 `open` 期间可用**；所有拒绝路径**都不消耗卡且必须给用户提示**；`/确认广告位` 成功后即消耗，**不顺延、不退回**。
- 公告：投票类（开投/播报/定稿/顺延）与广告卡类**共用同一套过滤** = `deleted_at IS NULL` + `listening_enabled` + `announcements_enabled`（与同事最新那版彩票一致）。
- 群消息上限 `1000` 字 / `10` 行，超了会被**拆成多条**：候选公告按"一行一个候选"排版，身份过长只显示人数。
- 幂等：Worker tick ≈ 1 秒但**不精确**；所有一次性播报用落库占位列去重；周期播报判定写成"距上次 ≥ N 分钟"，**不要**写"每 N 次 tick"。
- 播报间隔自适应：`间隔 = max(配置间隔, 窗口 ÷ 6)`（配置默认 30 分钟），每个窗口最多播 6 次。
- 新指令/新状态必须登记**四处**白名单：`_RANDOM_EVENT_CONFIGURABLE_COMMANDS`（否则活动期间永远无法放行）、`_COMMAND_DEFINITIONS`（否则指令静默无反应）、`reply_templates.TEMPLATE_DEFINITIONS`（否则运行时抛"未知模板场景"）、`service.py:121-135` 的私聊控制指令判定（否则私聊里发的指令被丢弃）。
- 不改既有玩法与彩票；spec §9 既有问题第 1 条（奖励口径 `global_completion_reward` vs `event.reward`）**保持现状**。
- 只暂存本功能涉及的文件（工作区另有未跟踪的 spec 文档）。

---

## 阶段 P0：投票主链路（可独立上线）

### Task 1: 迁移与三张投票表

**Files:**

- Create: `migrations/versions/20260915_76_random_event_votes.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Test: `tests/deploy/test_random_event_vote_migration.py`

- [x] 写失败测试：upgrade 建出 `random_event_polls` / `random_event_poll_candidates` / `random_event_poll_votes` 与各自的唯一约束与索引；downgrade 删净；`random_event_settings` 新增配置列。
- [x] 运行 `pytest -q tests/deploy/test_random_event_vote_migration.py`，确认失败。
- [x] 加表与列：`polls(target_schedule_id` 唯一`, status, opened_at, closes_at, closed_at, winner_candidate_id, announced_at, last_tally_at, fallback_reason)`；`candidates(poll_id, position, source, scene_id, template_id, scene_name, event_name, seat_summary, reward, target_rounds, author_name, vacant)` 带 `unique(poll_id, position)` 与 `unique(poll_id, scene_id)`（推荐位来源改记在 `random_event_ad_slots` 上，候选表不再有 `ad_slot_id`；`author_name` 为后加的署名快照）；`votes(poll_id, user_id, candidate_id, created_at, updated_at)` 带 `unique(poll_id, user_id)`；settings 加 `vote_enabled / vote_close_offset_minutes / vote_broadcast_interval_minutes / vote_random_candidates / vote_ad_slot_limit / vote_fallback_minutes / vote_allow_change`。
- [x] `down_revision = "20260915_75"`；重新运行测试确认通过。

> 迁移头当前是 `20260915_75`。三张表的 `poll` 不带 `group_chat_id`（全公司一份），群信息通过 `target_schedule_id` 关联。

### Task 2: 纯逻辑模块

**Files:**

- Create: `src/dzmm_bot/core/random_event_vote.py`
- Test: `tests/core/test_random_event_vote.py`

- [x] 写失败测试：三档优先与**跨档补齐**（只给 2 个"没演过"时，第 3 个来自"没排过"档）；3 个候选互不相同；池子不足 3 个时按实际数量返回；平票三级判定（演出次数 → 投稿时间 → 随机，且随机可复现）；计票与"每人一票"。
- [x] 运行 `pytest -q tests/core/test_random_event_vote.py`，确认失败。
- [x] 实现纯函数：`tiered_pool(scenes, performed, planned)` + `pick_tiered(tiers, count, randbelow)`（原设计的 `pick_candidates`）、`break_tie(candidates, performances, authored_at, randbelow) -> (winner, tier)`、`tally(votes)`。**不碰数据库**，与 `company_lottery.py` 同样式的无依赖模块。
- [x] 重新运行测试确认通过。

> 三档优先的语义必须与 `repository.py:22064-22078` 逐字一致：`unperformed = 没演过且没排过`；`if unperformed: 用 unperformed` 否则 `unplanned = 没排过`；`if unplanned: 用 unplanned`。跨档补齐是本任务的唯一扩展点，要在测试里固定。

### Task 3: 仓储层——建投票、投票、计票、定稿

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`
- Test: `tests/core/test_random_event_vote_repository.py`

- [x] 写失败测试：建投票时抽出 3 个候选且**遵循三档优先**（构造"已演过"与"当天已排"的场景，断言不被选中）；候选 1–3 互不相同；第 4 位 `vacant`；投票与改票（同一人第二次投票只改不新增）；`vacant` 位不可投；定稿后 `schedule.scene_name/event_name/signup_text/formal_opening_text/reward/target_rounds/seats` 被填成赢家（复用 `_set_random_event_schedule_snapshot`）；平票三级判定生效。
- [x] 运行 `pytest -q tests/core/test_random_event_vote_repository.py`，确认失败。
- [x] 实现 `create_random_event_poll`（复用 `_fill_random_event_schedule_snapshot` 的选池：`performed_scene_names` + `planned_scene_names`，**再排除本次已定的候选**）、`cast_random_event_vote`、`random_event_poll_view`、`close_random_event_poll`（定稿冻结）。
- [x] 重新运行测试确认通过。

> 候选生成必须**重新走一遍**现有的过滤查询（`22052-22063`），不要另写一套"排除已演过"的逻辑，否则两处规则会漂。`schedule.scene_name` 在定稿前必须保持 `NULL`——`schedule_random_events` 里那句"`scene_name is None` 就补快照"（`20768-20769`）要跟着改，否则会被旧的随机逻辑抢先冻结。

### Task 4: 调度——开投、播报、兜底、定稿、顺延

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`run_random_event_jobs` `21241`、`_finish_random_event` `22252`）、`src/dzmm_bot/core/reply_templates.py`
- Test: `tests/core/test_random_event_vote_jobs.py`

- [x] 写失败测试：上一场结束即开投并发出开投公告；**定时兜底**（距下一场不足 30 分钟仍无投票则强制开投）；周期播报每 tick 只发一次（连跑 3 次 tick 断言只 1 条）；**截止（T−10）定稿严格早于 T−5 预告**（同一 tick 内也成立）；目标场次被 `skipped` 时顺延到再下一个 `pending` 且票与第 4 位保留；播报间隔按 `max(30 分钟, 窗口/6)`。
- [x] 运行 `pytest -q tests/core/test_random_event_vote_jobs.py`，确认失败。
- [x] 实现四段：兜底开投、周期播报（`last_tally_at` 幂等）、到点定稿（写 `closed_at` + 冻结 + 公告）、顺延处理（改写 `target_schedule_id` / `closes_at`）。
- [x] 重新运行测试确认通过。

> 挂钩点原计划选 `_finish_random_event`（`22252`），**实现时改成 Worker tick 驱动**（`run_random_event_jobs` 里在群循环之前先跑投票任务）：那条链路上没有现成钩子，而 tick 每秒一次、靠 `status` / `last_tally_at` 幂等，行为等价且能在同一 tick 内保证「定稿早于 T−5 预告」。`in_progress` **没有**超时分支，所以兜底开投不是可选优化，是必需路径。所有一次性动作都要落库占位（照 `reminded_at` 的写法，`repository.py:28558-28576`）。

### Task 5: 命令层 `/事件投票`

**Files:**

- Modify: `src/dzmm_bot/core/commands.py`、`src/dzmm_bot/core/repository.py`（`_RANDOM_EVENT_CONFIGURABLE_COMMANDS` `586-597`、`_COMMAND_DEFINITIONS` `2111`）、`src/dzmm_bot/core/reply_templates.py`
- Test: `tests/core/test_random_event_vote_commands.py`

- [x] 写失败测试：`/事件投票 1` 成功并回显票数；改票；序号越界/非数字/缺参数；未入职；投票不存在时；**投 `vacant` 的第 4 位要被明确拒绝**；`/事件投票情况` 展示票型；**随机事件报名中/进行中仍能投票**（门禁放行）。
- [x] 运行 `pytest -q tests/core/test_random_event_vote_commands.py`，确认失败。
- [x] 实现命令与全部文案模板，并**登记四处白名单**（`_RANDOM_EVENT_CONFIGURABLE_COMMANDS`、`_COMMAND_DEFINITIONS`、`TEMPLATE_DEFINITIONS`，外加放进"报名中/进行中允许指令"的默认值）。
- [x] 加一个迁移把新指令**追加进已有库的放行清单**——放行清单存在设置表里，只改代码默认值对已部署的库无效；否则升级后"活动期间投不了票"。
- [x] 重新运行测试确认通过。

> 实测记录（写实现时才发现）：门禁确实会拦 `/事件投票`，`test_vote_command_works_while_a_random_event_is_running` 在实现前就是红的。
> 迁移编号：本任务的放行清单迁移占用 `20260915_77`，Task 7 的广告卡迁移顺延为 `20260915_78`。

> `/投票` 与 `/开始投票` **不能复用**：它们被绑成"谁是卧底"（`group_games.py:48-51`），未开该玩法的群会回"本群未开启「谁是卧底」"。必须用新指令名 `/事件投票`。漏登记 `_COMMAND_DEFINITIONS` 会导致指令静默无反应而 HTTP 仍 200（彩票 `/发放福利` 踩过）。

### Task 6: 后台投票可视化与强制操作

**Files:**

- Modify: `src/dzmm_bot/core/api_models.py`、`src/dzmm_bot/core/app.py`、`src/dzmm_bot/admin/app.py`、`src/dzmm_bot/admin/templates/index.html`、`src/dzmm_bot/admin/static/admin.js`
- Test: `tests/core/test_app.py`、`tests/admin/test_app.py`

- [x] 写失败测试：投票详情接口返回候选、票数、投票人明细、广告位来源；强制截止 / 改判 / **管理员手动指定当选者** 三个操作各改对状态；未授权时 401。
- [x] 运行两个测试文件，确认失败。
- [x] 实现内部接口、Pydantic 模型与后台页面（候选表 + 票数 + 强制操作按钮）。
- [x] 重新运行测试确认通过。

---

## 阶段 P1：事件广告卡

### Task 7: 迁移 + 两张表 + 商品定义

**Files:**

- Create: `migrations/versions/20260915_78_random_event_ad_slots.py`（编号顺延，见本文件上方说明）
- Modify: `src/dzmm_bot/core/schema.py`、`src/dzmm_bot/core/shop_cards.py`
- Test: `tests/deploy/test_random_event_ad_slot_migration.py`

- [x] 写失败测试：upgrade 建出 `random_event_ad_slots`（作者、作品、状态、`poll_id`）与 `random_event_ad_slot_drafts`（`user_id` 唯一 + `current_step` + `expires_at` + `last_activity_at`），downgrade 删净；`事件广告卡` 被 `_ensure_shop_catalog` 种入且 `effect_type="event_ad_slot"`、`unlimited_stock=True`。
- [x] 运行 `pytest -q tests/deploy/test_random_event_ad_slot_migration.py`，确认失败。
- [x] 加表与商品定义；`down_revision = "20260915_76"`。
- [x] 重新运行测试确认通过。

### Task 8: `/使用` 分支 + 私聊向导

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`use_ordinary_shop_item` `25301-25358` 的 `else:` 之前）、`src/dzmm_bot/core/commands.py`、`src/dzmm_bot/core/service.py`（`121-135`）、`src/dzmm_bot/core/reply_templates.py`
- Test: `tests/core/test_random_event_ad_slot_commands.py`

- [x] 写失败测试：**五条拒绝路径各给提示且都不消耗卡**——没有 `open` 的投票 / 没有已通过作品 / 没有可送达私聊房间 / 与候选 1–3 重复 / 第 4 位已被占用；`/选择` 与 `/确认广告位` 在私聊里能被正确路由（不是被当普通指令丢弃）；15 分钟超时后草稿作废但卡还在；确认成功后卡被消耗且第 4 位被填。
- [x] 运行 `pytest -q tests/core/test_random_event_ad_slot_commands.py`，确认失败。
- [x] 实现：`effect_type="event_ad_slot"` 分支（校验私聊房间→返回新状态）、命令层双目标回包、draft 状态机 `pick_event → confirm`、私聊控制指令白名单、全部文案模板。
- [x] 重新运行测试确认通过。

> 私聊路由（`service.py:121-135`）目前只认 `/确认`（`step=="confirm"`）与 `/跳过`（`step=="cover"`）；**不把 `/选择`、`/确认广告位` 加进去，向导会永远卡在第一步**。向导抄公演草稿那套（`repository.py:6754/6819/6864/6877/6930`），不要抄成人卡。

### Task 9: 填入第 4 位、公告、可被投票

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`、`src/dzmm_bot/core/reply_templates.py`
- Test: 追加到 `tests/core/test_random_event_vote_repository.py`

- [x] 写失败测试：填位后第 4 位从 `vacant` 变成正式候选，`/事件投票 4` 可投，且它得票最高时**真的当选**；填位公告与投票公告的**目标群过滤一致**；顺延后第 4 位与票都还在。
- [x] 运行测试确认失败。
- [x] 实现填位、`vacant` 翻转、公告渲染。
- [x] 重新运行测试确认通过。

---

## 阶段 P2：配置、文档与验收

### Task 10: 配置项打通

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`RandomEventSettings` / `update_random_event_settings`）、`src/dzmm_bot/core/api_models.py`、`src/dzmm_bot/core/app.py`、`src/dzmm_bot/admin/*`
- Test: `tests/core/test_app.py`、`tests/admin/test_app.py`

- [x] 写失败测试：七个配置项（投票开关、截止提前量、播报间隔、随机候选数、广告位上限、兜底窗口、是否允许改票）能读能写、越界被拒；改配置不影响已开的投票（候选已冻结）。
- [x] 运行测试确认失败 → 实现 → 重新运行确认通过。

### Task 11: 规则文档

**Files:**

- Modify: `rule.md`

- [x] §6 大改：排期改为"投票决定下一场"，写清候选构成、投票规则、截止与预告的先后、平票判定、顺延、第 4 位广告；**同时补齐 §6 一直缺失的滞后内容**（投稿/审核流程、打赏阶段、"打赏中"状态、开场前 5 分钟预告、报名文案变量、全局完成奖励）。
- [x] §5 新增「事件广告卡」商品条目（购买无门槛、使用强制有作品、只在开投期间可用、拒绝不消耗、确认即消耗不顺延不退回）。
- [x] §16.4 修正彩票公告那句与同事最新代码不一致的描述（"无视本开关" → 与 `4a65a64` 之后的实际实现一致）。
- [x] 通读一遍确认没有互相矛盾的句子（特别是公告范围与门禁放行）。

### Task 12: 端到端验收

**Files:**

- Modify: `tests/core/test_app.py`

- [x] 写端到端测试，全部经由 `/internal/inbound` 与 `/internal/daily-jobs/run` 两个真实入口，串起：上一场结束 → 开投 → 多人投票（含改票）→ 作者买卡并私聊填第 4 位 → 周期播报 → 截止定稿 → 预告（事件名已定）→ 开演链路照旧 → 目标场次被跳过时顺延。
- [x] 运行 `pytest -q`，与干净 `main`（`4a65a64`）逐项对比，**失败集合完全一致**（本机已知 61 项既有失败：Linux 桌面 Xvfb 16、deploy 24、runtime 13、service 3、browser 1、核心既有业务 4）。
- [x] 对照 spec 逐条核对 22 项决策，全部有对应测试或实现证据。
- [x] 记录验收结果（`docs/superpowers/plans/` 内追加一段 `> ` 结语）。


---

## 验收结语（2026-09-15）

> **结论：Task 1–12 全部完成并通过验收，可以交付。** 分支 `feat/random-event-vote`，基于 `4a65a64`，18 个提交；迁移 `20260915_76` → `77` → `78`，单头，可升可降。

> **测试证据**：投票 / 广告位 / 三个新迁移共 `105 passed`；`tests/core` + `tests/deploy` 为 `27 failed / 1283 passed`；全量 `61 failed / 1637 passed / 17 skipped`，失败集合与干净 `main`（`4a65a64`）**逐项一致**——全部是本机既有问题（Linux 桌面 Xvfb 16、deploy 迁移基线 24、runtime 13、service 3、browser 1、核心既有业务 4），本功能零回归。新增/改写用例 20 个。

> **与本计划的三处偏离（均为有意为之，已同步到 spec / rule.md）**：
> 1. 开投不用 `_finish_random_event` 挂钩子，改成 Worker tick 驱动；并额外加了两条：**上一场没演完就先不开下一场**（上一场的投票在它开场前 10 分钟就截止了，不能拿"投票截止"当"上一场结束"），以及**跨天衔接**——当天最后一场演完后先把次日第一场排出来，否则每天第一场永远没有投票。
> 2. `break_tie` 返回 `(winner, tier)`，定稿公告按**实际生效的那一级**写（演出次数 / 投稿时间 / 随机），不再一律写"按演出次数与投稿时间"。
> 3. 命名与上限：`pick_candidates` → `tiered_pool` + `pick_tiered`；随机候选数上限 `5`、广告位上限 `2`（受"一行一个候选"的单条消息 10 行预算约束）。

> **明确未实现（不要当成已完成）**：候选凑不出时**不建投票也不公告**（该分支每秒重算，公告需要额外落库去重）；管理员**改期不会重算** `closes_at`；群级「允许随机事件」关掉后**已开的投票不会立刻作废**（只有总开关 `vote_enabled` 会）；已定稿场次被跳过时**当选节目不顺延**到下一场；`random_event_ad_slots` **只写不读**（后台没有展示位）；广告卡**每人每天限购 1 张未做**（当前不限购）。

> **升级注意**：迁移 `20260915_76` 给 `vote_enabled` 的默认值是 `true`，所以**已部署库升级后立刻**从"到点随机"变成"投票决定"。这是设计意图，但属于既有行为的默认变更，不是 opt-in。

> **审计轮次**：实现完成后做了两轮审计（自查逐文件通读 + 一个独立只读审计），共修掉 12 类问题，其中 4 个会造成真实错误：后台保存一次随机事件规则会把 `/事件投票`、`/事件投票情况` 从放行清单里静默删掉（复选框数组漏登记）；广告位确认先改数据后校验库存且无行锁（"位子被占、卡没扣"）；关掉投票开关会留下收票却永不定稿的僵尸投票；已作废的期次能被后台"改判"复活。修复落在提交 `5b7e0b3`、`852e74a`，文档同步在 `cb101ff`。
