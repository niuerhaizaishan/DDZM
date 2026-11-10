import {ClubClient} from "./client.js";
import {CONFIG} from "./config.js";
import {createTileFace, tileLabel, tileSuit} from "./mahjong-faces.js";

const $ = selector => document.querySelector(selector);
const sdk = window.dzmm;
const client = new ClubClient({sdk, apiBase: CONFIG.apiBase});
let rooms = [], room = null, stopFollow = null, selectedTile = null, receivedAt = 0, bootReady = false;
let chatOpen = false, unreadChat = 0, seenMessageCount = 0, messagesInitialized = false;
let dismissedResult = null;
let activeClubTab = "channel", activeDirectFriend = null;
let socialVersion = null, socialRefreshTimer = null, channelRenderVersion = 0, directRenderVersion = 0;
let actionBusy = false, handGesture = null, handHoldTimer = null, ignoreTileClickUntil = 0;
let presenceTimer = null;
let activeClubModule = null, clubModuleVersion = 0, clubModuleRoom = null;
const roomSharePrefix = "MoyuClubRoom:";
const gameNames = {mahjong: "摸鱼麻将", chess: "群聊象棋", doudizhu: "斗地主", drawguess: "你画我猜", texas: "德州扑克", zhajinhua: "炸金花", blackjack: "21 点"};
const clubModules = {
  chess: {base: "./games/chess", title: "群聊象棋"},
  doudizhu: {base: "./games/doudizhu", title: "斗地主"},
  drawguess: {base: "./games/drawguess", title: "你画我猜"},
  texas: {base: "./games/card-table", title: "德州扑克"},
  zhajinhua: {base: "./games/card-table", title: "炸金花"},
  blackjack: {base: "./games/card-table", title: "21 点"},
};

const winds = ["东", "南", "西", "北"];
const phaseNames = {waiting: "候场", playing: "对局中", reaction: "鸣牌响应", hand_finished: "本局结算", match_finished: "终局", cancelled: "已取消"};
const resultNames = {tsumo: "自摸", ron: "荣和", "荒牌流局": "荒牌流局", "流局满贯": "流局满贯", "途中流局": "途中流局", match: "终局"};

function feedback(text = "", kind = "info") { const node = $("#feedback"); node.textContent = text; node.dataset.kind = kind; }
function show(selector, value = true) { $(selector).hidden = !value; }
function markReady() { if (!bootReady) { bootReady = true; sdk?.loading?.ready?.(); } }
function fullscreenElement() { return document.fullscreenElement || document.webkitFullscreenElement || null; }
function updateFullscreenButton() {
  const active = Boolean(fullscreenElement());
  $("#fullscreen").textContent = active ? "退出" : "全屏";
  $("#fullscreen").setAttribute("aria-label", active ? "退出全屏" : "进入全屏");
}
async function enterFullscreen(silent = false) {
  if (fullscreenElement()) return true;
  const root = document.documentElement;
  const request = root.requestFullscreen || root.webkitRequestFullscreen;
  if (!request) {
    if (!silent) feedback("当前浏览器不支持游戏内全屏，请使用平台顶部的全屏按钮");
    return false;
  }
  try {
    await request.call(root);
    return true;
  } catch (error) {
    if (!silent) feedback("浏览器未允许全屏，请使用平台顶部的全屏按钮");
    return false;
  }
}
async function toggleFullscreen() {
  if (!fullscreenElement()) return enterFullscreen();
  const exit = document.exitFullscreen || document.webkitExitFullscreen;
  if (exit) {
    try { await exit.call(document); } catch { feedback("无法退出全屏，请重试"); }
  }
}
async function returnToLobby() {
  if (["playing", "reaction"].includes(room?.phase) && !confirm("牌局尚未结束。返回后将由系统按倒计时自动摸切，重新进入 Club 会回到本桌。确定返回吗？")) return;
  const exit = document.exitFullscreen || document.webkitExitFullscreen;
  if (fullscreenElement() && exit) {
    try { await exit.call(document); } catch {}
  }
  await openLobby();
}
function secondsLeft() {
  if (!room?.deadline) return null;
  const server = Date.parse(room.server_time) + (Date.now() - receivedAt);
  return Math.max(0, Math.ceil((Date.parse(room.deadline) - server) / 1000));
}
function tileNode(id, small = false) {
  const tile = document.createElement("button");
  tile.type = "button"; tile.className = `tile ${small ? "small" : ""}`; tile.dataset.id = String(id); tile.dataset.suit = tileSuit(id); tile.append(createTileFace(id)); tile.setAttribute("aria-label", tileLabel(id)); tile.title = tileLabel(id);
  return tile;
}
function avatarNode(player, className = "") {
  const avatar = document.createElement("span"); avatar.className = className; avatar.textContent = player?.name?.slice(0, 1) || "?";
  if (player?.avatar_url) {
    const image = document.createElement("img"); image.src = player.avatar_url; image.alt = ""; image.loading = "lazy"; image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => image.remove(), {once: true}); avatar.append(image);
  }
  return avatar;
}
function playerButton(player, className = "") {
  const button = document.createElement("button"); button.type = "button"; button.className = `player-link ${className}`.trim(); button.setAttribute("aria-label", `查看${player?.name || "玩家"}的主页`); button.append(avatarNode(player, className ? `${className}-avatar` : ""));
  if (player?.id) button.addEventListener("click", () => openPlayerProfile(player.id));
  return button;
}
function gameCard(game) {
  const button = document.createElement("button"); button.type = "button"; button.className = "game-card";
  button.dataset.game = game.id;
  const art = document.createElement("span"); art.className = `game-art ${game.id}`; art.textContent = game.icon; art.style.backgroundImage = `url("${game.image}")`; art.setAttribute("aria-hidden", "true");
  const copy = document.createElement("div"); const name = document.createElement("strong"); name.textContent = game.name; const description = document.createElement("small"); description.textContent = game.description; copy.append(name, description);
  const arrow = document.createElement("b"); arrow.textContent = "›"; button.append(art, copy, arrow);
  if (game.path) button.addEventListener("click", () => void openClubGame(game.id));
  return button;
}
function renderGames() {
  const grid = $("#game-grid"); grid.replaceChildren();
  const mahjong = {id: "mahjong", name: "摸鱼麻将", icon: "雀", image: "./assets/game-mahjong.webp", description: "四人立直 · 休闲 / 摸鱼币"};
  const mahjongCard = gameCard(mahjong); mahjongCard.addEventListener("click", openLobby);
  grid.append(mahjongCard, ...CONFIG.games.map(gameCard));
}

