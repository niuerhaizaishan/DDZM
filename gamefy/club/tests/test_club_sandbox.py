import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


ROOM_ID = "11111111-1111-4111-8111-111111111111"


def waiting_snapshot():
    now = datetime.now(timezone.utc)
    return {
        "id": ROOM_ID,
        "short_id": "MAHJONG88",
        "creator_name": "房主",
        "room_type": "casual",
        "match_mode": "east",
        "buy_in": 0,
        "prizes": [0, 0, 0, 0],
        "phase": "waiting",
        "version": 0,
        "seat": None,
        "creator_seat": 0,
        "players": [
            {"name": "房主", "ready": False, "online": True},
            None, None, None,
        ],
        "deadline": (now + timedelta(minutes=10)).isoformat(),
        "server_time": now.isoformat(),
        "messages": [],
        "settlement": None,
    }


def playing_snapshot():
    value = waiting_snapshot()
    value.update(phase="playing", version=5, seat=0)
    value["players"] = [
        {"name": name, "ready": True, "online": True}
        for name in ("房主", "南风", "西风", "北风")
    ]
    value["game"] = {
        "mode": "east", "points": [25000] * 4, "dealer": 0,
        "round_wind": 27, "hand_number": 1, "honba": 0,
        "riichi_sticks": 0, "turn": 0,
        "melds": [[], [], [], []], "discards": [[], [], [], []],
        "riichi": [False] * 4, "result": None, "remaining": 69,
        "dora_indicators": [120], "hand": list(range(14)),
        "hand_counts": [14, 13, 13, 13],
        "actions": {"discard": list(range(14)), "riichi": [0]},
    }
    return value


def card_snapshot(game):
    players = [
        {"id": "22222222-2222-4222-8222-222222222222", "name": "房主", "avatar_url": None},
        {"id": "33333333-3333-4333-8333-333333333333", "name": "牌友", "avatar_url": None},
    ]
    common = {
        "id": ROOM_ID, "game": game, "phase": "playing", "creator_id": players[0]["id"],
        "room_type": "casual", "stake": 0, "players": players, "ready": [item["id"] for item in players],
        "me": players[0], "version": 4, "hand_number": 1, "messages": [],
    }
    if game == "texas":
        common["state"] = {"phase": "playing", "players": [item["id"] for item in players],
                           "turn": players[0]["id"], "board": [["hearts", 14], ["clubs", 13], ["spades", 10]],
                           "hands": {players[0]["id"]: [["hearts", 12], ["hearts", 11]], players[1]["id"]: [None, None]},
                           "chips": {players[0]["id"]: 96, players[1]["id"]: 94},
                           "contributions": {players[0]["id"]: 4, players[1]["id"]: 6},
                           "street_bets": {players[0]["id"]: 4, players[1]["id"]: 6}, "current_bet": 6,
                           "minimum_raise": 2, "folded": [], "all_in": [], "acted": [], "pot": 10}
    elif game == "zhajinhua":
        common["state"] = {"phase": "playing", "players": [item["id"] for item in players], "turn": players[0]["id"],
                           "hands": {players[0]["id"]: [["hearts", 12], ["clubs", 12], ["spades", 8]], players[1]["id"]: [None, None, None]},
                           "chips": {players[0]["id"]: 48, players[1]["id"]: 48},
                           "contributions": {players[0]["id"]: 2, players[1]["id"]: 2}, "folded": [], "seen": [], "pot": 4}
    else:
        common["state"] = {"phase": "playing", "players": [item["id"] for item in players], "turn": players[0]["id"],
                           "hands": {players[0]["id"]: [["hearts", 10], ["clubs", 7]], players[1]["id"]: [None, None]},
                           "contributions": {players[0]["id"]: 0, players[1]["id"]: 0}, "pot": 0}
    common["state"]["turn_deadline"] = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    return common


def card_waiting_snapshot(game):
    value = card_snapshot(game)
    value.update(phase="waiting", version=1, hand_number=0, ready=[value["me"]["id"]], state={})
    return value


def card_finished_spectator_snapshot(game):
    value = card_snapshot(game)
    hand_players = list(value["state"]["players"])
    value.update(
        phase="hand_finished", version=5, ready=[],
        me={"id": "44444444-4444-4444-8444-444444444444", "name": "旁观者", "avatar_url": None},
    )
    value["state"].update(
        phase="hand_finished", turn=None, winners=[hand_players[0]], payouts={},
        hand_ranks={player_id: "已摊牌" for player_id in hand_players},
        totals={player_id: 20 for player_id in hand_players},
        results={player_id: "胜" if index == 0 else "负" for index, player_id in enumerate(hand_players)},
    )
    value["state"].pop("turn_deadline", None)
    return value


