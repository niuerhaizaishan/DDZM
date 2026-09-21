# 生日祝福（与入职周年）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **状态：主体已完成，剩余 T6（后台面板）与 T15（端到端验收）；T14（入职周年）按 owner 要求暂缓。**

**Goal:** 给公司群加一套生日仪式：员工自助登记生日 → 生日当天早上自动祝福 + 发礼金 → 同事可随礼并汇总播报 → 寿星当天享几项小特权；顺带用同一套引擎支持"入职周年"。

**Architecture:** 新增**独立生日模块**（5 张新表 + 1 段 `run_birthday_jobs` + 4 条指令 + 1 个后台面板），既有表**只给 `group_chats` 加一列 `birthdays_enabled`**（三个群各自的入口开关）。既有玩法只在 4 个挂点上读一个「今天是不是你的生日」的判断（打卡奖励、购彩金额、商店价格、随机事件完成奖励）。幂等全部靠唯一约束（照 `daily_checkins` / `weekly_attendance_settlements`），转账靠「入站消息去重 + 行锁」（照 `tip_random_event`）。

**Tech Stack:** Python 3.12+、SQLAlchemy 2、Alembic、FastAPI/Pydantic、原生 JavaScript/HTML、pytest。

**Spec:** `docs/superpowers/specs/2026-09-17-birthday-blessing-design.md`

## Global Constraints

- 时间一律 `Asia/Shanghai`（`BeijingDateTime` / `BEIJING`）；"今天"按北京时间自然日。
- Worker tick ≈ 1 秒但**不精确**：所有一次性动作必须靠**落库字段或唯一约束**幂等，禁止"每隔 N 个 tick 做一次"。
- 公告过滤与彩票/投票**完全一致**（`deleted_at IS NULL` + `listening_enabled` + `announcements_enabled`），在此之上**只发给 `birthdays_enabled` 的群**（三个群各自可配）；群消息预算 `1000` 字 / `10` 行，超了会被拆条。公告按群各发一条，**礼金/特权/随礼记录全公司一份**（幂等锚点 `(user_id, year)`，与群无关）。
- 新指令必须登记**四处**白名单：`commands._COMMANDS`、`repository._COMMAND_DEFINITIONS`、`reply_templates.TEMPLATE_DEFINITIONS`、`repository._RANDOM_EVENT_CONFIGURABLE_COMMANDS`；进了第四处的**必须**同时加进 `admin/static/admin.js` 的 `randomEventCommandOptions`，否则管理员存一次规则就会把它们静默删掉。
- `/随礼` 放进 `service._RANDOM_EVENT_INDEPENDENT_COMMANDS`（与 `/打赏` 同款），保证活动期间也能随礼。
- 迁移：建 5 张表 + 给 `group_chats` 加一列 `birthdays_enabled`；**编号取决于投票 PR 是否已合并**（本分支基于 `4a65a64`，该基线头是 `20260915_75`）：已合并 → `20260917_79`（`down_revision="20260915_78"`）；未合并 → 自成 `20260917_76`（`down_revision="20260915_75"`），合并前统一重编号。**开工第一步 `git fetch` + `alembic heads` 看真实头号**；`downgrade` 必须可重入（`has_table` / `has_column` 守卫）。
- 经济：礼金**计入「今日收益」**（`today_income` 一行不改）；随礼是玩家间转移；免单/折扣是少回收；打卡双倍与随机事件加成计入收益。
- **本次不做 AI 相关**（决策 14）；不做农历、不做跨群广播、不做私聊贺卡。
- 不改既有玩法与彩票流程，除 4 个明确挂点。
- TDD：每个 Task 先写失败测试、跑红、再实现、再跑绿；每个 Task 结束跑一次相关测试文件。

---

## 阶段 P0：核心（登记 → 祝福 → 礼金 → 运营）

### Task 1: 迁移与 5 张表

**Files:**

- Create: `migrations/versions/20260917_79_birthday_blessing.py`
- Modify: `src/dzmm_bot/core/schema.py`
- Test: `tests/deploy/test_birthday_migration.py`