function decodeRoomShare(text) {
  if (typeof text !== "string" || !text.startsWith(roomSharePrefix)) return null;
  try {
    const value = JSON.parse(text.slice(roomSharePrefix.length));
    if (!gameNames[value.game] || typeof value.roomId !== "string" || !/^[0-9a-f-]{36}$/i.test(value.roomId)) return null;
    return {game: value.game, roomId: value.roomId, host: String(value.host || "玩家").slice(0, 40)};
  } catch { return null; }
}
function roomShareText(value) { return `${roomSharePrefix}${JSON.stringify({game: value.game, roomId: value.roomId, host: value.host})}`; }
function joinSharedRoom(value) {
  closeClubDrawer();
  if (value.game === "mahjong") { void enterRoom(value.roomId, null, true); return; }
  const game = CONFIG.games.find(item => item.id === value.game); if (!game) return;
  void openClubGame(game.id, value.roomId);
}
async function hydrateRoomShare(row, share) {
  const meta = row.querySelector(".room-share-meta");
  const action = row.querySelector(".room-share-action");
  try {
    const status = await client.roomStatus(share.game, share.roomId);
    meta.textContent = `${status.label} · 人数 ${status.occupied}/${status.capacity}`;
    row.dataset.roomState = status.state;
    action.disabled = !status.enterable;
    action.textContent = status.state === "started" ? "进入观战" : status.state === "waiting" ? "进入房间" : status.label;
    if (status.enterable) action.addEventListener("click", () => joinSharedRoom({...share, game: status.game}), {once: true});
  } catch {
    meta.textContent = "状态暂不可用";
    action.textContent = "尝试进入";
    action.disabled = false;
    action.addEventListener("click", () => joinSharedRoom(share), {once: true});
  }
}
function messageRow(item, direct = false) {
  const row = document.createElement("article"); row.className = `club-message${direct && item.mine ? " mine" : ""}`;
  const player = direct ? (item.mine ? client.clubPlayer : activeDirectFriend) : item.player; const identity = document.createElement("span"); identity.className = "message-identity";
  if (player) identity.append(playerButton(player, "message")); const name = document.createElement("b"); name.textContent = direct ? (item.mine ? "我" : activeDirectFriend?.name || "好友") : item.player?.name || "玩家"; if (player) { name.role = "button"; name.tabIndex = 0; name.addEventListener("click", () => openPlayerProfile(player.id)); } identity.append(name);
  const share = direct ? null : decodeRoomShare(item.text);
  if (!share) { const text = document.createElement("p"); text.textContent = item.text; row.append(identity, text); return row; }
  row.classList.add("room-share-message"); const title = document.createElement("strong"); title.textContent = `${gameNames[share.game]} · ${share.host}的房间`;
  const meta = document.createElement("span"); meta.className = "room-share-meta"; meta.textContent = "正在读取房间状态…";
  const action = document.createElement("button"); action.type = "button"; action.className = "room-share-action"; action.textContent = "读取中"; action.disabled = true;
  row.append(identity, title, meta, action); row.roomShare = share; return row;
}
async function refreshChannelPreview() {
  try {
    const messages = await client.channel(); const latest = messages.at(-1);
    const share = latest && decodeRoomShare(latest.text);
    $("#channel-peek-text").textContent = latest ? (share ? `${latest.player.name} 分享了${gameNames[share.game]}房间` : `${latest.player.name}：${latest.text}`) : "还没有消息，来打个招呼吧";
    return messages;
  } catch (error) {
    $("#channel-peek-text").textContent = "公共频道暂时连接不上";
    return [];
  }
}
async function refreshPresence() {
  try {
    const presence = await client.presence();
    $("#club-online-count").textContent = String(presence.online);
    $("#club-playing-count").textContent = String(presence.playing);
    $("#club-presence").classList.remove("unavailable");
  } catch {
    $("#club-presence").classList.add("unavailable");
  }
}
function startPresenceHeartbeat() {
  clearInterval(presenceTimer);
  void refreshPresence();
  presenceTimer = setInterval(refreshPresence, 15000);
}
function startSocialFollowing() {
  client.followSocial(next => {
    const previous = socialVersion;
    socialVersion = next;
    const channelChanged = !previous || previous.channel !== next.channel;
    const directChanged = !previous || previous.direct !== next.direct;
    const friendsChanged = !previous || previous.friends !== next.friends;
    clearTimeout(socialRefreshTimer);
    socialRefreshTimer = setTimeout(async () => {
      const drawerOpen = !$("#club-drawer").hidden;
      try {
        if (channelChanged) {
          if (drawerOpen && activeClubTab === "channel") await renderChannel();
          else await refreshChannelPreview();
        }
        if (drawerOpen && activeClubTab === "friends") {
          if (directChanged && activeDirectFriend) await openDirect(activeDirectFriend);
          else if (friendsChanged) await renderFriends();
        }
      } catch {}
    }, 50);
  }, () => {});
}
async function renderChannel() {
  const version = ++channelRenderVersion;
  const messages = await refreshChannelPreview();
  if (version !== channelRenderVersion) return;
  const list = $("#club-channel-messages"); const rows = messages.map(item => messageRow(item)); list.replaceChildren(...rows);
  await Promise.allSettled(rows.filter(row => row.roomShare).map(row => hydrateRoomShare(row, row.roomShare)));
  if (version === channelRenderVersion) list.scrollTop = list.scrollHeight;
}
function friendCard(player, actionLabel, action) {
  const row = document.createElement("div"); row.className = "friend-card"; const avatar = avatarNode(player, "friend-avatar");
  const copy = document.createElement("div"); const name = document.createElement("b"); name.textContent = player.name; const id = document.createElement("small"); id.textContent = `ID ${player.id.slice(0, 8)}`; copy.append(name, id);
  const button = document.createElement("button"); button.type = "button"; button.className = "secondary compact"; button.textContent = actionLabel; button.addEventListener("click", action); row.append(avatar, copy, button); return row;
}
async function openDirect(player) {
  const version = ++directRenderVersion; activeDirectFriend = player; $("#direct-name").textContent = player.name; show("#direct-chat");
  const messages = await client.directMessages(player.id);
  if (version !== directRenderVersion || activeDirectFriend?.id !== player.id) return;
  const list = $("#direct-messages"); list.replaceChildren(...messages.map(item => messageRow(item, true))); list.scrollTop = list.scrollHeight;
}
async function renderFriends() {
  directRenderVersion += 1; show("#direct-chat", false); activeDirectFriend = null; const data = await client.friends(); const list = $("#friend-list"); list.replaceChildren();
  for (const item of data.incoming) list.append(friendCard(item, "接受", async () => { await client.acceptFriend(item.request_id); await renderFriends(); }));
  for (const item of data.friends) list.append(friendCard(item, "私聊", () => openDirect(item).catch(error => feedback(error.message, "error"))));
  for (const item of data.outgoing) list.append(friendCard(item, "等待接受", () => {}));
  if (!list.children.length) { const empty = document.createElement("p"); empty.className = "drawer-empty"; empty.textContent = "还没有好友，可输入玩家 ID 添加。"; list.append(empty); }
}
const taskNames = {employment: "加入公司", checkin: "完成一次打卡", random_event: "完成一次随机事件", five_rounds: "小游戏完成 5 轮", activity: "活跃彩蛋", dark_market: "上架一次暗网商品"};
async function renderTasks() {
  const tasks = await client.tasks(); const list = $("#task-list"); list.replaceChildren();
  const visible = tasks.filter(item => !item.hidden || item.eligible || item.claimed);
  for (const cadence of ["once", "daily"]) {
    const items = visible.filter(item => item.cadence === cadence);
    if (!items.length) continue;
    const section = document.createElement("section"); section.className = `task-group task-group-${cadence}`;
    const heading = document.createElement("header"); const title = document.createElement("b"); title.textContent = cadence === "once" ? "一次性任务" : "每日任务"; const note = document.createElement("small"); note.textContent = cadence === "once" ? "每个账号仅可领取一次" : "每日 00:00 刷新"; heading.append(title, note); section.append(heading);
    items.forEach(item => {
      const row = document.createElement("div"); row.className = "task-card"; const copy = document.createElement("div"); const line = document.createElement("span"); const name = document.createElement("b"); name.textContent = taskNames[item.key]; const cadenceBadge = document.createElement("em"); cadenceBadge.textContent = cadence === "once" ? "仅一次" : "每日"; line.append(name, cadenceBadge); const reward = document.createElement("small"); reward.textContent = `+${item.reward} 摸鱼币`; copy.append(line, reward);
      const button = document.createElement("button"); button.type = "button"; button.className = "primary compact"; button.textContent = item.claimed ? "已领取" : item.eligible ? "领取奖励" : "未完成"; button.disabled = item.claimed || !item.eligible;
      button.addEventListener("click", async () => { try { await client.claimTask(item.key); await renderTasks(); await renderProfile(); } catch (error) { feedback(error.message, "error"); } }); row.append(copy, button); section.append(row);
    });
    list.append(section);
  }
}
async function renderProfile(playerId = null) {
  const profile = playerId ? await client.playerProfile(playerId) : await client.profile(); const holder = $("#club-profile"); holder.replaceChildren(); const avatar = avatarNode(profile, "profile-avatar");
  const name = document.createElement("h2"); name.textContent = profile.name; const role = document.createElement("p"); role.textContent = profile.employee ? "已入职玩家" : "游客玩家";
  const id = document.createElement("code"); id.textContent = `玩家编号：${profile.id.slice(0, 8)}`;
  const balance = document.createElement("strong"); balance.className = "balance-chip"; balance.textContent = profile.employee ? `${profile.balance} 摸鱼币` : "入职后可参加摸鱼币场并领取任务";
  if (playerId && profile.relationship !== "self") {
    const actions = document.createElement("div"); actions.className = "profile-actions";
    const button = document.createElement("button"); button.type = "button"; button.className = "primary";
    if (profile.relationship === "friend") { button.textContent = "发起私聊"; button.addEventListener("click", () => { openClubDrawer("friends"); openDirect(profile).catch(error => feedback(error.message, "error")); }); }
    else if (profile.relationship === "none") { button.textContent = "添加好友"; button.addEventListener("click", async () => { try { await client.requestFriend(profile.id); await renderProfile(profile.id); } catch (error) { feedback(error.message, "error"); } }); }
    else { button.textContent = profile.relationship === "incoming" ? "待你在好友页接受" : "好友申请已发送"; button.disabled = true; }
    actions.append(button); holder.append(avatar, name, role, actions, id); return;
  }
  const stats = document.createElement("section"); stats.className = "profile-stats";
  const total = profile.stats?.total || {played: 0, wins: 0, losses: 0, draws: 0};
  const summary = document.createElement("b"); summary.textContent = `对局 ${total.played} · 胜 ${total.wins} · 负 ${total.losses} · 平 ${total.draws}`; stats.append(summary);
  const labels = {mahjong: "摸鱼麻将", chess: "群聊象棋", doudizhu: "斗地主", drawguess: "你画我猜", texas: "德州扑克", zhajinhua: "炸金花", blackjack: "21 点"};
  Object.entries(labels).forEach(([key, label]) => { const item = profile.stats?.games?.[key] || {played: 0, wins: 0, losses: 0, draws: 0}; const row = document.createElement("small"); row.textContent = `${label} · ${item.played} 局 · ${item.wins}胜 ${item.losses}负 ${item.draws}平`; stats.append(row); });
  const ledger = document.createElement("section"); ledger.className = "profile-ledger"; const ledgerTitle = document.createElement("header"); ledgerTitle.textContent = "最近摸鱼币记录"; ledger.append(ledgerTitle);
  for (const item of profile.recent_transactions || []) { const row = document.createElement("div"); const copy = document.createElement("span"); const label = document.createElement("b"); label.textContent = item.label; const at = document.createElement("small"); at.textContent = new Date(item.at).toLocaleString("zh-CN", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}); copy.append(label, at); const amount = document.createElement("strong"); amount.textContent = `${item.amount > 0 ? "+" : ""}${item.amount}`; amount.className = item.amount >= 0 ? "gain" : "loss"; row.append(copy, amount); ledger.append(row); }
  if (!(profile.recent_transactions || []).length) { const empty = document.createElement("p"); empty.textContent = "还没有摸鱼币记录"; ledger.append(empty); }
  holder.append(avatar, name, role, balance, stats, ledger, id);
}
async function openPlayerProfile(playerId) { await openClubDrawer("profile"); await renderProfile(playerId); }
async function openClubDrawer(tab = "channel") {
  activeClubTab = tab; show("#club-drawer"); show("#club-drawer-backdrop"); document.body.classList.add("drawer-open");
  document.querySelectorAll("[data-club-tab]").forEach(button => button.classList.toggle("active", button.dataset.clubTab === tab));
  document.querySelectorAll(".club-panel").forEach(panel => { panel.hidden = panel.id !== `club-panel-${tab}`; });
  $("#club-drawer-title").textContent = {channel: "公共频道", friends: "好友与私聊", tasks: "任务中心", profile: "个人中心"}[tab];
  try { if (tab === "channel") await renderChannel(); if (tab === "friends") await renderFriends(); if (tab === "tasks") await renderTasks(); if (tab === "profile") await renderProfile(); } catch (error) { feedback(error.message, "error"); }
}
function closeClubDrawer() { show("#club-drawer", false); show("#club-drawer-backdrop", false); document.body.classList.remove("drawer-open"); }

