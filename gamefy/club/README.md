# 摸鱼 Club

统一游戏大厅，包含立直麻将、象棋、斗地主、你画我猜、德州扑克、炸金花和 21 点七个游戏模块。

## 首版范围

- 四人东风战、半庄战
- 全模块支持休闲房和 5/10/20 摸鱼币房
- 德州扑克支持 2～8 人连续牌桌、大小盲、加注、全下、边池和摊牌
- 炸金花支持 2～6 人闷牌、看牌、跟注、加注、弃牌和比牌
- 21 点支持 1～5 人对战系统庄家、要牌、停牌、加倍与 Blackjack 赔付
- 15 秒基础出牌时间，整场每人 60 秒时间银行
- 吃、碰、明杠、暗杠、加杠、立直、自摸、荣和、流局和断线自动摸切
- 公共频道和房间频道显示玩家头像，可进入玩家主页、加好友和私聊
- 页面固定为一个手机视口，牌桌和聊天独立滚动

## 本地检查

```bash
node --test gamefy/club/tests/client.test.mjs
PYTHONPATH=. .venv/bin/pytest -q gamefy/club/tests/test_club_sandbox.py
```

## 发布前配置

Gamefy 游戏卡为 `3799452`。上传 `publish/` 前确认 `dzmm.json` 已绑定该 ID，并在服务器环境中配置：

```text
DZMM_CLUB_GAME_ID=3799452
DZMM_CLUB_GAME_URL=https://www.aikda.com/chat?card=3799452
DZMM_CLUB_PUBLIC_API_URL=https://49.234.20.159
DZMM_CLUB_CHATROOM_ID=4fc4a2fd-465a-4436-9884-dbb5e60c6af2
```
