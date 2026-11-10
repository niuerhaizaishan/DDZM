# 工位小游戏构建与发布

源码位于`gamefy-workstation/`，共用页面脚本和样式以`src/dzmm_bot/admin/static/`为准。构建只在忽略的`output/workstation-build/`生成独立项目，不覆盖源码、私有配置或现有平台绑定。

## 本地预览

```bash
python scripts/build_gamefy_workstation.py
python -m zipfile -e output/gamefy-workstation-preview.zip output/workstation-preview
python -m http.server 8894 --bind 127.0.0.1 --directory output/workstation-preview/publish
```

选择新的空解压目录。预览默认使用演示素材，`cardId`为空，不用于上传；不自动读取本机的正式地址或游戏卡ID。完整购买、装卸与群聊联动可使用隔离试玩：

```bash
python scripts/preview_workstation_game.py --port 8895
```

该试玩在回环地址使用独立SQLite和临时身份签名，不需要生产密钥，不向真实群发送消息。

## 正式发布包

使用明确参数构建：

```bash
python scripts/build_gamefy_workstation.py --release --api-base-url https://workstation.example.com --card-id 123456
```

也可复制仓库根目录的`config.local.example.json`为已忽略的`config.local.json`，在`workstation`字段填写自己的`apiBaseUrl`和数字`cardId`，然后运行：

```bash
python scripts/build_gamefy_workstation.py --release
```

配置优先级为命令参数、环境变量、私有JSON。对应构建变量是`DZMM_WORKSTATION_API_BASE_URL`与`DZMM_GAMEFY_CARD_ID`。正式包缺少有效HTTPS地址或正整数卡ID时拒绝构建。后端验证用的`DZMM_GAMEFY_GAME_ID`是JWT audience，需按平台配置单独填写。

默认正式包为`output/gamefy-workstation-release.zip`；`--output`可以指定其他ZIP路径。包内含`dzmm.json`和7个静态文件，使用后端合成图片，不复制完整素材库。每次构建会校验图层布局、文件名单、资源引用及明显的密钥字符串，生成文件不会写回源目录。

## 上传及平台配置

将ZIP通过工坊“上传本地项目”上传到自己的游戏，再按平台流程发布。也可在生成的独立项目中，按平台官方CLI说明绑定、同步基线和发布。没有上游同步基线时先在另一个空目录拉取远端并比较；不能直接强制覆盖平台新版本。

游戏方向应设为竖屏。工坊手机预览还有独立的设备框与预览设置；预览区的16:9留白需要核对宿主实际画布，不能仅凭源码CSS或方向标签宣告修复。正式群游戏卡也需独立验收。

平台JWT、用户身份、余额、价格、装备和支付结果以服务端为准。小游戏只能配置公开后端URL，不能嵌入数据库口令、服务密钥、开发者密钥或浏览器登录资料。

## 服务器变化

使用稳定DNS域名作为`apiBaseUrl`。更换主机时迁移后端与数据库，更新DNS和HTTPS配置，保留域名即可继续使用原小游戏包。若公开域名或游戏卡变化，重新构建并上传。详见[部署与迁移](workstation-deployment.md)。