async function boot(refresh = false) {
  feedback("正在进入 Club…"); sdk?.loading?.progress?.({phase: "runtime_initializing", progress: 20, message: "正在进入摸鱼 Club"});
  try {
    await client.identity(refresh); $("#identity").textContent = "在线"; startPresenceHeartbeat(); startSocialFollowing();
    renderGames();
    await refreshChannelPreview();
    const launch = await sdk?.getLaunchParams?.().catch?.(() => null);
    const roomId = launch?.roomId ?? launch?.params?.roomId;
    if (typeof roomId === "string" && roomId) await enterRoom(roomId);
    else {
      const activeRoom = await client.activeRoom().catch(() => null);
      if (activeRoom?.game === "mahjong" && activeRoom?.room_id) {
        await enterRoom(activeRoom.room_id);
      } else if (activeRoom?.game && activeRoom?.room_id && clubModules[activeRoom.game]) {
        await openClubGame(activeRoom.game, activeRoom.room_id);
      } else openHome();
    }
    feedback(); markReady();
  } catch (error) {
    feedback(error.message || "加载失败，请重试", "error"); sdk?.loading?.error?.("CLUB_BOOT_FAILED", error.message || "加载失败");
  }
}
function stopRoom() { stopFollow?.(); stopFollow = null; room = null; selectedTile = null; dismissedResult = null; chatOpen = false; unreadChat = 0; seenMessageCount = 0; messagesInitialized = false; show("#chat-drawer", false); $("#table").classList.remove("chat-open"); updateChatBadges(); }
function moduleCss(css, base) {
  return css
    .replaceAll(":root", ":host")
    .replace(/\bhtml\b/g, ":host")
    .replace(/url\((['"]?)\.\//g, `url($1${base}/`);
}
function stopClubModule() {
  activeClubModule?.module?.unmount?.();
  activeClubModule?.host?.remove();
  activeClubModule = null;
  clubModuleRoom = null;
  $("#club-module-share").hidden = true;
  window.MoyuClubRuntime?.clearRoomContext?.();
}
async function openClubGame(game, roomId = null) {
  const config = clubModules[game];
  if (!config) return;
  const version = ++clubModuleVersion;
  stopClubModule(); stopRoom(); show("#club-home", false); show("#mahjong-lobby", false); show("#table", false); show("#club-game"); document.body.dataset.view = "subgame";
  const mount = $("#club-game-mount"); mount.replaceChildren();
  const loading = document.createElement("div"); loading.className = "club-module-loading"; loading.textContent = `正在进入${config.title}…`; mount.append(loading);
  try {
    const [htmlResponse, cssResponse] = await Promise.all([fetch(`${config.base}/index.html`), fetch(`${config.base}/style.css`)]);
    if (!htmlResponse.ok || !cssResponse.ok) throw new Error("游戏资源加载失败");
    const source = await htmlResponse.text(); const css = await cssResponse.text();
    if (version !== clubModuleVersion) return;
    const parsed = new DOMParser().parseFromString(source, "text/html"); parsed.querySelectorAll("script").forEach(node => node.remove());
    const host = document.createElement("div"); host.className = "club-module-host"; const root = host.attachShadow({mode: "open"});
    const style = document.createElement("style"); style.textContent = `:host{display:block;width:100%;height:100%;min-height:0}\n${moduleCss(css, config.base)}`;
    const body = document.createElement("body"); body.className = "club-module-body"; body.innerHTML = parsed.body.innerHTML;
    body.querySelectorAll("[src],[href]").forEach(node => {
      for (const attribute of ["src", "href"]) {
        const value = node.getAttribute(attribute); if (value?.startsWith("./")) node.setAttribute(attribute, `${config.base}/${value.slice(2)}`);
      }
    });
    root.append(style, body); mount.replaceChildren(host);
    root.querySelectorAll(".club-link").forEach(link => { link.hidden = true; link.addEventListener("click", event => { event.preventDefault(); closeClubGame(); }); });
    const duplicatePublicButton = root.querySelector("#public-channel"); if (duplicatePublicButton) duplicatePublicButton.hidden = true;
    window.CHESS_API_BASE = CONFIG.apiBase; window.DOUDIZHU_CONFIG = {apiBase: CONFIG.apiBase};
    window.MoyuClubModuleMount = {root, game, roomId, close: closeClubGame, reload: () => void openClubGame(game, roomId)};
    const module = await import(`${config.base}/game.js?mount=${version}`);
    delete window.MoyuClubModuleMount;
    if (version !== clubModuleVersion) { module.unmount?.(); host.remove(); return; }
    activeClubModule = {game, host, module};
  } catch (error) {
    delete window.MoyuClubModuleMount;
    if (version !== clubModuleVersion) return;
    loading.textContent = error.message || "游戏加载失败，请返回大厅重试"; loading.dataset.kind = "error";
  }
}
function closeClubGame() { clubModuleVersion += 1; stopClubModule(); $("#club-game-mount").replaceChildren(); show("#club-game", false); openHome(); }
function setMainNavigation(active) { document.querySelectorAll(".club-bottom-nav button").forEach(button => button.classList.toggle("active", button.id === active)); }
function openHome() { stopRoom(); show("#club-home"); show("#mahjong-lobby", false); show("#table", false); show("#club-game", false); document.body.dataset.view = "home"; setMainNavigation("home-nav"); }
async function openLobby() {
  stopRoom(); show("#club-home", false); show("#mahjong-lobby"); show("#table", false); document.body.dataset.view = "lobby"; setMainNavigation("home-nav"); feedback("正在刷新牌桌…");
  try { rooms = await client.rooms(); renderRooms(); feedback(); } catch (error) { feedback(error.message, "error"); }
}
function renderRooms() {
  $("#room-count").textContent = `${rooms.length} 桌`; const list = $("#rooms"); list.replaceChildren();
  if (!rooms.length) {
    const empty = document.createElement("div"); empty.className = "empty room-empty";
    const art = document.createElement("span"); art.className = "room-empty-art"; art.textContent = "🀄";
    const title = document.createElement("b"); title.textContent = "今晚还没有牌桌";
    const copy = document.createElement("span"); copy.textContent = "开一桌，邀请群友直接入座";
    const button = document.createElement("button"); button.type = "button"; button.className = "primary gold compact"; button.textContent = "开第一桌"; button.addEventListener("click", () => $("#create-dialog").showModal());
    empty.append(art, title, copy, button); list.append(empty); return;
  }
  for (const item of rooms) {
    const button = document.createElement("button"); button.className = "room-card"; button.type = "button";
    const icon = document.createElement("span"); icon.className = "room-icon"; icon.textContent = "🀄";
    const copy = document.createElement("div"); const title = document.createElement("strong"); title.textContent = `${item.creator_name}的牌桌`; const meta = document.createElement("small"); meta.textContent = `${item.room_type === "coin" ? `${item.stake} 币场` : "休闲场"} · ${item.match_mode === "south" ? "半庄战" : "东风战"} · ${item.occupied}/4 人${item.mine ? " · 我已入座" : ""}`; copy.append(title, meta);
    const phase = document.createElement("b"); phase.textContent = phaseNames[item.phase] || item.phase; button.append(icon, copy, phase); button.addEventListener("click", () => enterRoom(item.id, null, true)); list.append(button);
  }
}
async function createRoom() {
  feedback("正在创建牌桌…");
  const roomType = $("#room-type").value;
  const stake = roomType === "coin" ? Number($("#stake").value) : 0;
  try { const next = await client.create(roomType, stake, $("#match-mode").value); $("#create-dialog").close(); await enterRoom(next.id, next); } catch (error) { feedback(error.message, "error"); }
}
async function enterRoom(roomId, initial = null, immersive = false) {
  if (immersive) void enterFullscreen(true);
  stopFollow?.(); feedback("正在落座…");
  try {
    const next = initial || await client.snapshot(roomId);
    if (next.phase === "cancelled") { await openLobby(); return; }
    setRoom(next); show("#club-home", false); show("#mahjong-lobby", false); show("#table"); document.body.dataset.view = "table"; renderTable(); feedback();
    stopFollow = client.follow(roomId, next => { const changed = renderKey(next) !== renderKey(room); setRoom(next); if (changed) renderTable(); feedback(); }, error => feedback(`${error.message}，正在重连…`, "warning"));
  } catch (error) { feedback(error.message, "error"); }
}
function setRoom(next) { room = next; receivedAt = Date.now(); if (selectedTile !== null && !room.game?.hand?.includes(selectedTile)) selectedTile = null; }
function renderKey(value) { const messages = value?.messages || []; return JSON.stringify([value?.phase, value?.version, value?.settlement, messages.length, messages.at(-1)?.id]); }
function seatOrder() { const self = room.seat ?? 0; return {self, right: (self + 1) % 4, top: (self + 2) % 4, left: (self + 3) % 4}; }
function playerText(seat) {
  const player = room.players[seat]; if (!player) return "空位";
  const points = room.game?.points?.[seat]; return `${player.name}${seat === room.creator_seat ? " · 房主" : ""}${points === undefined ? "" : ` · ${points.toLocaleString()}`}`;
}
function renderWaiting() {
  document.body.dataset.tablePhase = "waiting";
  show("#waiting"); show("#mahjong-table", false); show("#result", false);
  $("#room-kind").textContent = `${room.room_type === "coin" ? `${room.buy_in} 摸鱼币房` : "休闲房"} · ${room.match_mode === "south" ? "半庄战" : "东风战"}`; $("#room-code").textContent = `${room.creator_name || "玩家"}的牌桌`;
  const seats = $("#seats"); seats.replaceChildren();
  room.players.forEach((player, index) => {
    const item = document.createElement("div"); item.className = `waiting-seat seat-${index} ${player ? "occupied" : ""} ${player?.ready ? "ready" : ""} ${player && !player.online ? "offline" : ""} ${room.seat === index ? "mine" : ""}`;
    const avatar = player ? avatarNode(player, "waiting-avatar") : document.createElement("span"); if (!player) { avatar.className = "waiting-avatar"; avatar.textContent = "+"; }
    const copy = document.createElement("div"); const name = document.createElement("strong"); name.textContent = player?.name || "等待入座";
    const status = document.createElement("small"); status.textContent = player ? `${index === room.creator_seat ? "房主 · " : ""}${player.ready ? "已准备" : "未准备"}${player.online ? "" : " · 离线"}` : ["东位", "南位", "西位", "北位"][index];
    copy.append(name, status); item.append(avatar, copy); seats.append(item);
  });
  show("#claim-controls", room.seat === null); show("#waiting-actions", room.seat !== null);
  if (room.seat !== null) { const mine = room.players[room.seat]; $("#ready").textContent = mine.ready ? "取消准备" : "准备"; $("#ready").dataset.action = mine.ready ? "unready" : "ready"; $("#start").hidden = room.seat !== 0; $("#start").disabled = room.players.some(player => !player?.ready); }
}
function renderPlayer(selector, seat) {
  const node = $(selector); const player = room.players[seat]; node.replaceChildren(); node.classList.toggle("active", room.game.turn === seat);
  const avatar = avatarNode(player); const copy = document.createElement("div"); const name = document.createElement("strong"); name.textContent = playerText(seat); const count = document.createElement("small"); count.textContent = `${winds[(seat - room.game.dealer + 4) % 4]}风 · ${room.game.hand_counts[seat]} 张${room.game.riichi[seat] ? " · 立直" : ""}`; copy.append(name, count); node.append(avatar, copy);
}
function renderRivers() {
  const holder = $("#rivers"); holder.replaceChildren();
  room.game.discards.forEach((river, seat) => { const line = document.createElement("div"); line.className = `river river-${seat}`; for (const item of river) { const tile = tileNode(item.tile, true); tile.classList.toggle("called", item.called); tile.classList.toggle("riichi", item.riichi); tile.disabled = true; line.append(tile); } holder.append(line); });
}
function renderMelds() {
  const holder = $("#melds"); holder.replaceChildren();
  room.game.melds.forEach((melds, seat) => { if (!melds.length) return; const group = document.createElement("div"); group.className = "meld-group"; const name = document.createElement("small"); name.textContent = room.players[seat]?.name || `玩家${seat + 1}`; group.append(name); for (const meld of melds) { const row = document.createElement("span"); row.className = "meld"; meld.tiles.forEach(id => { const tile = tileNode(id, true); tile.disabled = true; row.append(tile); }); group.append(row); } holder.append(group); });
}
function renderHand() {
  const holder = $("#hand"); holder.replaceChildren();
  if (room.seat === null) { const spectator = document.createElement("div"); spectator.className = "spectator"; spectator.textContent = "观战模式 · 手牌已隐藏"; holder.append(spectator); return; }
  const discardable = new Set(room.game.actions.discard || []);
  room.game.hand.forEach(id => { const tile = tileNode(id); tile.disabled = !discardable.has(id); tile.classList.toggle("selected", id === selectedTile); tile.addEventListener("click", () => { if (Date.now() < ignoreTileClickUntil) return; selectedTile = selectedTile === id ? null : id; for (const item of holder.querySelectorAll(".tile")) item.classList.toggle("selected", Number(item.dataset.id) === selectedTile); renderActions(); }); tile.addEventListener("dblclick", event => { event.preventDefault(); if (!discardable.has(id) || actionBusy) return; selectedTile = id; void perform("discard", {tile: id}); }); holder.append(tile); });
}
function actionButton(label, action, payload = {}, className = "secondary") { const button = document.createElement("button"); button.type = "button"; button.className = className; button.textContent = label; button.addEventListener("click", () => perform(action, payload)); return button; }
function renderActions() {
  const bar = $("#action-bar"); bar.replaceChildren(); const actions = room.game.actions || {};
  if (actions.pass) bar.append(actionButton("过", "pass", {}, "secondary pass-action"));
  if (actions.ron) bar.append(actionButton("荣和", "ron", {}, "primary gold"));
  if (actions.tsumo) bar.append(actionButton("自摸", "tsumo", {}, "primary gold"));
  for (const choice of actions.chi || []) bar.append(actionButton(`吃 ${choice.map(tileLabel).join(" ")}`, "chi", {tiles: choice}, "primary action-call"));
  for (const choice of actions.pon || []) bar.append(actionButton("碰", "pon", {tiles: choice}, "primary action-call"));
  for (const choice of actions.kan || []) bar.append(actionButton("杠", "kan", {tiles: choice}, "primary action-call"));
  for (const type of actions.ankan || []) bar.append(actionButton(`暗杠 ${tileLabel(type * 4)}`, "ankan", {tile_type: type}, "primary action-call"));
  for (const choice of actions.kakan || []) bar.append(actionButton(`加杠 ${tileLabel(choice.tile_type * 4)}`, "kakan", {meld_index: choice.meld_index}, "primary action-call"));
  if (actions.kyuushu) bar.append(actionButton("九种九牌", "kyuushu"));
  if (selectedTile !== null && (actions.discard || []).includes(selectedTile)) { if ((actions.riichi || []).includes(selectedTile)) bar.append(actionButton("立直打出", "riichi", {tile: selectedTile}, "primary gold")); bar.append(actionButton("打出", "discard", {tile: selectedTile}, "primary")); }
}
function resultCopy(result) {
  if (!result) return "结算中"; if (result.kind === "match") return `终局 · ${result.reason}`; if (result.kind === "途中流局") return result.reason; return resultNames[result.kind] || result.kind;
}
function renderResult() {
  const holder = $("#result"); holder.replaceChildren(); const resultKey = JSON.stringify([room.phase, room.version, room.game?.result, room.settlement]);
  if (!room.game?.result || !["hand_finished", "match_finished"].includes(room.phase) || dismissedResult === resultKey) { show("#result", false); return; }
  show("#result"); const heading = document.createElement("header"); const headingCopy = document.createElement("div"); const eyebrow = document.createElement("span"); eyebrow.textContent = room.phase === "match_finished" ? "MATCH RESULT" : "ROUND RESULT"; const title = document.createElement("h2"); title.textContent = resultCopy(room.game.result); const subtitle = document.createElement("small"); subtitle.textContent = room.phase === "match_finished" ? "本场最终排名" : "本局点数变化"; headingCopy.append(eyebrow, title, subtitle); const mark = document.createElement("b"); mark.textContent = room.phase === "match_finished" ? "终" : "局"; heading.append(headingCopy, mark);
  const rows = document.createElement("div"); rows.className = "result-rows";
  const lastHand = room.game.last_hand_result;
  if (lastHand?.winners?.length) {
    const evidence = document.createElement("div"); evidence.className = "winning-evidence";
    for (const seat of lastHand.winners) {
      const block = document.createElement("article"); const label = document.createElement("div"); const name = document.createElement("strong"); name.textContent = `${room.players[seat]?.name || "玩家"} · ${resultNames[lastHand.kind] || lastHand.kind}`;
      const detail = lastHand.details?.find(item => item.seat === seat); const yaku = document.createElement("small"); yaku.textContent = detail ? `${detail.yaku.join(" · ")} · ${detail.han}番${detail.fu ? ` ${detail.fu}符` : ""}${detail.limit ? ` · ${detail.limit}` : ""}` : "和牌"; label.append(name, yaku);
      const tiles = document.createElement("div"); tiles.className = "winning-tiles"; (room.game.winning_hands?.[String(seat)] || []).forEach(id => { const tile = tileNode(id, true); tile.disabled = true; tiles.append(tile); }); if (lastHand.kind === "ron" && lastHand.tile !== undefined) { const separator = document.createElement("i"); separator.textContent = "+"; tiles.append(separator); const tile = tileNode(lastHand.tile, true); tile.disabled = true; tiles.append(tile); }
      block.append(label, tiles); evidence.append(block);
    }
    holder.append(heading, evidence);
  } else holder.append(heading);
  const order = room.settlement?.order || room.game.result.order || [0, 1, 2, 3].sort((a, b) => room.game.points[b] - room.game.points[a]);
  order.forEach((seat, index) => {
    const player = room.players[seat]; const row = document.createElement("div"); row.className = index === 0 ? "winner" : "";
    const rank = document.createElement("b"); rank.textContent = String(index + 1); const avatar = avatarNode(player, "result-avatar"); const copy = document.createElement("div"); const name = document.createElement("strong"); name.textContent = player?.name || "玩家"; const note = document.createElement("small");
    if (room.room_type === "coin" && room.settlement?.payouts) { const net = (room.settlement.payouts[seat] || 0) - room.buy_in; note.textContent = `摸鱼币 ${net >= 0 ? "+" : ""}${net}`; } else note.textContent = ["东", "南", "西", "北"][seat] + "家";
    copy.append(name, note);
    const score = document.createElement("span"); const points = document.createElement("strong"); points.textContent = room.game.points[seat].toLocaleString(); const delta = room.game.result.deltas?.[seat]; const change = document.createElement("small"); change.textContent = delta === undefined ? "" : `${delta >= 0 ? "+" : ""}${delta}`; score.append(points, change); row.append(rank, avatar, copy, score); rows.append(row);
  });
  const actions = document.createElement("div"); actions.className = "result-actions";
  if (room.phase === "match_finished" && room.seat !== null) {
    const ready = room.players[room.seat]?.ready; const readyButton = document.createElement("button"); readyButton.type = "button"; readyButton.className = ready ? "secondary" : "primary gold"; readyButton.textContent = ready ? "取消准备" : "准备下一场"; readyButton.addEventListener("click", () => perform(ready ? "unready" : "ready")); actions.append(readyButton);
    const exit = document.createElement("button"); exit.type = "button"; exit.className = "secondary"; exit.textContent = "退出房间"; exit.addEventListener("click", returnToLobby); actions.append(exit);
    if (room.seat === room.creator_seat) { const readyCount = room.players.filter(player => player?.ready).length; const start = document.createElement("button"); start.type = "button"; start.className = "primary gold"; start.disabled = readyCount !== 4; start.textContent = start.disabled ? `等待准备 ${readyCount}/4` : "开始下一场"; start.addEventListener("click", () => perform("start")); actions.append(start); }
  } else { const close = document.createElement("button"); close.type = "button"; close.className = "primary gold"; close.textContent = room.phase === "match_finished" ? "返回大厅" : "继续牌局"; close.addEventListener("click", () => { dismissedResult = resultKey; show("#result", false); if (room.phase === "match_finished") void returnToLobby(); }); actions.append(close); }
  holder.append(rows, actions);
}
function renderGame() {
  document.body.dataset.tablePhase = "game";
  show("#waiting", false); show("#mahjong-table"); const order = seatOrder(); renderPlayer("#opponent-left", order.left); renderPlayer("#opponent-top", order.top); renderPlayer("#opponent-right", order.right); renderPlayer("#self-player", order.self);
  const round = `${winds[room.game.round_wind - 27] || "东"}${room.game.hand_number}局`;
  $("#round-label").textContent = `${round} · ${room.game.honba}本场`; $("#center-round").textContent = round; $("#remaining-count").textContent = `余 ${room.game.remaining} 张`; $("#turn-status").textContent = room.game.turn === room.seat ? "轮到你出牌" : `${room.players[room.game.turn]?.name || "玩家"} 思考中`;
  const dora = $("#dora"); dora.replaceChildren(document.createTextNode("宝牌指示 ")); room.game.dora_indicators.forEach(id => { const node = tileNode(id, true); node.disabled = true; dora.append(node); });
  renderRivers(); renderMelds(); renderHand(); renderActions(); renderResult();
}
function updateChatBadges() {
  for (const selector of ["#chat-unread", "#chat-preview-unread"]) { const badge = $(selector); badge.textContent = String(unreadChat); badge.hidden = unreadChat === 0; }
}
function openChat() { chatOpen = true; unreadChat = 0; $("#table").classList.add("chat-open"); show("#chat-drawer"); show("#chat-preview", false); updateChatBadges(); $("#chat-input").focus(); }
function closeChat() { chatOpen = false; $("#table").classList.remove("chat-open"); show("#chat-drawer", false); show("#chat-preview"); }
function renderMessages() {
  const entries = room.messages || [];
  if (messagesInitialized && entries.length > seenMessageCount && !chatOpen) unreadChat += entries.length - seenMessageCount;
  messagesInitialized = true; seenMessageCount = entries.length;
  const list = $("#messages"); list.replaceChildren();
  for (const item of entries) { const row = document.createElement("div"); const avatar = item.player ? playerButton(item.player, "message") : document.createElement("i"); if (!item.player) avatar.textContent = item.name?.slice(0, 1) || "?"; const copy = document.createElement("span"); const name = document.createElement("strong"); name.textContent = item.name; if (item.player) { name.role = "button"; name.tabIndex = 0; name.addEventListener("click", () => openPlayerProfile(item.player.id)); } const text = document.createElement("b"); text.textContent = item.text; copy.append(name, text); row.append(avatar, copy); list.append(row); }
  list.scrollTop = list.scrollHeight;
  const preview = $("#chat-preview-lines"); preview.replaceChildren();
  for (const item of entries.slice(-3)) { const line = document.createElement("span"); const name = document.createElement("b"); name.textContent = item.name; const text = document.createElement("i"); text.textContent = item.text; line.append(name, text); preview.append(line); }
  if (!entries.length) preview.textContent = "还没有聊天消息";
  updateChatBadges();
}
function renderTable() {
  $("#table-title").textContent = `${room.players[0]?.name || "玩家"}的牌桌`; $("#round-label").textContent = phaseNames[room.phase] || room.phase;
  if (room.phase === "waiting") renderWaiting(); else renderGame(); renderMessages(); updateTimer();
}
async function perform(action, payload = {}) {
  if (!room || actionBusy) return; feedback(); actionBusy = true; document.body.classList.add("action-busy");
  try {
    const next = await client.action(room.id, room.version, action, payload);
    if (action === "leave") { await returnToLobby(); return; }
    setRoom(next); selectedTile = null; renderTable();
  } catch (error) { feedback(error.message, "error"); } finally { actionBusy = false; document.body.classList.remove("action-busy"); }
}
async function sendChatText(text) { if (!room || !text) return; $("#chat-send").disabled = true; try { await client.chat(room.id, text); setRoom(await client.snapshot(room.id)); renderMessages(); } catch (error) { feedback(error.message, "error"); } finally { $("#chat-send").disabled = false; } }
async function sendChat() { const input = $("#chat-input"); const text = input.value.trim(); if (!text) return; input.value = ""; await sendChatText(text); }
async function shareRoom() {
  if (!room) return;
  try {
    await sdk?.share?.({title: "摸鱼麻将", description: `${room.players[0]?.name || "玩家"}的牌桌 · 点击即可入座或观战`, params: JSON.stringify({roomId: room.id})});
  } catch (error) { feedback(error.message || "分享失败，请重试", "error"); }
}
async function shareRoomToChannel(value = null) {
  const share = value || (room && {game: "mahjong", roomId: room.id, host: room.players[0]?.name || room.creator_name || "玩家"});
  if (!share) throw new Error("请先进入房间");
  await client.sendChannel(roomShareText(share));
  await openClubDrawer("channel");
}
function updateTimer() { const seconds = secondsLeft(); $("#timer").textContent = seconds === null ? "--" : `${seconds}s`; }

const customSelects = [...document.querySelectorAll(".custom-select")];
function closeCustomSelect(root, returnFocus = false) {
  const menu = root.querySelector(".custom-select-menu");
  root.classList.remove("open"); menu.hidden = true; root.querySelector(".custom-select-trigger").setAttribute("aria-expanded", "false");
  if (returnFocus) root.querySelector(".custom-select-trigger").focus();
}
function closeCustomSelects(except = null) { customSelects.forEach(root => { if (root !== except) closeCustomSelect(root); }); }
function syncCustomSelect(root) {
  const select = $(`#${root.dataset.selectFor}`); const selected = select.options[select.selectedIndex];
  root.querySelector(".custom-select-trigger>span").textContent = selected.textContent;
  root.querySelectorAll("[role=option]").forEach(option => option.setAttribute("aria-selected", String(option.dataset.value === select.value)));
}
function syncCreateEconomy() {
  const coin = $("#room-type").value === "coin"; show("#stake-field", coin); show(".prize-panel", coin);
  if (coin) { const stake = Number($("#stake").value); $("#prize-copy").textContent = `每人 ${stake} 币，共 ${stake * 4} 币；最终第一名获得奖池，同分则平分。`; }
}
function openCustomSelect(root, focusOption = false) {
  closeCustomSelects(root); const menu = root.querySelector(".custom-select-menu");
  root.classList.add("open"); menu.hidden = false; root.querySelector(".custom-select-trigger").setAttribute("aria-expanded", "true");
  if (focusOption) (menu.querySelector('[aria-selected="true"]') || menu.querySelector("[role=option]"))?.focus();
}
customSelects.forEach(root => {
  const select = $(`#${root.dataset.selectFor}`); const trigger = root.querySelector(".custom-select-trigger"); const options = [...root.querySelectorAll("[role=option]")];
  syncCustomSelect(root); select.addEventListener("change", () => syncCustomSelect(root));
  trigger.addEventListener("click", () => root.classList.contains("open") ? closeCustomSelect(root) : openCustomSelect(root));
  trigger.addEventListener("keydown", event => { if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); openCustomSelect(root, true); } });
  options.forEach(option => {
    option.addEventListener("click", () => { select.value = option.dataset.value; select.dispatchEvent(new Event("change", {bubbles: true})); closeCustomSelect(root, true); });
    option.addEventListener("keydown", event => {
      const index = options.indexOf(event.currentTarget);
      if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); options[(index + (event.key === "ArrowDown" ? 1 : -1) + options.length) % options.length].focus(); }
      if (event.key === "Escape") { event.preventDefault(); closeCustomSelect(root, true); }
    });
  });
});
document.addEventListener("pointerdown", event => { if (!event.target.closest(".custom-select")) closeCustomSelects(); });
$("#create-dialog").addEventListener("close", () => closeCustomSelects());
$("#room-type").addEventListener("change", syncCreateEconomy); $("#stake").addEventListener("change", syncCreateEconomy); syncCreateEconomy();

