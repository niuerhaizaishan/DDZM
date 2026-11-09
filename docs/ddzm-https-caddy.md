# DDZM稳定域名与HTTPS

使用自己持有的稳定DNS域名作为工位后端入口，例如`workstation.example.com`。更换服务器时更新域名解析，小游戏不需要跟着公网IP变化。仓库Caddy配置通过环境变量注入域名及本机后端端口，不包含具体服务器地址。

## 安装

先把域名解析到目标实例，检查云平台安全组与本机防火墙允许所需的80、443端口，再执行：

```bash
sudo env DZMM_PUBLIC_HOST=workstation.example.com DZMM_ADMIN_WEB_PORT=18090 bash deploy/scripts/deploy_caddy_https.sh
```

此命令只应在确认过的目标服务器上运行。安装脚本在任何服务或防火墙修改前校验域名和端口，保存配置备份、校验固定版本的Caddy归档哈希，再写入：

| 文件 | 用途 |
| --- | --- |
| `/etc/caddy/Caddyfile` | 公开HTTPS站点与本机反向代理配置 |
| `/etc/caddy/dzmm.env` | 仅域名和本机Web端口 |
| `/etc/systemd/system/caddy.service` | 读取上述环境文件的服务定义 |
| `/var/lib/caddy` | 证书、私钥与自动续期状态，属于私有服务器数据 |

Caddy配置不需要数据库连接、管理密钥、Bot token或平台开发者密钥。后端`DZMM_ADMIN_WEB_PORT`必须与代理端口一致；Core等内部端口保持内部服务用途。

## 配置验证和运维

独立运行Caddy校验前需要加载它的环境文件：

```bash
sudo bash -c 'set -a; . /etc/caddy/dzmm.env; set +a; /usr/local/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile'
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

配置改动后验证TLS证书、公开访问、静态资源和后端健康检查。证书及续期数据必须持久化，不能放入Git或小游戏发布包。迁移时保留必要私有配置与数据，并避免旧新两台群聊服务同时写入。

安装脚本固定Caddy二进制版本与SHA-256；升级时同时更新两者并重新验证。环境变量语法及自动HTTPS行为参考[Caddy官方文档](https://caddyserver.com/docs/caddyfile/concepts#environment-variables)。