- [ ] 写失败测试：upgrade 建出 `employee_birthdays`（`user_id` 唯一）、`birthday_greetings`（`unique(user_id, greet_year)`）、`birthday_previews`（`unique(user_id, preview_year)`）、`birthday_tips`（`unique(greeting_id, from_user_id)` + 入站外键）、`birthday_settings`，并给 `group_chats` 加上 `birthdays_enabled`（默认 `true`）；downgrade 删净且可重入。
- [ ] 运行 `pytest -q tests/deploy/test_birthday_migration.py`，确认失败。
- [ ] 按 spec §3 加表加列（含 `group_chats.birthdays_enabled`）；`birthday_settings` 的默认值与 spec §3.5 逐条一致。
- [ ] 重新运行测试确认通过；再跑一次 `alembic heads` 确认单头。

### Task 2: 生日设置（读写 + 校验 + 内部接口）

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`BirthdaySettings` dataclass + `get_birthday_settings` / `update_birthday_settings`）、`src/dzmm_bot/core/api_models.py`、`src/dzmm_bot/core/app.py`
- Test: `tests/core/test_app.py`（追加）

- [ ] 写失败测试：13 个配置项能读能写；越界（时刻格式、金额上限、折扣 1–100、窗口 1–1440、免单注数 0–20）被拒；开关默认 `false`；改动不影响已产生的祝福记录。
- [ ] 运行测试确认失败 → 实现 → 重新运行确认通过。

