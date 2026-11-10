# 工位部署与迁移

部署沿用项目的Python服务、PostgreSQL、systemd和Caddy。业务数据库、登录状态及密钥放在代码目录之外。源码不绑定服务器公网IP、平台游戏卡或开发者账号。

## 配置

复制`deploy/env/dzmm.example.env`到服务器私有配置文件，填写该实例的真实值；不要将填写后的配置提交Git。

| 配置 | 用途 |
| --- | --- |
| `DZMM_DATABASE_URL` | 数据库连接，仅后端使用 |
| `DZMM_CORE_TOKEN`、`DZMM_ADMIN_TOKEN` | 服务鉴权密钥，仅后端使用 |
| `DZMM_WORKSTATION_PUBLIC_URL` | 普通签名工位页的公开HTTPS基地址，可留空关闭普通网页入口 |
| `DZMM_GAMEFY_GAME_ID` | 平台签发JWT的游戏audience，按照该平台游戏配置填写，可为规范数字或UUID |
| `DZMM_WORKSTATION_GAME_URL` | 群聊发送的游戏入口，例如`https://www.dzmm.ai/character/123456` |
| `DZMM_WORKSTATION_API_BASE_URL` | 小游戏构建使用的公开HTTPS后端地址 |
| `DZMM_GAMEFY_CARD_ID` | 小游戏构建和上传使用的数字游戏卡ID，与JWT audience分别配置 |
| `DZMM_PUBLIC_HOST` | Caddy使用的稳定DNS域名 |
| `DZMM_ADMIN_WEB_PORT` | 后端Web端口，默认18090；反向代理和应用需一致 |

小游戏公开包只包含后端URL和上传卡ID。数据库连接、服务密钥、Bot token、浏览器登录资料、私钥和绘图API密钥不能进入小游戏包。

## 数据库升级

工位迁移从 `20261021_106` 依次升级到 `20261027_107`、`20261027_108`、`20261104_109` 和 `20261105_110`，增加部件进度、配件所有权、操作回执、每日收益结算表、后台规则和管理操作记录。`20261016_105` 保留为旧数据库的迁移链兼容节点。`20261105_110` 将生日祝福默认设为开启，后续的 `20261107_111` 会在升级时将已关闭的生日祝福总开关和群开关设为开启。升级后管理员可以按需调整开关。

```bash
python -m alembic heads
python -m alembic upgrade head
```

`20261109_merge_workstation` 合并线上生产链 `20261103_130` 与工位 `20261107_111`。随后 `20261109_merge_permanent_honors` 将它们与已部署的永久称号迁移 `20261109_111_permanent_honors` 合为单一迁移头。两个合并节点均只调整版本记录。

升级110后，现有管理员登录入口新增「游戏运营 → 工位管理」。补授工位和结算控制需要超级管理员权限；普通管理员可修改名称、价格和收益规则，查询工位、调整已拥有装备和补齐自动配件。首次读取使用现有默认数值，无需手工导入规则。反向代理继续只开放原有Web入口，`/internal/game/workstation/*`仅供持有核心服务凭据的后台代理使用，不应单独公开。

## 现有账号配件补发

此命令根据每个账号最高已拥有环境补齐配件，保留已有装卸标记，不扣币，也不建立购买流水。默认只报告，明确加`--apply`才写入：

```bash
python scripts/backfill_workstation_accessories.py --env-file /etc/dzmm/dzmm.env
python scripts/backfill_workstation_accessories.py --env-file /etc/dzmm/dzmm.env --apply
```

重复执行不会重复授予。进程环境的`DZMM_DATABASE_URL`优先于`--env-file`；运行前确认连接的是目标数据库。数据库连接不要写在命令参数或共享脚本中。

## 正式收益结算

迁移只创建表，不自动启用收益。先查询状态，再指定首次结算日期进行预检查；以下日期需要替换为该实例实际启用日期：

```bash
python scripts/configure_workstation_income.py --env-file /etc/dzmm/dzmm.env
python scripts/configure_workstation_income.py --env-file /etc/dzmm/dzmm.env --enable --first-date YYYY-MM-DD
python scripts/configure_workstation_income.py --env-file /etc/dzmm/dzmm.env --enable --first-date YYYY-MM-DD --apply
```

暂停与恢复已有配置使用`--disable --apply`、`--enable --apply`。命令不修改既有首次日期、结算游标、账号回执或余额。不会因为迁移或恢复而补发虚构的历史快照。

## 更换服务器

1. 准备新实例和依赖，部署同一版本代码，配置HTTPS并验证必要素材和字体。
2. 在切换窗口停止旧实例的群聊worker、结算调度和其他写入服务；备份完整数据库与私有配置、登录资料。
3. 恢复数据库到新实例，按需执行迁移。保留玩家平台ID、余额、已购等级、当前装备、流水、操作回执、每日结算回执和游标；不要重置结算状态。
4. 核对账号数据、健康检查、平台JWT audience、游戏入口及小额隔离测试结果；确认旧实例保持停止。
5. 切换稳定域名的DNS，启动新实例并观察日志。保持域名不变时，小游戏已发布的后端地址无需随IP改变。

回退应用代码不能丢弃已发放收益的回执或覆盖新的交易数据。旧主机在DNS切换后也不能恢复为并行活跃的群聊写入实例。
