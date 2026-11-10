# 工位素材维护

运行素材保存在`src/dzmm_bot/admin/static/workstation/`。当前引用集合为172张PNG，约105MiB，包含旧工位兼容图层、九部件90档兼容素材及五级独立场景图层。完整文件名、大小和SHA-256见[素材清单](workstation-assets.json)。

服务端根据受信任的设备状态重建图层路径。当前API可访问的素材集合由`WORKSTATION_LAYERS`、`ART_FILENAMES`及`ACCESSORY_FILENAMES`决定；不能使用客户端提供的任意文件路径。

```bash
python scripts/audit_workstation_assets.py --check
python scripts/validate_workstation_layout.py
```

前者检查缺图和无引用PNG，后者检查尺寸、遮挡、桌面接触及设备占地冲突。两条命令都不删除文件、不修改账号。增加新素材后，更新对应注册表及清单：

```bash
python scripts/audit_workstation_assets.py --check --manifest docs/workstation-assets.json
python scripts/audit_workstation_levels.py --output-dir output/workstation-review
```

先验证再提交新的清单。素材文件名包含内容哈希，替换时使用新文件名并更新注册表，避免浏览器不可变缓存继续读取旧图。保留队列快照兼容所需的注册表版本；不能只依据文件年龄删除图片。

原始大图、生成过程、临时对照图与已废弃历史版本不属于运行依赖，放在忽略的`output/`或单独的美术归档中。运行所需的172张素材随源码保留，当前未引入需要额外下载的素材包或Git LFS依赖。