@pytest.mark.parametrize(("width", "height"), [(320, 700), (390, 844), (844, 390), (1280, 720)])
def test_club_and_table_stay_in_one_viewport(width, height):
    publish = Path(__file__).resolve().parents[1] / "publish"
    state, actions, channel_messages = waiting_snapshot(), [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_init_script(
            "if(window.top===window){window.clubEvents=[];window.dzmm={user:{info:async()=>({id:'host-user'})},"
            "getLaunchParams:async()=>({}),share:async value=>clubEvents.push(['share',value]),"
            "kv:{get:async()=>({value:null}),put:async()=>{}},"
            "loading:{progress:value=>clubEvents.push(['progress',value]),ready:()=>clubEvents.push(['ready']),error:(...v)=>clubEvents.push(['error',v])}};}"
        )

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
                return
            if path.endswith("/api/club/session"):
                request.fulfill(json={
                    "id": "22222222-2222-4222-8222-222222222222",
                    "uid": "host-user", "name": "房主", "avatar_url": None,
                    "employee": True, "balance": 100,
                }, headers=headers)
                return
            if path.endswith("/api/club/active-room"):
                request.fulfill(json=None, headers=headers)
                return
            if path.endswith("/api/club/channel"):
                if request.request.method == "POST":
                    body = request.request.post_data_json
                    channel_messages.append({
                        "id": f"channel-{len(channel_messages) + 1}",
                        "player": {"name": "房主"},
                        "text": body["text"],
                        "at": "2026-10-21T12:00:00+08:00",
                    })
                    request.fulfill(json=channel_messages[-1], headers=headers)
                else:
                    request.fulfill(json=channel_messages, headers=headers)
                return
            if path.endswith("/api/club/social/events"):
                request.fulfill(
                    body='event: social\ndata: {"channel":"","direct":"","friends":""}\n\n',
                    headers={**headers, "Content-Type": "text/event-stream"},
                )
                return
            if path.endswith("/api/club/presence"):
                request.fulfill(json={"online": 8, "playing": 3}, headers=headers)
                return
            if path.endswith("/api/club/profile"):
                request.fulfill(json={
                    "id": "22222222-2222-4222-8222-222222222222",
                    "uid": "host-user", "name": "房主", "avatar_url": None,
                    "employee": True, "balance": 100,
                    "stats": {
                        "total": {"played": 3, "wins": 1, "losses": 1, "draws": 1},
                        "games": {
                            "mahjong": {"played": 1, "wins": 1, "losses": 0, "draws": 0},
                            "chess": {"played": 2, "wins": 0, "losses": 1, "draws": 1},
                            "doudizhu": {"played": 0, "wins": 0, "losses": 0, "draws": 0},
                            "drawguess": {"played": 0, "wins": 0, "losses": 0, "draws": 0},
                        },
                    },
                    "recent_transactions": [{
                        "id": f"tx-{index}", "amount": 20, "label": "任务奖励",
                        "at": "2026-10-21T12:00:00+08:00",
                    } for index in range(12)],
                }, headers=headers)
                return
            if path.endswith("/api/club/tasks"):
                request.fulfill(json=[{
                    "key": "employment", "reward": 20,
                    "eligible": True, "claimed": False, "hidden": False,
                    "cadence": "once",
                }], headers=headers)
                return
            if "/api/club/room-status/" in path:
                game = path.split("/api/club/room-status/", 1)[1].split("/", 1)[0]
                request.fulfill(json={
                    "game": game, "room_id": ROOM_ID, "state": "waiting", "label": "候场",
                    "occupied": 1, "capacity": {"mahjong": 4, "chess": 2}[game], "enterable": True,
                }, headers=headers)
                return
            if path.endswith(("/api/chess/rooms", "/api/doudizhu/rooms", "/api/drawguess/rooms")):
                request.fulfill(json=[], headers=headers)
                return
            if "/api/club/cards/" in path:
                game = path.split("/api/club/cards/", 1)[1].split("/", 1)[0]
                if path.endswith("/rooms"):
                    request.fulfill(json=[{
                        "id": ROOM_ID, "game": game, "creator_name": "房主", "room_type": "casual", "stake": 0,
                            "phase": "waiting", "occupied": 2, "maximum": 8, "mine": False,
                    }], headers=headers)
                    return
                if path.endswith("/events"):
                    request.fulfill(
                        body=f'event: snapshot\ndata: {json.dumps(card_waiting_snapshot(game))}\n\n',
                        headers={**headers, "Content-Type": "text/event-stream"},
                    )
                    return
                request.fulfill(json=card_waiting_snapshot(game), headers=headers)
                return
            if "/api/club/mahjong/" in request.request.url:
                if path.endswith("/actions"):
                    body = request.request.post_data_json
                    actions.append(body)
                    state["version"] += 1
                    if body["action"] == "claim":
                        state["seat"] = 1
                        state["players"][1] = {"name": "测试玩家", "ready": False, "online": True}
                    if body["action"] == "ready":
                        state["players"][state["seat"]]["ready"] = True
                    request.fulfill(json=state, headers=headers)
                    return
                if path.endswith("/chat"):
                    body = request.request.post_data_json
                    state["messages"].append({"id": "m1", "name": "房主", "text": body["text"]})
                    request.fulfill(json=state["messages"][-1], headers=headers)
                    return
                if path.endswith("/rooms"):
                    request.fulfill(json=[{
                        "id": ROOM_ID, "short_id": "MAHJONG88", "room_type": "casual",
                        "creator_name": "房主", "stake": 0,
                        "match_mode": "east", "phase": state["phase"], "occupied": 1,
                        "mine": True, "names": ["房主"],
                    }], headers=headers)
                    return
                request.fulfill(json=state, headers=headers)
                return
            relative = path.strip("/") or "index.html"
            request.fulfill(path=str(publish / relative), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto("https://club.test/index.html")
        expect(page.locator("#club-home")).to_be_visible()
        expect(page.locator("#game-grid .game-card")).to_have_count(7)
        expect(page.locator("#club-presence")).to_contain_text("8 在线")
        expect(page.locator("#club-presence")).to_contain_text("3 游戏中")
        home_layout = page.evaluate("""
            () => {
              const shell = document.querySelector('.app-shell').getBoundingClientRect();
              const nav = document.querySelector('.club-bottom-nav').getBoundingClientRect();
              return {
                bodyWidth: document.body.scrollWidth,
                bodyHeight: document.body.scrollHeight,
                shellWidth: shell.width,
                shellBottom: shell.bottom,
                navBottom: nav.bottom,
              };
            }
        """)
        assert home_layout["bodyWidth"] <= width
        assert home_layout["bodyHeight"] <= height
        assert home_layout["shellBottom"] <= height + 1
        assert home_layout["navBottom"] <= height + 1
        assert home_layout["shellWidth"] >= width - 1
        initial_progress = page.evaluate("clubEvents.filter(event => event[0] === 'progress').length")
        page.locator("#game-grid .game-card").nth(1).click()
        frame = page.locator("#club-game-mount")
        expect(frame.locator("h1")).to_contain_text("群聊象棋")
        expect(page.locator("#club-module-public")).to_be_visible()
        page.locator("#club-module-public").click()
        expect(page.locator("#club-drawer")).to_be_visible()
        page.locator("#club-drawer-close").click()
        page.evaluate("() => window.MoyuClubRuntime.setRoomContext({game:'chess',roomId:'11111111-1111-4111-8111-111111111111',host:'房主'})")
        expect(page.locator("#club-module-share")).to_be_visible()
        page.locator("#club-module-share").click()
        expect(page.locator("#club-channel-messages")).to_contain_text("群聊象棋")
        page.locator("#club-drawer-close").click()
        assert page.evaluate("clubEvents.filter(event => event[0] === 'progress').length") == initial_progress
        page.locator("#club-module-home").click()
        expect(page.locator("#club-home")).to_be_visible()
        for index, title in ((2, "斗地主"), (3, "你画我猜")):
            page.locator("#game-grid .game-card").nth(index).click()
            frame = page.locator("#club-game-mount")
            expect(frame.locator(".lobby")).to_be_visible()
            expect(frame.locator("#feedback")).not_to_contain_text("Cannot read properties")
            page.locator("#club-module-home").click()
            expect(page.locator("#club-home")).to_be_visible()
        for index, title in ((4, "德州扑克"), (5, "炸金花"), (6, "21 点")):
            page.locator("#game-grid .game-card").nth(index).click()
            frame = page.locator("#club-game-mount")
            expect(frame.locator("#lobby")).to_be_visible()
            expect(frame.locator("#game-title")).to_have_text(title)
            frame.locator("#create").click()
            expect(frame.locator("#create-dialog")).to_be_visible()
            frame.locator("#cancel-create").click()
            if index == 4:
                frame.locator("#rooms .room-card").click()
                expect(frame.locator("#waiting")).to_be_visible()
                hud_layout = frame.locator(".room-hud").evaluate("""
                    node => {
                      const title = node.firstElementChild.getBoundingClientRect();
                      const actions = node.lastElementChild.getBoundingClientRect();
                      return {titleRight: title.right, actionsLeft: actions.left, actionsRight: actions.right};
                    }
                """)
                assert hud_layout["titleRight"] <= hud_layout["actionsLeft"]
                assert hud_layout["actionsRight"] <= width
                frame.locator("#room-public-channel").click()
                expect(page.locator("#club-drawer")).to_be_visible()
                expect(page.locator("#club-drawer-title")).to_have_text("公共频道")
                page.locator("#club-channel-input").fill("候场聊两句")
                page.locator("#club-channel-send").click()
                expect(page.locator("#club-channel-messages")).to_contain_text("候场聊两句")
                page.locator("#club-drawer-close").click()
                expect(frame.locator("#waiting")).to_be_visible()
                frame.locator("#chat-toggle").click()
                expect(frame.locator("#chat")).to_be_visible()
                frame.locator("#chat-close").click()
                frame.locator("#back").click()
            frame.locator("#back").click()
            expect(page.locator("#club-home")).to_be_visible()
        page.locator("#profile-toggle").click()
        expect(page.locator("#club-profile")).to_contain_text("对局 3 · 胜 1 · 负 1 · 平 1")
        expect(page.locator("#club-profile")).to_contain_text("群聊象棋 · 2 局 · 0胜 1负 1平")
        expect(page.locator("#club-profile")).to_contain_text("任务奖励")
        expect(page.locator("#club-profile")).to_contain_text("+20")
        profile_panel = page.locator("#club-panel-profile")
        profile_panel.evaluate("node => { node.scrollTop = node.scrollHeight; }")
        assert profile_panel.evaluate("node => node.scrollTop") > 0
        page.locator("#club-drawer-close").click()
        page.locator("#profile-toggle").click()
        page.locator('[data-club-tab="tasks"]').click()
        expect(page.locator("#task-list")).to_contain_text("加入公司")
        expect(page.locator("#task-list")).to_contain_text("+20 摸鱼币")
        page.locator("#club-drawer-close").click()
        page.locator("#game-grid .game-card").first.click()
        expect(page.locator("#mahjong-lobby")).to_be_visible()
        page.locator("#create-room").click()
        expect(page.locator("#create-dialog")).to_be_visible()
        dialog_box = page.locator("#create-dialog").bounding_box()
        assert dialog_box["x"] >= 0
        assert dialog_box["y"] >= 0
        assert dialog_box["x"] + dialog_box["width"] <= width + 1
        assert dialog_box["y"] + dialog_box["height"] <= height + 1
        expect(page.locator("#room-type")).to_be_hidden()
        page.locator('[data-select-for="room-type"] .custom-select-trigger').click()
        expect(page.locator('[data-select-for="room-type"] .custom-select-menu')).to_be_visible()
        page.locator('[data-select-for="room-type"] [data-value="casual"]').click()
        expect(page.locator("#room-type")).to_have_value("casual")
        match_trigger = page.locator('[data-select-for="match-mode"] .custom-select-trigger')
        match_trigger.focus()
        match_trigger.press("ArrowDown")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        expect(page.locator("#match-mode")).to_have_value("south")
        page.locator("#cancel-create").click()
        expect(page.locator("#create-dialog")).not_to_be_visible()
        page.locator("#rooms .room-card").click()
        expect(page.locator("#waiting")).to_be_visible()
        expect(page.locator("#seat-code")).to_have_count(0)
        expect(page.locator("#rooms .room-card strong")).to_have_text("房主的牌桌")
        expect(page.locator("#room-code")).to_have_text("房主的牌桌")
        expect(page.locator("#fullscreen")).to_be_visible()
        expect(page.locator("#home")).not_to_be_visible()
        page.locator("#claim").click()
        expect(page.locator("#waiting-actions")).to_be_visible()
        page.locator("#ready").click()
        expect(page.locator("#ready")).to_have_text("取消准备")
        page.locator("#share-room").click()
        page.locator("#share-room-channel").click()
        expect(page.locator("#club-drawer")).to_be_visible()
        expect(page.locator("#club-channel-messages")).to_contain_text("摸鱼麻将")
        expect(page.locator("#club-channel-messages")).to_contain_text("进入房间")
        assert channel_messages[-1]["text"].startswith("MoyuClubRoom:")
        page.locator("#club-drawer-close").click()
        expect(page.locator("#chat-toggle")).to_be_visible()
        page.locator("#chat-toggle").click()
        page.locator("#chat-channel").click()
        expect(page.locator("#club-drawer")).to_be_visible()
        page.locator("#club-drawer-close").click()
        expect(page.locator("#chat-drawer")).to_be_visible()
        page.locator("#chat-input").fill("好好打牌")
        page.locator("#chat-send").click()
        expect(page.locator("#messages")).to_contain_text("好好打牌")
        page.locator("#chat-close").click()
        expect(page.locator("#chat-preview-lines")).to_contain_text("好好打牌")

        state.clear()
        state.update(playing_snapshot())
        page.wait_for_timeout(1200)
        expect(page.locator("#mahjong-table")).to_be_visible()
        expect(page.locator(".topbar")).to_be_hidden()
        expect(page.locator("#hand .tile")).to_have_count(14)
        expect(page.locator("#hand .tile svg.tile-face")).to_have_count(14)
        expect(page.locator("#hand .tile").first).to_have_attribute("aria-label", "1萬")
        expect(page.locator("#hand .tile svg.tile-face").first).to_have_attribute("data-kind", "man")
        expect(page.locator("#hand .tile").first).to_have_text("一萬")
        expect(page.locator("#remaining-count")).to_have_text("余 69 张")
        expect(page.locator("#self-player")).to_contain_text("东风 · 14 张")
        expect(page.locator("#chat-preview")).to_be_visible()
        tile_box = page.locator("#hand .tile").first.bounding_box()
        assert tile_box["y"] + tile_box["height"] <= height, tile_box
        assert tile_box["x"] >= 0, tile_box
        page.locator("#hand .tile").first.click()
        expect(page.locator("#action-bar")).to_contain_text("立直打出")
        page.locator("#hand .tile").first.dblclick()
        page.wait_for_timeout(200)
        assert actions[-1]["action"] == "discard"
        layout = page.evaluate("""
            () => ({
              bodyHeight: document.body.scrollHeight,
              bodyWidth: document.body.scrollWidth,
              innerHeight,
              innerWidth,
              tableTop: document.querySelector('.mahjong-table').getBoundingClientRect().top,
              tableWidth: document.querySelector('.mahjong-table').getBoundingClientRect().width,
              tableBottom: document.querySelector('.mahjong-table').getBoundingClientRect().bottom,
              tableScreenBottom: document.querySelector('.table-screen').getBoundingClientRect().bottom,
            })
        """)
        assert layout["bodyHeight"] <= layout["innerHeight"]
        assert layout["bodyWidth"] <= layout["innerWidth"]
        assert layout["tableTop"] <= 1
        assert layout["tableWidth"] >= layout["innerWidth"] - 1
        assert layout["tableBottom"] <= layout["innerHeight"] + 1
        assert layout["tableScreenBottom"] <= layout["innerHeight"] + 1
        assert any(event[0] == "ready" for event in page.evaluate("clubEvents"))
        assert actions[0]["action"] == "claim"
        assert actions[0]["payload"] == {}
        assert actions[1]["action"] == "ready"
        browser.close()


@pytest.mark.parametrize("game", ["texas", "zhajinhua", "blackjack"])
@pytest.mark.parametrize(("width", "height"), [(320, 700), (390, 844), (844, 390)])
def test_card_table_modules_fit_phone_viewports(game, width, height):
    publish = Path(__file__).resolve().parents[1] / "publish"
    snapshot = card_snapshot(game)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_init_script("window.dzmm={user:{info:async()=>({id:'host-user'})},loading:{ready(){},error(){}}};")

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if path.endswith("/api/club/session"):
                request.fulfill(json=snapshot["me"], headers=headers)
            elif path.endswith(f"/api/club/cards/{game}/rooms"):
                request.fulfill(json=[{"id": ROOM_ID, "game": game, "creator_name": "房主", "room_type": "casual", "stake": 0,
                                      "phase": "playing", "occupied": 2, "maximum": 8, "mine": True}], headers=headers)
            elif f"/api/club/cards/{game}/rooms/{ROOM_ID}" in path:
                request.fulfill(json=snapshot, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "games/card-table/index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto(f"https://club.test/games/card-table/index.html?game={game}")
        expect(page.locator("#chat")).to_be_hidden()
        expect(page.locator("#table")).to_be_visible()
        expect(page.locator("[data-turn-countdown]")).to_contain_text("你的回合")
        expect(page.locator("[data-turn-countdown]")).to_contain_text("秒")
        expect(page.locator("#chat")).to_be_hidden()
        expect(page.locator("#my-cards .card")).to_have_count(2 if game != "zhajinhua" else 3)
        layout = page.evaluate("""
            () => {
              const actions = document.querySelector('#actions');
              return {
                w: document.body.scrollWidth,
                h: document.body.scrollHeight,
                orientation: document.body.dataset.layout,
                table: document.querySelector('#table').getBoundingClientRect(),
                actions: actions.getBoundingClientRect(),
                actionOverflow: getComputedStyle(actions).overflowX,
                actionScrollWidth: actions.scrollWidth,
                actionClientWidth: actions.clientWidth,
                actionChildren: [...actions.children].map(node => node.getBoundingClientRect()),
              };
            }
        """)
        assert layout["w"] <= width
        assert layout["h"] <= height
        assert layout["orientation"] == ("landscape" if width >= height else "portrait")
        assert layout["table"]["right"] <= width + 1
        assert layout["table"]["bottom"] <= height + 1
        assert layout["actions"]["left"] >= -1
        assert layout["actions"]["right"] <= width + 1
        assert layout["actions"]["top"] >= layout["table"]["top"] - 1
        assert layout["actions"]["bottom"] <= height + 1
        assert layout["actionOverflow"] == "visible"
        assert layout["actionScrollWidth"] <= layout["actionClientWidth"] + 1
        assert all(item["left"] >= -1 and item["right"] <= width + 1
                   and item["top"] >= layout["table"]["top"] - 1
                   and item["bottom"] <= height + 1
                   for item in layout["actionChildren"])
        if game == "texas":
            expect(page.locator(".raise-control")).to_be_visible()
        browser.close()


def test_card_table_reflows_after_orientation_change():
    publish = Path(__file__).resolve().parents[1] / "publish"
    snapshot = card_snapshot("texas")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script("window.dzmm={user:{info:async()=>({id:'host-user'})},loading:{ready(){},error(){}}};")

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if path.endswith("/api/club/session"):
                request.fulfill(json=snapshot["me"], headers=headers)
            elif path.endswith("/api/club/cards/texas/rooms"):
                request.fulfill(json=[{"id": ROOM_ID, "game": "texas", "creator_name": "房主",
                                      "room_type": "casual", "stake": 0, "phase": "playing",
                                      "occupied": 2, "maximum": 8, "mine": True}], headers=headers)
            elif f"/api/club/cards/texas/rooms/{ROOM_ID}" in path:
                request.fulfill(json=snapshot, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "games/card-table/index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto("https://club.test/games/card-table/index.html?game=texas")
        expect(page.locator("#table")).to_be_visible()
        expect(page.locator("body")).to_have_attribute("data-layout", "portrait")

        page.set_viewport_size({"width": 844, "height": 390})
        expect(page.locator("body")).to_have_attribute("data-layout", "landscape")
        layout = page.evaluate("""
            () => {
              const actions = document.querySelector('#actions');
              return {
                bodyWidth: document.body.scrollWidth,
                bodyHeight: document.body.scrollHeight,
                actions: actions.getBoundingClientRect(),
                children: [...actions.children].map(node => node.getBoundingClientRect()),
              };
            }
        """)
        assert layout["bodyWidth"] <= 844
        assert layout["bodyHeight"] <= 390
        assert layout["actions"]["left"] >= -1 and layout["actions"]["right"] <= 845
        assert layout["actions"]["top"] >= -1 and layout["actions"]["bottom"] <= 391
        assert all(item["left"] >= -1 and item["right"] <= 845
                   and item["top"] >= -1 and item["bottom"] <= 391
                   for item in layout["children"])
        browser.close()


@pytest.mark.parametrize("game", ["texas", "zhajinhua", "blackjack"])
def test_spectator_can_join_finished_card_table_for_next_hand(game):
    publish = Path(__file__).resolve().parents[1] / "publish"
    snapshot = card_finished_spectator_snapshot(game)
    actions = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script("window.dzmm={user:{info:async()=>({id:'spectator-user'})},loading:{ready(){},error(){}}};")

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
            elif path.endswith("/api/club/session"):
                request.fulfill(json=snapshot["me"], headers=headers)
            elif path.endswith("/events"):
                request.fulfill(body="", headers={**headers, "Content-Type": "text/event-stream"})
            elif path.endswith("/actions"):
                body = request.request.post_data_json
                actions.append(body["action"])
                if body["action"] == "claim":
                    snapshot["players"].append(snapshot["me"])
                    snapshot["version"] += 1
                request.fulfill(json=snapshot, headers=headers)
            elif path.endswith(f"/api/club/cards/{game}/rooms/{ROOM_ID}"):
                request.fulfill(json=snapshot, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "games/card-table/index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto(f"https://club.test/games/card-table/index.html?game={game}&room={ROOM_ID}")

        expect(page.locator("#result")).to_be_visible()
        expect(page.locator(".showdown-row")).to_have_count(2)
        page.get_by_role("button", name="加入下一手", exact=True).click()
        expect(page.get_by_role("button", name="准备下一手", exact=True)).to_be_visible()
        expect(page.locator(".showdown-row")).to_have_count(2)
        assert actions == ["claim"]
        browser.close()


def test_finished_mahjong_launch_keeps_settlement_room_open():
    publish = Path(__file__).resolve().parents[1] / "publish"
    finished = waiting_snapshot()
    finished.update(phase="match_finished", deadline=None)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script(
            f"window.dzmm={{user:{{info:async()=>({{id:'host-user'}})}},"
            f"getLaunchParams:async()=>({{roomId:'{ROOM_ID}'}}),"
            "loading:{progress(){},ready(){},error(){}}};"
        )

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
            elif path.endswith("/api/club/session"):
                request.fulfill(json={
                    "id": "22222222-2222-4222-8222-222222222222",
                    "uid": "host-user", "name": "房主", "avatar_url": None,
                    "employee": True, "balance": 100,
                }, headers=headers)
            elif path.endswith("/api/club/channel"):
                request.fulfill(json=[], headers=headers)
            elif path.endswith("/api/club/social/events"):
                request.fulfill(
                    body='event: social\ndata: {"channel":"","direct":"","friends":""}\n\n',
                    headers={**headers, "Content-Type": "text/event-stream"},
                )
            elif path.endswith(f"/api/club/mahjong/rooms/{ROOM_ID}"):
                request.fulfill(json=finished, headers=headers)
            elif path.endswith("/api/club/mahjong/rooms"):
                request.fulfill(json=[], headers=headers)
            elif path.endswith("/api/club/presence"):
                request.fulfill(json={"online": 1, "playing": 0}, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto("https://club.test/")

        expect(page.locator("#mahjong-lobby")).to_be_hidden()
        expect(page.locator("#table")).to_be_visible()
        browser.close()


def test_club_boot_restores_the_players_active_card_table():
    publish = Path(__file__).resolve().parents[1] / "publish"
    snapshot = card_waiting_snapshot("texas")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script(
            "window.dzmm={user:{info:async()=>({id:'host-user'})},getLaunchParams:async()=>({}),"
            "loading:{progress(){},ready(){},error(){}}};"
        )

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
            elif path.endswith("/api/club/session"):
                request.fulfill(json=snapshot["me"], headers=headers)
            elif path.endswith("/api/club/channel"):
                request.fulfill(json=[], headers=headers)
            elif path.endswith("/api/club/social/events"):
                request.fulfill(
                    body='event: social\ndata: {"channel":"","direct":"","friends":""}\n\n',
                    headers={**headers, "Content-Type": "text/event-stream"},
                )
            elif path.endswith("/api/club/presence"):
                request.fulfill(json={"online": 1, "playing": 1}, headers=headers)
            elif path.endswith("/api/club/active-room"):
                request.fulfill(json={"game": "texas", "room_id": ROOM_ID, "phase": "waiting"}, headers=headers)
            elif path.endswith(f"/api/club/cards/texas/rooms/{ROOM_ID}/events"):
                request.fulfill(
                    body=f'event: snapshot\ndata: {json.dumps(snapshot)}\n\n',
                    headers={**headers, "Content-Type": "text/event-stream"},
                )
            elif path.endswith(f"/api/club/cards/texas/rooms/{ROOM_ID}"):
                request.fulfill(json=snapshot, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto("https://club.test/index.html")

        expect(page.locator("#club-game")).to_be_visible()
        expect(page.locator("#club-game-mount #waiting")).to_be_visible()
        expect(page.locator("#club-game-mount #game-title")).to_have_text("德州扑克")
        expect(page.locator("#club-home")).to_be_hidden()
        browser.close()


def test_public_chat_avatar_opens_player_profile_and_friend_action():
    publish = Path(__file__).resolve().parents[1] / "publish"
    other_id = "33333333-3333-4333-8333-333333333333"
    avatar = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
    friend_requests = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        context.add_init_script(
            "window.dzmm={user:{info:async()=>({id:'host-user'})},getLaunchParams:async()=>({}),"
            "loading:{progress(){},ready(){},error(){}}};"
        )

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
            elif path.endswith("/api/club/session"):
                request.fulfill(json={"id": "22222222-2222-4222-8222-222222222222", "uid": "host-user",
                                      "name": "房主", "avatar_url": None, "employee": True, "balance": 100}, headers=headers)
            elif path.endswith("/api/club/active-room"):
                request.fulfill(json=None, headers=headers)
            elif path.endswith("/api/club/social/events"):
                request.fulfill(
                    body='event: social\ndata: {"channel":"message-1","direct":"","friends":""}\n\n',
                    headers={**headers, "Content-Type": "text/event-stream"},
                )
            elif path.endswith("/api/club/channel"):
                request.fulfill(json=[
                    {"id": "message-1", "player": {"id": other_id, "name": "牌友", "avatar_url": avatar},
                     "text": "有人开一桌吗？", "at": "2026-10-21T12:00:00+08:00"},
                    {"id": "share-texas", "player": {"id": other_id, "name": "牌友", "avatar_url": None},
                     "text": f'MoyuClubRoom:{{"game":"texas","roomId":"{ROOM_ID}","host":"牌友"}}',
                     "at": "2026-10-21T12:01:00+08:00"},
                    {"id": "share-zhajinhua", "player": {"id": other_id, "name": "牌友", "avatar_url": None},
                     "text": f'MoyuClubRoom:{{"game":"zhajinhua","roomId":"{ROOM_ID}","host":"牌友"}}',
                     "at": "2026-10-21T12:02:00+08:00"},
                    {"id": "share-blackjack", "player": {"id": other_id, "name": "牌友", "avatar_url": None},
                     "text": f'MoyuClubRoom:{{"game":"blackjack","roomId":"{ROOM_ID}","host":"牌友"}}',
                     "at": "2026-10-21T12:03:00+08:00"},
                ], headers=headers)
            elif "/api/club/room-status/" in path:
                game = path.split("/api/club/room-status/", 1)[1].split("/", 1)[0]
                state, label, occupied, capacity, enterable = {
                    "texas": ("waiting", "候场", 5, 8, True),
                    "zhajinhua": ("started", "已开始", 3, 6, True),
                    "blackjack": ("dissolved", "已解散", 0, 5, False),
                }[game]
                request.fulfill(json={"game": game, "room_id": ROOM_ID, "state": state,
                                      "label": label, "occupied": occupied, "capacity": capacity,
                                      "enterable": enterable}, headers=headers)
            elif path.endswith("/api/club/presence"):
                request.fulfill(json={"online": 2, "playing": 0}, headers=headers)
            elif path.endswith("/api/club/profile"):
                request.fulfill(json={"id": "22222222-2222-4222-8222-222222222222", "name": "房主",
                                      "avatar_url": None, "employee": True, "balance": 100,
                                      "stats": {"total": {"played": 0, "wins": 0, "losses": 0, "draws": 0}, "games": {}},
                                      "recent_transactions": []}, headers=headers)
            elif path.endswith(f"/api/club/players/{other_id}"):
                request.fulfill(json={"id": other_id, "name": "牌友", "avatar_url": avatar,
                                      "employee": True, "relationship": "outgoing" if friend_requests else "none"}, headers=headers)
            elif path.endswith("/api/club/friends") and request.request.method == "POST":
                friend_requests.append(request.request.post_data_json)
                request.fulfill(json={"status": "pending"}, headers=headers)
            else:
                request.fulfill(path=str(publish / (path.strip("/") or "index.html")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto("https://club.test/index.html")
        page.locator("#channel-toggle").click()
        expect(page.locator(".room-share-message").nth(0)).to_contain_text("候场 · 人数 5/8")
        expect(page.locator(".room-share-message").nth(0).locator(".room-share-action")).to_have_text("进入房间")
        expect(page.locator(".room-share-message").nth(1)).to_contain_text("已开始 · 人数 3/6")
        expect(page.locator(".room-share-message").nth(1).locator(".room-share-action")).to_have_text("进入观战")
        expect(page.locator(".room-share-message").nth(2)).to_contain_text("已解散 · 人数 0/5")
        expect(page.locator(".room-share-message").nth(2).locator(".room-share-action")).to_be_disabled()
        expect(page.locator("#club-channel-messages .message-avatar img")).to_have_count(1)
        page.locator("#club-channel-messages .message-avatar").first.click()
        expect(page.locator("#club-profile")).to_contain_text("牌友")
        expect(page.locator("#club-profile .profile-actions button")).to_have_text("添加好友")
        page.locator("#club-profile .profile-actions button").click()
        expect(page.locator("#club-profile .profile-actions button")).to_have_text("好友申请已发送")
        assert friend_requests == [{"player_id": other_id}]
        browser.close()


def test_source_does_not_use_forbidden_storage_or_expand_the_page():
    publish = Path(__file__).resolve().parents[1] / "publish"
    source = "\n".join(path.read_text() for path in publish.rglob("*") if path.suffix in {".js", ".css", ".html"})
    assert "localStorage" not in source
    assert "seat-code" not in source
    assert "入座码" not in source
    assert "100dvh" in source
    assert "overflow:hidden" in source.replace(" ", "")
    assert "new URL(path, location.href)" not in source
    assert "club-game-frame" not in source
    assert "<iframe" not in (publish / "index.html").read_text()
    for asset in (
        "club-hero-v2.webp", "game-mahjong.webp", "game-chess.webp",
        "game-doudizhu.webp", "game-drawguess.webp", "mahjong-table.webp",
        "moyu-coin-v1.webp", "mahjong-tile-v1.webp",
        "game-texas-table-v1.webp", "game-zhajinhua-table-v1.webp", "game-blackjack-table-v1.webp",
    ):
        assert (publish / "assets" / asset).is_file()
        assert asset in source
    for asset in ("games/chess/piece-blank-v1.webp", "games/doudizhu/card-back-v1.webp"):
        assert (publish / asset).is_file()
        assert Path(asset).name in source


@pytest.mark.parametrize(("game", "header", "brand", "screen", "primary", "toggle", "drawer", "body_class"), [
    ("chess", ".game-header", ".brand", ".layout", ".board-stage", "#chess-social-toggle", "#chess-social", ""),
    ("doudizhu", ".game-header", ".brand", "#table", ".play-stage", "#chat summary", "#chat", "table-open"),
    ("drawguess", ".brand-bar", ".brand-mark", "#room-view", ".game-column", "#draw-chat-toggle", "#draw-chat", "room-open"),
])
@pytest.mark.parametrize(("width", "height"), [(390, 844), (844, 390), (1280, 720)])
def test_embedded_subgame_keeps_primary_play_area_and_uses_chat_drawer(game, header, brand, screen, primary, toggle, drawer, body_class, width, height):
    publish = Path(__file__).resolve().parents[1] / "publish"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(viewport={"width": width, "height": height})
        context.add_init_script(
            "window.dzmm={user:{info:async()=>({id:'host-user'})},getLaunchParams:async()=>({}),"
            "kv:{get:async()=>({value:null}),put:async()=>{}},log:{info:()=>{},error:()=>{}},"
            "loading:{progress:()=>{},ready:()=>{},error:()=>{}}};"
        )

        def route(request):
            path = urlsplit(request.request.url).path
            headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*"}
            if request.request.method == "OPTIONS":
                request.fulfill(status=204, headers=headers)
            elif path.endswith(("/api/chess/rooms", "/api/doudizhu/rooms", "/api/drawguess/rooms")):
                request.fulfill(json=[], headers=headers)
            else:
                request.fulfill(path=str(publish / path.strip("/")), headers=headers)

        context.route("**/*", route)
        page = context.new_page()
        page.goto(f"https://club.test/games/{game}/index.html?club=1#lobby")
        expect(page.locator(".lobby")).to_be_visible()
        expect(page.locator(brand)).to_be_hidden()
        page.wait_for_timeout(200)
        lobby_layout = page.evaluate("""
            header => ({
              embedded: document.documentElement.classList.contains('club-embedded'),
              bodyWidth: document.body.scrollWidth,
              bodyHeight: document.body.scrollHeight,
              headerHeight: document.querySelector(header).getBoundingClientRect().height,
              lobbyBottom: document.querySelector('.lobby').getBoundingClientRect().bottom,
            })
        """, header)
        assert lobby_layout["embedded"]
        assert lobby_layout["bodyWidth"] <= width
        assert lobby_layout["bodyHeight"] <= height
        assert lobby_layout["headerHeight"] <= 44
        assert lobby_layout["lobbyBottom"] <= height + 1

        page.evaluate("""([screen, bodyClass]) => {
          document.querySelector('.lobby').hidden = true;
          const view = document.querySelector(screen);
          view.hidden = false;
          if (bodyClass) document.body.classList.add(bodyClass);
        }""", [screen, body_class])
        primary_box = page.locator(primary).bounding_box()
        assert primary_box["height"] >= height * .72
        compact = width <= 760 or height <= 560
        if compact:
            expect(page.locator(toggle)).to_be_visible()
            if game == "doudizhu":
                toggle_box = page.locator(toggle).bounding_box()
                hand_box = page.locator("#hand").bounding_box()
                assert (
                    toggle_box["x"] + toggle_box["width"] <= hand_box["x"]
                    or hand_box["x"] + hand_box["width"] <= toggle_box["x"]
                    or toggle_box["y"] + toggle_box["height"] <= hand_box["y"]
                    or hand_box["y"] + hand_box["height"] <= toggle_box["y"]
                )
            page.locator(toggle).click()
            page.wait_for_timeout(300)
        expect(page.locator(drawer)).to_be_visible()
        if compact and game == "doudizhu":
            drawer_box = page.locator(drawer).bounding_box()
            hand_box = page.locator("#hand").bounding_box()
            assert (
                drawer_box["x"] + drawer_box["width"] <= hand_box["x"]
                or hand_box["x"] + hand_box["width"] <= drawer_box["x"]
                or drawer_box["y"] + drawer_box["height"] <= hand_box["y"]
                or hand_box["y"] + hand_box["height"] <= drawer_box["y"]
            )
        drawer_box = page.locator(drawer).bounding_box()
        assert drawer_box["x"] >= -1
        assert drawer_box["y"] >= -1
        assert drawer_box["x"] + drawer_box["width"] <= width + 1
        assert drawer_box["y"] + drawer_box["height"] <= height + 1
        assert page.evaluate("document.body.scrollWidth <= innerWidth && document.body.scrollHeight <= innerHeight")
        browser.close()
