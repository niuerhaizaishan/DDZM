# 工位图片分层试验

本例把原工位图片里的 10 件核心装备提取为独立透明 PNG，再叠加到已移除设备的底图。现在加入了“先购买、后装备”的本地展示流程；没有数据库、正式账户或服务器变更。

## 查看与操作

- 打开 `workstation-game-demo.html` 的本地预览。
- 点击未购买的装备缩略图：用本地演示余额购买并自动装备；已购买装备可装备或卸下。
- “全部卸下”：仅卸下清单中的 10 件核心装备；杯子、笔记本、手机、控制面板、收纳架、摆件和植物等其他物品保留原样。
- “全部装备”：装备已经购买的设备。
- “查看原图”：对照输入图片，不改变装备选择。
- “保存合成图”：下载当前选择组合的 1536 × 1024 PNG，不包含网页按钮和文字。

## 文件

- `assets/workstation/core-base.png`：保留原图，只在设备轮廓内使用修复像素的底图。
- `assets/workstation/core-repair-source.png`：AI 修复参考图，不直接作为页面底图。
- `assets/workstation/core-repair-mask.png`：实际替换的设备区域；区域外像素与原图完全一致。
- `assets/workstation/layers/`：每件装备的小尺寸透明素材，以及保留原始画布坐标的完整透明图层。
- `assets/workstation/manifest.json`：图层、名称、图片路径、层级和坐标。
- `assets/workstation/core-extraction.json`：原图可见设备的轮廓草稿。
- `assets/workstation/core-equipment-sheet.png`：装备素材预览。
- `assets/workstation/core-composite-preview.png`：全部设备的本地合成结果。
- `workstation-layer-tools.py`：重新生成透明装备、清单和预览；依赖 Pillow。

## 实际采用的处理方式

使用 imagegen 技能的 CLI 路径，服务为 Kurumi 的 OpenAI 兼容接口。未把任何 API Key 写入项目文件。

`gpt-image-1.5` 在该服务没有可用渠道。改用 `gpt-image-2` 编辑原图；该模型没有原生透明输出参数。

最初让模型把主显示器单独提取到绿色背景，再转透明，结果改变了屏幕比例、位置和内容，保存在 `output/imagegen/` 作为对照试验，没有用作最终装备。

当前的核心设备图层采用本地轮廓遮罩提取原图可见像素，保留原来的透视与屏幕内容。AI 仅负责提供设备后方的修复参考；最终底图用原图作基础，仅在设备轮廓内替换像素，保留桌面上的其他物品和背景。

## 底图提示词

```text
Precise object removal for modular game backdrop. Remove all ten core equipment items from the original room: all three computer monitors and stands, the screen light bar, mechanical keyboard, both mice, brass desk lamp at left, handheld console at right, illuminated desktop PC case at far right, and entire foreground ergonomic office chair including cushion. Reconstruct plausible bare desktop, pegboard wall, night city window, floor and cabinets behind them. Remove their contact shadows and stray parts. Keep camera framing, L-shaped wooden desk, window skyline, wall shelves, plants and figurines, desk mat and all other decoration unchanged. No new objects, no replacement equipment, no chair or screens anywhere. Same exact 1536x1024 scene.
```

## 草稿限制

- 这是核心设备拆分，不是完整空工位；其他装饰尚未分离。
- 原图已扁平化，被其他物体遮挡的区域没有原始像素；当前图层包含可见部分，主机、台灯、左屏、椅子可能带有遮挡物或背景边缘。
- 设备卸下时需要的完整轮廓和独立阴影尚未补画。要支持任意组合，需要分别修复这些部位。
- 设备轮廓内被遮挡的背景由 AI 修复，无法逐像素还原；轮廓外直接保留原图，避免模型改动杯子、摆件、收纳架等其他物品。
- 当前余额、购买记录、装备状态保存在浏览器 localStorage；价格和日收入是演示数值，不代表正式经济配置。
- 当前页面不使用 XP、小游戏成长或舒适度；已装备装备只展示工位日收入。

## 保留其他物品的修正

最初直接使用 AI 返回的整张底图，导致桌面上的其他物品也被移除或改动。现在始终以原图作底，只在装备的可见轮廓范围内使用局部修复结果，区域外像素与原图一致。AI 修复参考不得再次直接覆盖整张底图。

## 验证记录

使用本机 Edge 自动验证 10 件图片加载、全部卸下、主显示器单独装备、原图对照保留选择和下载合成 PNG。1280 像素桌面与 390 像素手机布局均已截图检查，手机无横向溢出。浏览器导出的 1536 × 1024 图片与本地全部装备合成预览一致。