### Task 3: 生日登记与查询（`/设置生日`、`/我的生日`、`/本月生日`）

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`、`src/dzmm_bot/core/commands.py`、`src/dzmm_bot/core/reply_templates.py`、`src/dzmm_bot/admin/static/admin.js`（复选框同步）
- Test: `tests/core/test_birthday_commands.py`（新建）

- [ ] 写失败测试：`/设置生日 5-20` 成功；`5/20`、`05-20`、`5月20日` 都能解析；`2-30`、`4-31`、`13-1` 被拒；带年份时校验 2/29 只在闰年；**一个自然年只能改一次**（第二次给明确提示）；`visibility` 可切换；未入职给提示；`/我的生日` 回显（含今年还能不能改）；`/本月生日` 只列本月、标出今天是谁。
- [ ] 运行测试确认失败。
- [ ] 实现仓储 + 指令 + 模板，**登记四处白名单**，并把新指令加进 `admin.js` 复选框数组。
- [ ] 加一条守护测试：`admin.js` 的复选框覆盖所有新指令（照投票那次的做法）。
- [ ] 重新运行测试确认通过。

### Task 4: `run_birthday_jobs`——预告 + 祝福 + 幂等

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`run_daily_jobs` 里挂 `run_birthday_jobs`；公告渲染函数）、`src/dzmm_bot/core/reply_templates.py`
- Test: `tests/core/test_birthday_jobs.py`（新建）

- [ ] 写失败测试：到点播报且**连跑 3 个 tick 只发 1 条**；`enabled=false` 全静默；`visibility=private` 不发；**同一天多人合并成一条**；当天晚到也会补发；整天离线不留记录；预告受开关控制、只预告明天、幂等；**三个群各收一条、某群 `birthdays_enabled=false` 就不发**；**礼金只发一次**（不随群数翻倍）。
- [ ] 运行测试确认失败 → 实现 → 重新运行确认通过。

### Task 5: 生日礼金与"今日收益"口径

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`today_income` 排除生日礼金 source）
- Test: `tests/core/test_birthday_jobs.py`、`tests/core/test_repository.py`（回归）

- [ ] 写失败测试：礼金到账、`balance_transactions.source = "birthday_gift"`、**计入 `today_income`**；并保留一条对照用例断言其它 source（打卡/游戏/打赏）的收益统计**一个字都没变**（证明 `today_income` 没被动过）。
- [ ] 运行测试确认失败 → 实现 → 重新运行确认通过。

### Task 6: 后台生日面板

**Files:**

- Modify: `src/dzmm_bot/core/api_models.py`、`src/dzmm_bot/core/app.py`、`src/dzmm_bot/admin/app.py`、`src/dzmm_bot/admin/core_client.py`、`src/dzmm_bot/admin/templates/index.html`、`src/dzmm_bot/admin/static/admin.js`
- Test: `tests/core/test_app.py`、`tests/admin/test_app.py`

- [ ] 写失败测试：设置读写、名单（含未填写名单）、**群级开关三个群各自读写互不影响**、`POST /internal/game/birthday/greet` 在 `dry_run=true` 时**只回文本、无任何副作用**（无余额变动、无公告、无 `birthday_greetings` 行）；`dry_run=false` 才真发；未授权 401。
- [ ] 运行测试确认失败 → 实现接口、生日面板，并在现有「群聊配置」页加上三个群的生日开关 → 重新运行确认通过。

### Task 7: `rule.md` 核心部分

**Files:**

- Modify: `rule.md`

- [ ] 新增「生日祝福」一节（登记、时刻、礼金、特权、隐藏、2/29、每人每年一次）。
- [ ] 按 spec §12 的第 3、4、5、6 条补充既有章节的交叉说明。

---

## 阶段 P1：随礼（社交层）

### Task 8: `/随礼` 转账

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`tip_birthday` + `birthday_tips` 写入）、`src/dzmm_bot/core/commands.py`、`src/dzmm_bot/core/reply_templates.py`、`src/dzmm_bot/core/service.py`（独立放行集合）
- Test: `tests/core/test_birthday_tips.py`（新建）

- [ ] 写失败测试：成功转账（双方流水与余额都对）；超过单次上限被拒；余额不足被拒；**给自己随礼被拒**；同一人第二次被拒；窗口过期被拒；同一条入站消息重复投递**只扣一次**；未入职被拒；每种拒绝都**不产生流水**。
- [ ] 运行测试确认失败 → 实现 → 把 `/随礼` 加进 `_RANDOM_EVENT_INDEPENDENT_COMMANDS` 并补一条"活动进行中仍可随礼"的用例。
- [ ] 重新运行测试确认通过。

### Task 9: 随礼结算与汇总播报

**Files:**

- Modify: `src/dzmm_bot/core/repository.py`（`run_birthday_jobs` 里加结算段 + 汇总渲染）、`src/dzmm_bot/core/reply_templates.py`
- Test: `tests/core/test_birthday_tips.py`（追加）

- [ ] 写失败测试：窗口到点回填 `tips_count`/`tips_total`/`tips_closed_at` 并播报汇总；只结算一次（连跑 3 tick）；无随礼时不播报（或播报"无人随礼"，按 spec 定稿）；名单过长只报人数。
- [ ] 运行测试确认失败 → 实现 → 重新运行确认通过。

---

## 阶段 P2：寿星特权

### Task 10: 打卡双倍

**Files:** `src/dzmm_bot/core/commands.py`（`_check_in`）、Test: `tests/core/test_group_commands.py`（追加）

- [ ] 写失败测试：生日当天打卡奖励 = 基础 × 倍率；非生日不变；`enabled=false` 不变；不影响全勤与连续打卡。
- [ ] 跑红 → 实现 → 跑绿。

### Task 11: 生日当天购彩前 N 注免单

**Files:** `src/dzmm_bot/core/repository.py`（`_company_lottery_purchase` 的 `cost` 计算）、Test: `tests/core/test_company_lottery_repository.py`（追加）

- [ ] 写失败测试（**方案 A，已定**）：生日当天第 1..N 注 `cost=0` 且计入 `birthday_greetings.lottery_tickets`；第 N+1 注恢复原价；非生日不免单；**无开放期次时资格保留**（当天稍后仍有剩余额度）；不产生零额流水；**不改 `company_lottery_bets` 表结构**。
- [ ] 跑红 → 实现 → 跑绿。

### Task 12: 商店 8 折

**Files:** `src/dzmm_bot/core/repository.py`（统一的价格函数）、`src/dzmm_bot/core/commands.py`（`/商店` 渲染）、Test: `tests/core/test_shop_repository.py`、`tests/core/test_group_commands.py`

- [ ] 写失败测试：生日当天**展示价与结算价一致**且为 8 折；非生日原价；职位门槛仍然生效；后台流水金额与折扣价一致。
- [ ] 跑红 → 实现（两处读同一函数）→ 跑绿。

### Task 13: 随机事件完成奖励加成

**Files:** `src/dzmm_bot/core/repository.py`（`repository.py:21789` 附近）、Test: `tests/core/test_repository.py`（追加）

- [ ] 写失败测试：生日当天寿星 `/退出` 领奖 = 基础 ×(1+bonus%)；非生日不变；加成只给寿星本人。
- [ ] 跑红 → 实现 → 跑绿。

---

## 阶段 P3：入职周年与验收

### Task 14: 入职周年（共用引擎）

**Files:** `src/dzmm_bot/core/repository.py`、`src/dzmm_bot/core/reply_templates.py`、`src/dzmm_bot/core/schema.py`（若需要独立的幂等锚点则加一列或加表）、Test: `tests/core/test_birthday_jobs.py`（追加）

- [ ] 写失败测试：入职周年当天播报（文案与生日区分）；`joined_at` 的 2/29 在平年按 2/28；与生日同一天时能同时播报或合并（按 spec 定稿）；开关可单独关闭。
- [ ] 跑红 → 实现 → 跑绿。

### Task 15: 端到端验收与收尾

**Files:** `tests/core/test_app.py`、`rule.md`、本计划文档

- [ ] 写端到端测试：全部经真实入口 `/internal/inbound` 与 `/internal/daily-jobs/run`，串起"登记生日 → 预告 → 祝福（含礼金与特权）→ 随礼 → 结算 → 次日不再重复"。
- [ ] 跑全量 `pytest`，与干净 `4a65a64` **逐项对比失败集合**，必须完全一致（本机已知 61 项既有失败）。
- [ ] 对照 spec 逐条核对 16 项决策 + 6 项待确认的最终口径，全部有测试或实现证据。
- [ ] 在本文件末尾追加 `> ` 验收结语（测试证据、与计划的偏离、明确未实现项）。

---

## 口径已全部定稿（开工前无需再问）

1. **礼金计入「今日收益」**（你：计算）→ Task 5 按「计入 + `today_income` 不改」写。
2. **「送五注」= 方案 A：当天购彩前 N 注免单**（你：A）→ Task 11 按此写，不改 `company_lottery_bets`。
3. **三个群入口可配置**（你：做成可配置）→ Task 1 加列、Task 4 按群广播、Task 6 加群开关。

> 其余 6 项（随礼窗口 60 分钟 / 每人每场一次 / 单次上限 20、2/29 按 2/28、预告默认开、群开关默认开、随礼必须写金额、同日多人合并）已按 spec §14 的默认值写入，随时可改。

---

## 实现进度（2026-09-17）

> **已完成并提交**：T1–T5、T7、T8–T13。分支 `feat/birthday-blessing`（基于 `4a65a64`，迁移 `20260917_76`，单头）。

| Task | 内容 | 提交 |
| --- | --- | --- |
| T1 | 迁移 + 5 张表 + `group_chats.birthdays_enabled` | `aaed519` |
| T2 | 生日设置（仓储 + 校验 + 内部接口） | `fd3a8b8` |
| T3 | `/设置生日`、`/我的生日`、`/本月生日` + 四处白名单 + 可选年份/可见性/一年改一次 | `1d40437`、`0e15863` |
| T4 | `run_birthday_jobs`：预告 + 祝福 + 幂等 + 按群广播 | `637966f` |
| T5 | 生日礼金与今日收益口径（不计入改动，`today_income` 未动） | `637966f` |
| T7 | `rule.md` 新增 §21 + §3/§4/§5/§6/§16.2 交叉说明 | `d8ae5d3` 后一支 |
| T8/T9 | `/随礼` 转账 + 窗口结算与汇总播报 | `d8ae5d3` |
| T10–T13 | 打卡双倍、购彩前 N 注免单、商店折扣、随机事件完成奖励加成 | `9f76003`、`e3dfc6e` |
| T15（部分） | 与干净 `4a65a64` 的失败集合逐项对照 | 见下 |

**验收证据（`tests/core` + `tests/deploy`）**：

- 本分支与干净 `4a65a64`（`git worktree` 另开一份跑的）**失败集合逐项一致**：两边都是同一批本机既有失败（24–25 个 deploy 迁移基线失败 + 3 个既有业务用例 + 偶发的彩票 E2E）。
- 生日相关测试：`tests/core/test_birthday.py`（9）、`test_birthday_commands.py`（13）、`test_birthday_jobs.py`（14）、`test_birthday_perks.py`（8）、`test_birthday_tips.py`（10）、`tests/deploy/test_birthday_migration.py`（8）、`tests/core/test_app.py::*birthday*`（2）＝ **64 项全绿**。
- 过程中新增的一次性黄金断言修正：指令清单（`test_game_management_lists_commands_employees_and_shop_items`）按惯例补上 `/设置生日`、`/我的生日`、`/本月生日`、`/随礼`。

**剩余**：

1. **T6 后台生日面板**：目前只有核心内部接口（`GET/PATCH /internal/game/birthday/settings`），还没有管理端页面与群级开关的 UI；上线要开功能得先直接调这个接口。
2. **T15 正式验收**：端到端用例（真实入口串起"登记 → 预告 → 祝福 → 随礼 → 结算 → 特权"）与验收结语。
3. **T14 入职周年**：按 owner 要求暂缓（引擎已就绪：`birthday.matches` 与 `format_tenure` 都可直接复用）。

**已知取舍（实现时定的，与 spec 有出入的地方）**：

- 三段文案（祝福语 / 预告 / 随礼汇总）放在 `birthday_settings` 里由后台编辑，**没有**走 `reply_templates` 白名单（那是给指令回复用的）；指令回复走 `reply_templates` 不变。
- `same_day_backfill=False` 的语义落地为"只在到点后 30 分钟内发"（常量 `_BIRTHDAY_BACKFILL_WINDOW_MINUTES`）。
- 购彩免单**在当天祝福发出后才生效**（否则 09:00 前能无限刷免单）。
- `/商店` 的**展示价**仍是原价，折扣只体现在实扣与流水上（展示价要跟着改需要给商店列表渲染传当前用户，留待 T6 一起做）。

---

## 剩余工作（可直接接手）

> 只有一件：**T6 的管理端页面**（后端接口全部就绪）。T14 入职周年按 owner 要求不做。

### 接线四步

1. `src/dzmm_bot/admin/core_client.py`：仿 `get_hide_and_seek_settings` / `set_hide_and_seek_settings`（约 913–921 行）加四个方法：
   - `get_birthday_settings() -> dict` → `self._get("/internal/game/birthday/settings")`
   - `set_birthday_settings(settings: dict) -> dict` → `self._client.patch("/internal/game/birthday/settings", json=settings)`
   - `list_birthday_members() -> list[dict]` → `self._get("/internal/game/birthday/members")`
   - `greet_birthday(payload: dict) -> dict` → `self._client.post("/internal/game/birthday/greet", json=payload)`
   抽象基类（约 257 行附近）也要补同名签名。
2. `src/dzmm_bot/admin/app.py`：仿躲猫猫那 4 个代理（约 1956 行起，PATCH 要带 `_relay_core` + `repository.config_version()` + `Idempotency-Key` / `If-Match` 那套）：
   - `GET /api/game/birthday/settings`、`PATCH /api/game/birthday/settings`
   - `GET /api/game/birthday/members`
   - `POST /api/game/birthday/greet`
   - `PATCH /api/game/birthday/groups/{group_id}` → 转发核心的 `PATCH /internal/group-chats/{id}`，body 只带 `birthdays_enabled` 与 `now`（这样不必改现有的群配置页）
3. `src/dzmm_bot/admin/templates/index.html`：
   - 导航：仿第 66 行 `<button id="nav-hide-and-seek" class="nav-item" data-view="hide-and-seek" type="button">躲猫猫</button>` 加一个 `data-view="birthday"`；
   - 面板：仿第 248 行 `<section id="hide-and-seek-view" class="dashboard-view panel" hidden>` 加 `<section id="birthday-view" ...>`，内容＝设置表单（总开关、两个时刻、礼金、免单注数、折扣、打卡倍率、加成、随礼上限、预告/补发/随礼/周年四个开关）+ 三个群的开关 + 名单表格（姓名/工号/生日/可见性/今天）+ 每行「试跑」「补发」按钮 + 一个显示 dry-run 文案的区块。
4. `src/dzmm_bot/admin/static/admin.js`：
   - `pageContext` 加 `birthday` 一项（约 99 行起）；
   - `loadGameView`（2206 行起）里加 `if (view === "birthday") return loadBirthday();`
   - 新增 `loadBirthday()` / `saveBirthdaySettings()` / 试跑与补发的点击处理（仿 `loadHideAndSeek()` 与 3815 行附近的保存写法）。

### 上线前怎么先跑起来（不等 UI）

```bash
PATCH /internal/game/birthday/settings   # body 为 18 个字段的整份覆盖，enabled=true 开总开关
PATCH /internal/group-chats/{id}         # {"birthdays_enabled": false, "now": "..."} 关掉某个群
GET   /internal/game/birthday/members    # 名单（未登记的 month/day 为 null）
POST  /internal/game/birthday/greet      # {"platform_id": "...", "dry_run": true, "now": "..."} 试跑文案
```

### 跑测试（每次都要这么设环境）

```powershell
$rt="D:\Deepseek\.runtime"; New-Item -ItemType Directory -Force -Path $rt | Out-Null
$env:PYTHONPATH="D:\Deepseek\.pyfix;D:\Deepseek\DDZM\.pylibs;D:\Deepseek\DDZM\src"
$env:TMP=$rt; $env:TEMP=$rt; $env:PYTHONUTF8="1"; $env:PYTHONIOENCODING="utf-8"
python -m pytest -q -p no:cacheprovider tests/core/test_birthday.py tests/core/test_birthday_commands.py `
  tests/core/test_birthday_jobs.py tests/core/test_birthday_perks.py tests/core/test_birthday_tips.py `
  tests/deploy/test_birthday_migration.py tests/core/test_app.py -k "birthday"
