# 公司双色球 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DZMM 多群玩法系统中交付一套号码型彩票「公司双色球」，包含购票、开奖、奖池封顶、单人封顶、按比例折算、全员福利发放与机选。

**Architecture:** 纯逻辑层 `company_lottery.py` 负责号码生成、判档、奖池结算与解析，不碰数据库；仓储层在单个事务内完成购票、开奖结算与全员福利发放，奖池与调节金各走一本 `balance_after` 账本；命令层只做路由与渲染；调度层沿用既有 tick 模式处理停售通知、停售与开奖。号码池压缩为红球 01-10 选 4 + 蓝球 01-06 选 1（1,260 种组合），使头奖在群规模下约一个月出一次。

**Tech Stack:** Python 3.12+、SQLAlchemy 2、Alembic、FastAPI/Pydantic、原生 JavaScript/HTML、pytest。

**Spec:** `docs/superpowers/specs/2026-09-14-company-lottery-design.md`

## Global Constraints

- 玩法标识固定为 `company_lottery`，显示名固定为「公司双色球」；不接入 gameplay gate，不占用「当前游戏」。
- 号码固定为红球 01-10 选 4 个不重复、蓝球 01-06 选 1 个，总组合数 1,260。
- 固定奖金固定为 100 / 50 / 15 / 5 / 1；单注价格 2 摸鱼币；每人每个北京时间自然日最多 5 注。
- 奖池上限 200；单人单期中奖上限 100；启动奖池 100（首期系统注入，之后不再注入）。
- 结算顺序不可调换：入池 → 封顶溢出 → 逐票判档 → **同员工合并** → **合并后封顶** → **可付款不足时折算** → 发放。
- 任何情况下不超发、不出现负余额、不允许系统凭空补币。
- 全员福利门槛恒为「当前已注册员工总数」，每次只发一轮，余数保留。
- 期次、奖池与调节金按群独立；全局只共享配置。
- 开奖前任何查询接口不返回开奖号码与盐。
- 奖池与调节金账本的 `balance_after` 必须与实际余额逐笔一致。
- 当前工作区存在其他未提交改动（`.pylibs/`、`.piptmp/` 为本地测试依赖目录）；只暂存本玩法涉及的文件。

### Task 1: 纯逻辑模块

**Files:**

- Create: `src/dzmm_bot/core/company_lottery.py`
- Create: `tests/core/test_company_lottery.py`

- [x] 写失败测试，覆盖：`tier_counts` 输出 `1/5/24/120/185/925` 且合计 1,260；中奖率 26.5873%；每注期望返回 1.186508；`judge` 九种边界；红球顺序无关；`settle_round` 的稳定态、奖池封顶、同员工合并、合并后封顶、折算在封顶之后、头奖中奖后奖池曲线；`check_welfare` 的六组门槛用例与「不连发」；`parse_single` 的等价写法与四类拒绝；`parse_order` 的机选、别名、引导购票；`quick_tickets` 互不重复与避让已购。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery.py`，确认模块不存在而失败。
- [x] 实现 `PrizeTier`、`Ticket`、`RoundSettlement`、`WelfareCheck`、`Order`、`TicketParseError`，以及 `draw_numbers`、`commit_hash`、`quick_tickets`、`is_quick_pick`、`judge`、`tier_counts`、`total_combinations`、`expected_return`、`settle_round`、`check_welfare`、`round_timing`、`should_notify_close`、`parse_single`、`parse_order`。
- [x] 重新运行上述测试，确认全绿（67 passed）。

### Task 2: 持久化与迁移

**Files:**

- Modify: `src/dzmm_bot/core/schema.py`
- Create: `migrations/versions/20260914_74_company_lottery.py`
- Create: `tests/deploy/test_company_lottery_migration.py`

- [x] 写失败测试，覆盖六张表存在、唯一索引与部分索引生效、配置行已插入、启动奖池 100 已写入账本。
- [x] 运行 `.venv/bin/pytest -q tests/deploy/test_company_lottery_migration.py`，确认缺少模型与迁移而失败。
- [x] 新增 `company_lottery_settings`、`company_lottery_rounds`、`company_lottery_bets`、`company_lottery_drafts`、`company_lottery_pool_ledger`、`company_lottery_welfare`、`company_lottery_welfare_payouts` 七张 ORM；迁移接在当前 `20260909_73_ivorune_platform_node` 后。
- [x] 重新运行上述测试（4 passed）。

> 注意：`tests/deploy/` 在原始 HEAD 上已有 34 个失败用例（与本玩法无关，已用 `git checkout` 隔离验证）；本玩法新增的 4 个迁移用例全部通过。

### Task 3: 购票与双账户账本

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`
- Create: `tests/core/test_company_lottery_repository.py`

