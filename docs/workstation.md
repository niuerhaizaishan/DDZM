# 工位系统

本功能包含群聊指令、账号工位、平台小游戏、图片合成和每日收益结算。群聊与小游戏使用同一套服务端购买、装备和余额记录。部署地址及平台账号标识由各部署实例配置，源码不绑定某台服务器。

## 规则

- 环境共5级，位置、地板、桌子、椅子、绿植随环境整体更换。
- 电脑、显示器、键盘、鼠标每个环境各有基础款和升级款，显示为1-1至5-2。
- 四件设备都已购买到当前已解锁环境的升级款，才可迁入下一环境；仍受职级和余额限制。切回旧环境、基础款或卸下设备不减少购买进度。
- 配件随环境自动获得，不单独购买；历史装卸状态与所有权继续保留，群聊概览不展示配件清单。
- 整套环境日收益为0、2、5、10、20。设备每类10档收益为0、2、5、10、15、20、25、30、35、40。所有价格与投入产出说明见[价格说明](workstation-pricing.md)。
- 收益按当前已装备状态计算。结算启用后按北京时间每日一次入账；交易流水、账号日期回执和结算游标在同一事务提交。迁移和重启不能删除回执或重置游标。

## 群聊入口

`/我的工位`只显示环境、各设备日收益与合计日收益，不再附带游戏入口或发送提示。`/工位游戏`直接发送一张小游戏卡片；自定义网址或个人网页入口则单独发送链接。`/帮助 工位`显示现行指令，小游戏问号弹窗与该文案一致。游戏操作与发图入口的24小时授权支持新指令，并兼容旧版`/我的工位`记录。

常用指令：`/升级 鼠标`、`/升级 环境`、`/装备 鼠标 2-1`、`/装备 环境 2`、`/工位背包`、`/工位收益表`。旧商店、`/我的装备`、`/工位帮助`已退役。

## 代码位置

| 范围 | 入口 |
| --- | --- |
| 价格、名称、收益默认值 | `src/dzmm_bot/core/workstation_catalog.py` |
| 购买进度与报价 | `workstation_growth.py`、`workstation_actions.py` |
| 账号设备与配件 | `workstation_progression.py`、`workstation_accessories.py` |
| 每日结算 | `workstation_income.py` |
| 工位后台与数据库规则 | `core/workstation_admin.py`、`admin/workstation_management.py`、`admin/static/workstation-admin.js` |
| 平台身份与账号接口 | `core/gamefy.py`、`admin/workstation.py` |
| 群聊文案 | `core/equipment_commands.py`、`core/commands.py` |
| 页面及交互 | `admin/static/workstation.js`、`workstation.css`、`admin/templates/workstation.html` |
| 图片与摆放 | `browser/workstation_image.py`、`core/workstation_layout.py`、各级素材注册表 |

付费操作在服务端重查权限、职级、余额与报价版本；重试复用同一请求编号，避免重复扣币。报价不等待图片生成，操作后预览独立生成；成功响应先更新数值，再后台更新场景。图片合成使用本地PNG和Pillow，不调用绘图AI。

## 后台管理

管理控制台「游戏运营 → 工位管理」沿用其他玩法的状态卡、分页列表和规则编辑弹窗，不提供素材预览。

- **运行概览**：玩家数、已拥有环境分布、当前预计每日发放、今日实发及结算开关。
- **玩家工位**：按姓名或工号查询，查看购买进度与当前装备，核对修改后再提交；修正不调整余额。普通管理员只能切换已拥有的环境设备或补齐自动配件，超级管理员还可补授环境设备；补授不降低原有购买进度。
- **价格与收益**：管理员可修改5级环境名称与收益、四次环境迁移总价、四类设备各10档名称、共用设备收益与五次环境内升级价格。环境总价含下一环境四件基础设备，与设备单价独立。保存前展示全体日收益变化与四次环境总价，服务器校验版本；保存后群聊说明、小游戏报价和扣费同步使用新规则，旧页面与旧报价需刷新后重试。旧配置保留原价格，历史订单和结算快照不重算。
- **结算记录**：查询实际发放金额和当时的设备快照。超级管理员可切换自动结算或补跑今日结算，不能用当前装备补算历史日期，也不能清空结算游标。
- **操作记录**：修正工位、修改规则、切换结算与补跑今日无需填写原因，自动记录操作摘要、操作者、前后状态及请求回执；重复请求不会重复执行。

无数据库规则记录时沿用表格默认数值，首次保存后群聊、小游戏报价、列表和结算共用数据库配置。历史订单、扣款和收益回执不会被规则修改重写。职级门槛沿用「职位与部门」的现有配置；功能启停沿用「指令库」的命令开关。

生日祝福默认开启。迁移 `20261107_111` 开启已有的总开关和群级生日开关，升级完成后仍可在后台分别调整。

## 本地验证

安装项目与测试依赖后，运行：

```bash
python -m pip install -e ".[test]"
python scripts/audit_workstation_assets.py --check
python scripts/validate_workstation_layout.py
python -m pytest tests/core/test_workstation*.py tests/core/test_gamefy.py tests/browser/test_workstation_image.py tests/deploy/test_equipment_migration.py tests/deploy/test_workstation_portability.py -q
```

Windows PowerShell不展开通配符时，可使用Python选择测试文件：

```bash
python -c "import pathlib,subprocess,sys; files=[str(p) for p in pathlib.Path('tests/core').glob('test_workstation*.py')]; raise SystemExit(subprocess.call([sys.executable,'-m','pytest',*files,'tests/core/test_gamefy.py','tests/browser/test_workstation_image.py','tests/deploy/test_equipment_migration.py','tests/deploy/test_workstation_portability.py','-q']))"
```

后台联调测试：`python -m pytest tests/core/test_workstation_admin.py tests/admin/test_workstation_management.py tests/deploy/test_equipment_migration.py -q`。

`python scripts/preview_workstation_admin.py --port 8896`启动仅绑定回环地址的后台演示，使用临时SQLite和示例员工，不读取生产数据库，也不连接真实群。超级管理员演示Token为`local-workstation-admin`，普通管理员为`operator / local-demo-password`；这些固定凭据仅用于该隔离演示，不能用于部署。

Linux需要中文字体，例如Ubuntu的`fonts-noto-cjk`；部署预置脚本已包含它。

`python scripts/preview_workstation_game.py --port 8895`提供只绑定回环地址的隔离试玩。它生成独立页面文件，使用本机SQLite与合成账号，不读取生产数据库或向真实群发消息。`python scripts/audit_workstation_levels.py --output-dir output/workstation-review`生成可离线阅读的图片、名称及收益对照。

## 部署与素材

- [配置与服务器迁移](workstation-deployment.md)
- [小游戏打包与发布](gamefy-workstation-publishing.md)
- [素材维护](workstation-assets.md)
- [HTTPS配置](ddzm-https-caddy.md)