function clearHandGesture() { clearTimeout(handHoldTimer); handHoldTimer = null; handGesture = null; $("#hand").classList.remove("drag-armed", "drag-ready"); }
$("#hand").addEventListener("pointerdown", event => {
  const tile = event.target.closest(".tile:not(:disabled)"); if (!tile || !room?.game) return;
  handGesture = {pointerId: event.pointerId, tile: Number(tile.dataset.id), startY: event.clientY, currentY: event.clientY, armed: false};
  handHoldTimer = setTimeout(() => { if (!handGesture || handGesture.pointerId !== event.pointerId) return; handGesture.armed = true; $("#hand").classList.add("drag-armed"); }, 280);
  tile.setPointerCapture?.(event.pointerId);
});
document.addEventListener("pointermove", event => { if (!handGesture || handGesture.pointerId !== event.pointerId) return; handGesture.currentY = event.clientY; $("#hand").classList.toggle("drag-ready", handGesture.armed && handGesture.startY - event.clientY >= 44); });
document.addEventListener("pointerup", event => {
  if (!handGesture || handGesture.pointerId !== event.pointerId) return;
  const gesture = {...handGesture, currentY: event.clientY}; const play = gesture.armed && gesture.startY - gesture.currentY >= 44; clearHandGesture();
  if (play && (room?.game?.actions?.discard || []).includes(gesture.tile)) { ignoreTileClickUntil = Date.now() + 500; selectedTile = gesture.tile; event.preventDefault(); void perform("discard", {tile: gesture.tile}); }
});
document.addEventListener("pointercancel", event => { if (handGesture?.pointerId === event.pointerId) clearHandGesture(); });