- [x] 写失败测试：购票扣款原子性、`inbound_message_id` 幂等、同组合重复拒绝、每日 5 注上限按北京时间自然日重置、停售后拒绝、投注额即时入奖池账本、账本 `balance_after` 与实际余额一致。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery_repository.py -k 'buy or limit or idempotent'`，确认失败。
- [x] 实现 `get_company_lottery_settings`、`current_company_lottery_round`、`ensure_company_lottery_round`、`_company_lottery_purchase`（手选与机选共用内核）、`buy_company_lottery_tickets`、`buy_quick_picks`、`company_lottery_balances`、`_company_lottery_pool_append`。
- [x] 补写并运行余额不足零副作用、跨群独立测试（22 passed）。

> 实施时修正了一处设计缺陷：`company_lottery_bets.inbound_message_id` 原本是唯一约束，
> 但一条消息可以买多注、多行共用同一个入站 ID，会直接插入失败。改为非唯一索引 +
> 在购票内核里显式做「同消息重复投递」检查，手选与机选都能正确幂等。

### Task 4: 引导购票草稿

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `tests/core/test_company_lottery_repository.py`

- [x] 写失败测试：启动草稿并设定目标注数、逐注追加、草稿内发「机选」生成合法号码、手选机选混用、草稿内重复拒绝、15 分钟超时作废不扣款、取消不扣款、确认一次性扣款并落多行注单。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery_repository.py -k 'draft'`，确认失败。
- [x] 实现 `start_company_lottery_draft`、`append_company_lottery_draft`、`append_quick_pick_to_draft`、`load_company_lottery_draft`、`cancel_company_lottery_draft`、`confirm_company_lottery_draft`。
- [x] 重新运行草稿相关测试（35 passed）。

> 目标注数会被当日剩余额度截断：当天已买 1 注时发 `/购买彩票 5 注`，草稿目标是 4。
> 只有确认购买才扣款；超时与取消都不动余额。

### Task 5: 开奖结算与调度

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `tests/core/test_company_lottery_repository.py`

- [x] 写失败测试：开奖幂等、同员工合并后封顶 100、折算发生在封顶之后、奖池溢出转调节金、`capped_count` 与 `winner_count` 落库、开奖后自动开下一期且 `commit_hash` 与号码盐一致、开奖前查询接口不返回号码。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery_repository.py -k 'draw or cap or haircut'`，确认失败。
- [x] 实现 `close_company_lottery_round`、`draw_company_lottery_round`、`_open_company_lottery_round`。
- [x] 在 `run_company_lottery_jobs`（由 `run_daily_jobs` 触发）中完成停售提醒、停售与开奖，并渲染开奖公告。
- [x] 重新运行开奖相关测试（47 passed）。

> 调度挂点确认：`run_daily_jobs(now)` 由 `/internal/daily-jobs/run` 触发，是既有的
> 周期性入口，因此把 `run_company_lottery_jobs(now)` 接在同一个方法里，而不是新开
> 定时器。它遍历所有未删除群聊，各自完成「开期次 → 停售提醒 → 停售 → 开奖 →
> 全员福利」，播报通过 `enqueue_system_outbound` 出队。停售提醒沿用
> `should_notify_close`，只在提醒窗口内且群里超过 30 分钟没说话时才发。

> 两处实现要点：一是购票时销售额已逐笔进池，结算时必须把期初余额拆成
> `pool_opening = 池内余额 − 本期销售额` 再交给 `settle_round`，否则会重复计入；
> 二是同一员工多张中奖票按面值比例分摊实得时会产生整除尾差，尾差补给该员工
> 最后一张中奖票，保证分币不凭空消失（测试 `test_draw_merges_and_caps_per_employee`
> 断言实发合计恰为 100）。

### Task 6: 全员福利发放

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `tests/core/test_company_lottery_repository.py`

- [x] 写失败测试：调节金未达门槛不触发、达到门槛发一轮、超出后余数保留且不连发、每位已入职员工余额 +1、福利表与明细表与账本三方对账一致、员工数为 0 不触发、事务中途失败全量回滚、并发调用只发一轮。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery_repository.py -k 'welfare'`，确认失败。
- [x] 实现 `count_registered_employees`、`settle_company_lottery_welfare`。
- [x] 在开奖 tick 末尾调用 `settle_company_lottery_welfare` 并渲染发放公告。
- [x] 重新运行福利相关测试（12 passed）。