```
（`PYTHONUTF8=1` 必需；长跑要 `timeoutMs >= 300000`。）

### 这个仓库的踩坑清单（实现时踩过，接手别重犯）

1. **别用"插到 `class Xxx:` 之前"当锚点**：如果那个类上面有 `@dataclass` 装饰器，插入点会落在装饰器与类之间，导致你的类被装饰两次（`TypeError: Cannot overwrite attribute __setattr__`）、原类丢掉装饰器。改用"插到上一个类的最后一个字段之后"或"插到下一个 `def` 之前"。
2. **PowerShell 里别写 `python -c "..."` 带中文/引号**：会被拆坏。把脚本写到 `D:\Deepseek\.runtime\xxx.py` 再 `python xxx.py`（本仓库所有脚手架都这么做的）。
3. **改了配置默认值，记得同步 Pydantic**：`tip_window_minutes` 从 60 改 0 时，`api_models.BirthdaySettingsResponse` 的 `ge=1` 没改 → 设置接口 500。
4. **`sessionmaker()(bind)` 当上下文管理器不会提交**，要用 `sessionmaker.begin()`；测试里改数据忘了提交会得到"改了没生效"的假象。
5. **改了指令清单要同步黄金断言**：`tests/core/test_app.py::test_game_management_lists_commands_employees_and_shop_items` 里那个大集合，每加一条指令都要补。
6. **`_RANDOM_EVENT_INDEPENDENT_COMMANDS` 那条 line 没有尾逗号**：往里追加会隐式拼成一个字符串（`/当前游戏/随礼`），追加时记得补逗号。
7. **新指令四处白名单**：`commands._COMMANDS`、`repository._COMMAND_DEFINITIONS`、`reply_templates.TEMPLATE_DEFINITIONS`、`repository._RANDOM_EVENT_CONFIGURABLE_COMMANDS`，以及 `admin/static/admin.js` 的 `randomEventCommandOptions`（漏了就"活动期间用不了"或"管理员存一次规则就被清掉"）。