$("#refresh").addEventListener("click", () => boot(true)); $("#home").addEventListener("click", openHome); $("#home-nav").addEventListener("click", openHome); $("#club-back").addEventListener("click", openHome); $("#lobby-back").addEventListener("click", returnToLobby);
$("#create-room").addEventListener("click", () => $("#create-dialog").showModal()); $("#cancel-create").addEventListener("click", () => $("#create-dialog").close()); $("#confirm-create").addEventListener("click", event => { event.preventDefault(); void enterFullscreen(true); createRoom(); });
$("#claim").addEventListener("click", () => perform("claim")); $("#ready").addEventListener("click", () => perform($("#ready").dataset.action || "ready")); $("#start").addEventListener("click", () => perform("start")); $("#leave").addEventListener("click", () => perform("leave"));
$("#share-room").addEventListener("click", shareRoom);
$("#share-room-channel").addEventListener("click", () => shareRoomToChannel().catch(error => feedback(error.message || "分享失败，请重试", "error")));
$("#fullscreen").addEventListener("click", toggleFullscreen); document.addEventListener("fullscreenchange", updateFullscreenButton); document.addEventListener("webkitfullscreenchange", updateFullscreenButton);
$("#table-channel").addEventListener("click", () => openClubDrawer("channel"));
$("#chat-channel").addEventListener("click", () => openClubDrawer("channel"));
$("#chat-toggle").addEventListener("click", openChat); $("#chat-preview").addEventListener("click", openChat); $("#chat-close").addEventListener("click", closeChat); $("#chat-send").addEventListener("click", sendChat); $("#chat-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); sendChat(); } });
document.querySelectorAll("[data-quick-chat]").forEach(button => button.addEventListener("click", () => sendChatText(button.dataset.quickChat)));
$("#channel-toggle").addEventListener("click", () => openClubDrawer("channel")); $("#channel-peek").addEventListener("click", () => openClubDrawer("channel")); $("#tasks-toggle").addEventListener("click", () => openClubDrawer("tasks")); $("#profile-toggle").addEventListener("click", () => openClubDrawer("profile"));
$("#club-drawer-close").addEventListener("click", closeClubDrawer); $("#club-drawer-backdrop").addEventListener("click", closeClubDrawer); document.querySelectorAll("[data-club-tab]").forEach(button => button.addEventListener("click", () => openClubDrawer(button.dataset.clubTab)));
$("#club-channel-send").addEventListener("click", async () => { const input = $("#club-channel-input"); const text = input.value.trim(); if (!text) return; try { await client.sendChannel(text); input.value = ""; await renderChannel(); } catch (error) { feedback(error.message, "error"); } });
$("#club-channel-input").addEventListener("keydown", event => { if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); $("#club-channel-send").click(); } });
$("#friend-add").addEventListener("click", async () => { const input = $("#friend-player-id"); try { await client.requestFriend(input.value.trim()); input.value = ""; await renderFriends(); } catch (error) { feedback(error.message, "error"); } });
$("#direct-back").addEventListener("click", () => renderFriends().catch(error => feedback(error.message, "error")));
$("#direct-send").addEventListener("click", async () => { const input = $("#direct-input"); const text = input.value.trim(); if (!activeDirectFriend || !text) return; try { await client.sendDirectMessage(activeDirectFriend.id, text); input.value = ""; await openDirect(activeDirectFriend); } catch (error) { feedback(error.message, "error"); } });
window.MoyuClubRuntime = {
  embedded: true,
  sdk,
  openChannel: () => openClubDrawer("channel"),
  openProfile: player => openPlayerProfile(player.id),
  shareRoom: shareRoomToChannel,
  setRoomContext(value) { clubModuleRoom = value; $("#club-module-share").hidden = !value; },
  clearRoomContext() { clubModuleRoom = null; $("#club-module-share").hidden = true; },
  close: closeClubGame,
};
window.MoyuClub = {closeGame: closeClubGame};
$("#club-module-home").addEventListener("click", closeClubGame);
$("#club-module-public").addEventListener("click", () => openClubDrawer("channel"));
$("#club-module-share").addEventListener("click", () => { if (clubModuleRoom) void shareRoomToChannel(clubModuleRoom); });
setInterval(updateTimer, 500); window.addEventListener("visibilitychange", () => { if (!document.hidden) void refreshPresence(); }); window.addEventListener("pagehide", () => { clearInterval(presenceTimer); clearTimeout(socialRefreshTimer); client.dispose(); }); updateFullscreenButton(); boot();