> 门槛恒取「当前已注册员工总数」，因此新增员工后下一次判定即按新人数计算。
> 发放全程一个事务，测试用 monkeypatch 让第二个员工的加币抛错，断言余额、
> 调节金、福利表与明细表全部回滚干净。

### Task 7: 群命令与回复文案

**Files:**

- Modify: `src/dzmm_bot/core/commands.py`
- Modify: `src/dzmm_bot/core/reply_templates.py`
- Modify: `src/dzmm_bot/core/ai_knowledge.py`
- Create: `tests/core/test_company_lottery_commands.py`

- [x] 写失败命令测试（落在新文件 `tests/core/test_company_lottery_commands.py`），覆盖 `/购买彩票` 手选、机选、机选多注、引导购票、草稿内机选、`/确认彩票`、`/取消彩票`、`/彩票`、`/我的彩票`、`/彩票验证`，以及未入职、停售、超时、号码越界、红球个数不符的回复场景。
- [x] 运行 `.venv/bin/pytest -q tests/core/test_company_lottery_commands.py`，确认失败。
- [x] 注册指令与文案模板，实现 `_company_lottery` handler 与草稿续填分支；补写 `/帮助 彩票` 指引与 `ai_knowledge` 知识卡（迁移内种入，含长期期望返回约 1.19 摸鱼币的如实说明）。
- [x] 重新运行命令测试（29 passed）。

### Task 8: 后台配置与报表

**Files:**

- Modify: `src/dzmm_bot/admin/app.py`
- Modify: `src/dzmm_bot/admin/core_client.py`
- Modify: `src/dzmm_bot/admin/templates/index.html`
- Modify: `src/dzmm_bot/admin/static/admin.js`
- Modify: `src/dzmm_bot/core/api_models.py`
- Modify: `src/dzmm_bot/core/app.py`
- Modify: `tests/admin/test_app.py`
- Modify: `tests/core/test_app.py`

- [x] 写失败测试：配置读写（含乐观并发与幂等重放）、期次历史、奖池与调节金流水、中奖明细、员工累计收益、手动开奖与手动注资，以及核心层 `overview` / `draw` / `pool` 三个内部接口。
- [x] 运行相关测试，确认失败。
- [x] 实现后台页面与接口；所有写操作复用仓储层的同一方法（`update_company_lottery_settings`、`draw_company_lottery_round_manually`、`deposit_company_lottery_pool`）。手动开奖额外要求期次已过停售时刻，避免在承诺期内泄露号码。
- [x] 确保启动奖池全公司仅首期注入一次；迁移与仓储层都不按群重复注入（`pool_seed` 可在后台配置）。
- [x] 修正期次排期时区：核心层 `clock` 给的是 UTC，`_open_company_lottery_round` 必须先转北京时间再算 22:00 开奖。
- [x] 重新运行后台测试（新增 3 个用例全绿；其余失败为仓库既有的 Linux 桌面/X11 与 Windows 权限位用例）。

### Task 9: 端到端验收

**Files:**

- Modify: `tests/core/test_app.py`

- [x] 写端到端测试，走通「开卖 → 购票（手选 + 机选 + 引导）→ 停售 → 开奖 → 发奖 → 全员福利 → 开下一期」的完整链路；全部经由 `/internal/inbound` 与 `/internal/daily-jobs/run` 两个真实入口。
- [x] 运行 `pytest -q`：与干净 HEAD 对比失败集合完全一致（62 项，全部为仓库既有失败：Linux 桌面/X11 的 `test_auth_desktop`、迁移基线、Windows 权限位等），未新增失败。
- [x] 对照 spec 逐条核对：概率与期望（`tier_counts` 1/5/24/120/185/925，合计 1,260，期望返回 1.186508）、结算顺序（入池 → 封顶溢出 → 判档 → 合并 → 封顶 → 折算 → 发放）、封顶与折算、全员福利门槛与「每次只发一轮」、机选与手选共用判档、按群独立、开奖前不泄露号码（含后台手动开奖的停售前置条件）。
- [ ] 单群灰度上线，核对首周期奖池曲线与调节金累计是否落在预期区间。
