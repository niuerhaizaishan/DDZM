"use strict";

const layerOrder = {
  "monitor-main": 20, "monitor-left": 10, "monitor-right": 10,
  "screen-light": 30, "keyboard": 40, "mouse": 40, "desk-lamp": 40,
  "handheld": 40, "pc": 40, "chair": 60,
};
const DEVICE_DISPLAY_NUMBER = Object.freeze({6: 2, 7: 3, 8: 4, 9: 5});
const DEVICE_KEYS = Object.freeze(["computer", "monitor", "keyboard", "mouse"]);
const DEVICE_NAMES = Object.freeze(["电脑", "显示器", "键盘", "鼠标"]);
function displayNumber(item) {
  return DEVICE_DISPLAY_NUMBER[item.number] || item.number;
}
function levelLabel(level) {
  const numeric = Number(level);
  if (!Number.isFinite(numeric) || numeric < 1) return "—";
  return `${Math.ceil(numeric / 2)}-${numeric % 2 ? 1 : 2}`;
}
function deviceCommand(item) {
  return `/升级 ${item.category}`;
}
const refreshButton = document.getElementById("refresh");
const statusText = document.getElementById("status");
const content = document.getElementById("workstation-content");
const token = window.location.pathname.split("/").pop();
const source = window.workstationSource;
const findButton = document.getElementById("find-colleague");
const shareButton = document.getElementById("share-image");
const shareGroup = document.getElementById("share-group");
const shareStatus = document.getElementById("share-status");
let sharing = false;
let pendingShare = null;
const lobby = document.getElementById("workstation-lobby");
const lobbyButton = document.getElementById("lobby-button");
const myButton = document.getElementById("my-workstation");
const downloadButton = document.getElementById("download-image");
const downloadDialog = document.getElementById("download-dialog");
let selectedNumber = null;
let currentWorkstation = null;
let view = source?.lobby ? "lobby" : "detail";
let loadVersion = 0;
let lobbyPage = 1;
let lobbyQuery = "";
let downloadVersion = 0;
const growthControls = document.getElementById("growth-controls");
const growthDevices = document.getElementById("growth-devices");
let currentGrowth = null;
let actionBusy = false;
let actionPending = null;
let actionDialog = null;
let actionMessage = null;
let managementPanel = null;
let sceneVersion = 0;
let sceneState = null;
let quoteVersion = 0;

function actionButton(label, action, enabled = true) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.dataset.action = action.kind;
  if (action.number) button.dataset.number = action.number;
  if (action.level) button.dataset.level = action.level;
  button.disabled = !enabled || actionBusy || !currentGrowth?.actions?.[action.kind];
  button.addEventListener('click', () => previewAction(action));
  return button;
}

function renderManagement() {
  if (!source?.quote || !growthControls) return;
  if (!managementPanel) {
    managementPanel = document.createElement('section');
    managementPanel.className = 'growth-management';
    managementPanel.setAttribute('aria-label', '工位养成进度');
    growthControls.prepend(managementPanel);
    actionMessage = document.createElement('p');
    actionMessage.id = 'action-status';
    actionMessage.setAttribute('role', 'status');
    actionMessage.setAttribute('aria-live', 'polite');
    growthControls.prepend(actionMessage);
  }
  const stage = Math.min(...currentGrowth.items.filter(i => i.number <= 5).map(i => Math.ceil(i.highest_level / 2)));
  const heading = document.createElement('h3');
  heading.textContent = `已解锁环境 ${stage} / 5`;
  const note = document.createElement('p');
  note.className = 'muted';
  note.textContent = Object.values(currentGrowth.actions || {}).some(Boolean)
    ? '四件设备全部升至本环境升级款后，才能升级到下一环境；五项基础布置随环境整体更换。'
    : currentGrowth.management_note;
  const actions = document.createElement('div');
  actions.className = 'growth-actions';
  const offer = currentGrowth.growth_offers?.advance;
  actions.append(actionButton('升级到下一环境', {kind: 'advance'}, stage < 5 && offer?.status === 'available'));
  const requirement = document.createElement('p');
  requirement.className = 'muted';
  requirement.textContent = offer?.status === 'devices_required'
    ? `需先升齐环境${offer.prerequisite_environment}升级款：${offer.missing_devices.join('、')}`
    : offer?.status === 'rank_locked' ? `需升级上限 ${levelLabel(offer.required_level)}；本次环境合计 ${offer.price} ${currentGrowth.currency_name}`
    : offer?.status === 'insufficient_balance' ? `环境升级合计 ${offer.price} ${currentGrowth.currency_name}；余额不足，还差 ${offer.shortage} ${currentGrowth.currency_name}`
    : stage === 5 ? '已到最高环境5。'
    : `环境升级合计 ${offer?.price ?? 0} ${currentGrowth.currency_name}；四件升级款已齐备，可以升级到下一环境。`;
  for (let n = 1; n <= 5; n++) {
    actions.append(actionButton(`环境 ${n}`, {kind: 'view', level: n}, n <= (currentGrowth.growth?.switchable_environment ?? stage)));
  }
  managementPanel.replaceChildren(heading, note, requirement, actions);
}

function ensureActionDialog() {
  if (actionDialog) return;
  actionDialog = document.createElement('dialog');
  actionDialog.id = 'action-dialog';
  actionDialog.setAttribute('aria-labelledby', 'action-title');
  const node = (tag, attributes, text = '') => {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
    element.textContent = text;
    return element;
  };
  const comparison = node('div', {class: 'action-comparison'});
  for (const [key, label] of [['before', '操作前'], ['after', '操作后']]) {
    const figure = node('figure', {});
    figure.append(node('figcaption', {}, label), node('img', {id: `action-${key}`, alt: `${label}的工位`, hidden: ''}),
      node('p', {id: `action-${key}-status`, class: 'muted'}, '图片加载中…'));
    comparison.append(figure);
  }
  const controls = node('div', {class: 'growth-actions'});
  controls.append(node('button', {id: 'action-cancel', class: 'secondary', type: 'button'}, '取消'),
    node('button', {id: 'action-confirm', type: 'button'}, '确认'));
  actionDialog.append(node('h2', {id: 'action-title'}, '确认工位操作'), node('p', {id: 'action-cost'}),
    comparison, node('p', {id: 'action-feedback', role: 'status', 'aria-live': 'polite'}), controls);
  document.body.append(actionDialog);
  actionDialog.querySelector('#action-cancel').addEventListener('click', () => actionDialog.close());
  actionDialog.addEventListener('cancel', event => { if (actionBusy) event.preventDefault(); });
  actionDialog.addEventListener('close', () => {
    if (!actionBusy && !actionDialog.open) { actionPending = null; quoteVersion += 1; }
  });
  actionDialog.querySelector('#action-confirm').addEventListener('click', confirmAction);
}

async function previewAction(action) {
  if (actionBusy || actionPending || !currentWorkstation || currentWorkstation.is_owner === false || selectedNumber !== null) return;
  ensureActionDialog();
  const version = ++quoteVersion;
  const pageVersion = loadVersion;
  const pending = {action, request_id: crypto.randomUUID(), revision: null};
  actionPending = pending;
  const active = () => version === quoteVersion && pageVersion === loadVersion && actionPending === pending && actionDialog.open;
  const confirm = document.getElementById('action-confirm');
  document.getElementById('action-title').textContent = '确认工位操作';
  document.getElementById('action-cost').textContent = '正在核对价格和账号状态…';
  document.getElementById('action-feedback').textContent = '报价确认后即可操作，图片会单独加载。取消不扣币。';
  confirm.disabled = true;
  confirm.textContent = '正在核价…';
  document.getElementById('action-cancel').disabled = false;
  for (const key of ['before', 'after']) {
    const image = document.getElementById(`action-${key}`);
    image.hidden = true;
    image.removeAttribute('src');
    const note = document.getElementById(`action-${key}-status`);
    note.hidden = false;
    note.textContent = key === 'after' ? '正在准备操作后预览…' : '当前画面尚未加载';
  }
  // Reuse the displayed scene; never request another full before-image.
  const before = document.getElementById('scene').querySelector('img');
  if (sceneState === currentWorkstation && before?.complete && before.naturalWidth && !before.classList.contains('equipment-layer')) {
    const image = document.getElementById('action-before');
    image.src = before.src;
    image.hidden = false;
    document.getElementById('action-before-status').hidden = true;
  }
  actionMessage.textContent = '';
  actionDialog.showModal();
  try {
    const quote = await source.quote(action);
    if (!active()) return;
    pending.revision = quote.revision;
    document.getElementById('action-title').textContent = quote.title;
    document.getElementById('action-cost').textContent = `实付 ${quote.price} ${quote.currency_name} · 操作后余额 ${quote.balance_after} ${quote.currency_name}`;
    const notes = ['确认后与群聊同步；取消不扣币。'];
    const beforeRoom = quote.before.progression.accessory_scene?.environment;
    const afterRoom = quote.after.progression.accessory_scene?.environment;
    if (beforeRoom && afterRoom && beforeRoom !== afterRoom && !['advance', 'view'].includes(action.kind)) {
      notes.push(`升级后将切回已拥有的环境${afterRoom}，仍可免费查看旧环境。`);
    }
    if (!afterRoom) notes.push('当前部件跨多个环境等级，将按混合等级布置；升级工位可补齐下一环境。');
    if (action.kind === 'advance') notes.push('升级环境后将自动获得该环境配件。');
    document.getElementById('action-feedback').textContent = notes.join(' ');
    confirm.disabled = false;
    confirm.textContent = quote.price ? `确认支付 ${quote.price} ${quote.currency_name}` : '确认免费操作';
    // Preview errors do not invalidate the independently verified quote.
    const preview = source.actionPreview
      ? source.actionPreview({action, revision: quote.revision})
      : Promise.resolve({data_url: quote.after_image});
    preview.then(async result => {
      const image = await loadImage(result.data_url, '', true);
      if (!active()) return;
      const target = document.getElementById('action-after');
      target.src = image.src;
      target.hidden = false;
      document.getElementById('action-after-status').hidden = true;
    }).catch(() => {
      if (active()) document.getElementById('action-after-status').textContent = '预览暂不可用，不影响已核对的操作。';
    });
  } catch (error) {
    if (!active()) return;
    document.getElementById('action-cost').textContent = '核价未完成，本次未扣币。';
    document.getElementById('action-feedback').textContent = error.message;
    confirm.textContent = '请关闭后重试';
    document.getElementById('action-after-status').textContent = '尚无预览';
  }
}

async function confirmAction() {
  if (actionBusy || !actionPending?.revision) return;
  actionBusy = true;
  const pageVersion = loadVersion;
  renderGrowth();
  const confirm = document.getElementById('action-confirm');
  confirm.disabled = true;
  document.getElementById('action-cancel').disabled = true;
  document.getElementById('action-feedback').textContent = '正在提交，请稍候…';
  let committed = false;
  try {
    const result = await source.apply(actionPending);
    committed = true;
    actionPending = null;
    quoteVersion += 1;
    actionDialog.close();
    if (pageVersion !== loadVersion || view !== 'detail' || selectedNumber !== null) return;
    // Invalidate older shop/image responses while retaining the usable page.
    const version = ++loadVersion;
    const [workstation, management] = result.workstation && result.management
      ? [result.workstation, result.management]
      : await Promise.all([source.load(null), source.shop()]);
    if (version !== loadVersion) return;
    showWorkstation({...currentWorkstation, ...workstation});
    setGrowth(management);
    downloadVersion += 1;
    downloadDialog?.close();
    actionMessage.textContent = `${result.title}完成 · 实付 ${result.price} ${result.currency_name} · 余额 ${management.balance} ${result.currency_name}`;
    finishLoad(version);
    refreshScene(currentWorkstation, version).catch(error => showLoadError(error, version));
  } catch (error) {
    if (committed) {
      if (view === 'detail' && selectedNumber === null) {
        actionMessage.textContent = '操作已成功，状态同步失败，请点击刷新；请勿重复购买。';
        finishLoad(loadVersion);
      }
      return;
    }
    document.getElementById('action-feedback').textContent = error.message;
    if ([401, 403, 409, 422].includes(error.status)) {
      actionPending = null;
      confirm.textContent = '请关闭后刷新';
    } else {
      // Reuse the exact receipt after a timeout, even when the server committed.
      confirm.disabled = false;
      confirm.textContent = '重试本次操作';
    }
  } finally {
    actionBusy = false;
    document.getElementById('action-cancel').disabled = false;
    renderGrowth();
  }
}

function renderGrowth() {
  if (!currentGrowth || !growthDevices) return;
  renderManagement();
  const rows = currentGrowth.items.filter(item => item.number >= 6 && item.number <= 9).map(item => {
    const row = document.createElement("article");
    row.className = "growth-device";
    const heading = document.createElement("h3");
    const environment = item.environment ?? Math.ceil(item.active_level / 2);
    heading.textContent = `${item.category} · 环境${environment}`;
    const next = document.createElement("p");
    next.textContent = item.next_level
      ? `${levelLabel(item.highest_level)} → ${levelLabel(item.next_level)} · ${item.next_name}`
      : `当前 ${levelLabel(item.active_level)}；下一次升级需先更换环境。`;
    row.append(heading, next);
    if (item.next_level) {
      const price = document.createElement("p");
      price.textContent = `升级费用 ${item.price} ${currentGrowth.currency_name}`;
      const income = document.createElement("p");
      income.className = "muted";
      income.textContent = `预计日收入 ${item.daily_income} → ${item.next_daily_income}（+${item.income_delta}）`;
      const action = document.createElement("p");
      if (item.status === "available") {
        action.append(source?.quote ? "群聊也可发送：" : "回群发送：");
        const command = document.createElement("code");
        command.textContent = deviceCommand(item);
        action.append(command);
      } else {
        action.textContent = item.status === "rank_locked" ? `需晋升至${item.required_rank}，解锁 ${levelLabel(item.next_level)}` : `余额不足，还差 ${item.shortage} ${currentGrowth.currency_name}`;
      }
      row.append(price, income, action);
      const details = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = "下一档外观说明";
      const description = document.createElement("p");
      description.textContent = item.next_description;
      details.append(summary, description);
      row.append(details);
    }
    if (source?.quote) {
      const controls = document.createElement('div');
      controls.className = 'growth-actions';
      const select = document.createElement('select');
      select.setAttribute('aria-label', `${item.category}已拥有等级`);
      const levels = item.selectable_levels ?? [environment * 2 - 1, environment * 2].filter(n => n <= item.highest_level);
      for (const level of levels) {
        const option = document.createElement('option');
        option.value = level; option.textContent = levelLabel(level);
        option.selected = level === item.active_level;
        select.append(option);
      }
      // Read the selected level only when clicked.
      const equipButton = document.createElement('button');
      equipButton.type = 'button'; equipButton.textContent = '装备';
      equipButton.disabled = actionBusy || !currentGrowth.actions?.equip;
      equipButton.addEventListener('click', () => previewAction({kind: 'equip', number: item.number, level: Number(select.value)}));
      controls.append(actionButton('升级一级', {kind: 'upgrade', number: item.number}, item.status === 'available'),
        select, equipButton, actionButton('卸下', {kind: 'remove', number: item.number}, item.equipped));
      row.append(controls);
    }
    return row;
  });
  if (!rows.length) {
    const empty = document.createElement("p");
    empty.textContent = "当前暂无可升级设备。";
    rows.push(empty);
  }
  growthDevices.replaceChildren(...rows);
}

function beginLoad(nextView) {
  sceneVersion += 1;
  quoteVersion += 1;
  if (actionDialog?.open && !actionBusy) { actionPending = null; actionDialog.close(); }
  view = nextView;
  currentWorkstation = null;
  downloadDialog?.close();
  downloadVersion += 1;
  content.hidden = true;
  if (growthControls) growthControls.hidden = true;
  currentGrowth = null;
  if (lobby) lobby.hidden = true;
  document.querySelector('main').dataset.view = view;
  if (findButton) findButton.hidden = view !== 'lobby' || !source?.lobby;
  shareStatus && (shareStatus.textContent = '');
  if (lobbyButton) lobbyButton.hidden = view === "lobby";
  const sharePanel = document.getElementById("share-panel");
  if (sharePanel) sharePanel.hidden = true;
  refreshButton.disabled = true;
  source?.setLoading?.(true);
  statusText.hidden = false;
  statusText.classList.remove("is-error");
  statusText.textContent = view === "lobby" ? "正在加载工位大厅…" : "正在加载工位…";
  return ++loadVersion;
}

function finishLoad(version) {
  if (version !== loadVersion) return;
  refreshButton.disabled = sharing;
  source?.setLoading?.(false);
}

function showLoadError(error, version) {
  if (version !== loadVersion) return;
  statusText.hidden = false;
  statusText.classList.add("is-error");
  statusText.textContent = error.name === "TimeoutError"
    ? "加载超时，请检查网络后点击刷新重试。"
    : error instanceof TypeError ? "网络连接失败，请检查网络后点击刷新重试。" : error.message;
}

async function loadLobby() {
  const version = beginLoad("lobby");
  document.getElementById("workstation-title").textContent = "工位大厅";
  document.getElementById("employee-number").hidden = true;
  document.title = "工位大厅 · 摸鱼公司";
  try {
    const result = await source.lobby({query: lobbyQuery, page: lobbyPage});
    if (version !== loadVersion) return;
    const cards = result.items.map(item => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "workstation-card";
      card.setAttribute("aria-label", `查看${item.display_name}的工位 ${item.employee_number}`);
      const name = document.createElement("h2");
      name.textContent = item.display_name;
      const number = document.createElement("p");
      number.className = "card-number";
      number.textContent = `${item.employee_number}${item.number === result.my_number ? " · 我的工位" : ""}`;
      const summary = document.createElement("p");
      summary.className = "muted";
      summary.textContent = `已装备 ${item.equipped_count} 件 · 查看工位 →`;
      const details = document.createElement("div");
      details.className = "card-details";
      details.append(name, number, summary);
      card.append(details);
      card.addEventListener("click", () => {
        selectedNumber = item.number === result.my_number ? null : item.number;
        loadWorkstation();
      });
      return card;
    });
    document.getElementById("lobby-list").replaceChildren(...cards);
    document.getElementById("lobby-summary").textContent = result.total
      ? `共 ${result.total} 位员工 · 点击工位卡片前去看看`
      : "没有找到匹配的员工，试试其他名字或工号。";
    const pages = Math.max(1, Math.ceil(result.total / result.page_size));
    document.getElementById("lobby-page").textContent = `第 ${result.page} 页 / 共 ${pages} 页`;
    document.getElementById("previous-page").disabled = result.page <= 1;
    document.getElementById("next-page").disabled = result.page >= pages;
    lobby.hidden = false;
    statusText.hidden = true;
  } catch (error) {
    showLoadError(error, version);
  } finally {
    finishLoad(version);
  }
}


function loadImage(filename, className = "", inline = false) {
  return new Promise((resolve, reject) => {
    if (inline && !/^data:image\/(png|webp);base64,/.test(filename || "")) {
      reject(new Error("工位图片生成失败，请稍后重试。"));
      return;
    }
    const image = new Image();
    image.alt = "";
    image.className = className;
    const timer = setTimeout(() => reject(new Error("工位图片加载超时，请点击刷新重试。")), filename.startsWith("growth-") ? 90000 : 20000);
    image.onload = () => { clearTimeout(timer); resolve(image); };
    image.onerror = () => { clearTimeout(timer); reject(new Error("工位图片加载失败，请点击刷新重试。")); };
    image.src = inline ? filename : `${source ? source.assetBase : "../static/workstation/"}${filename}`;
  });
}

function stage5Status(workstation) {
  const environment=workstation.progression.accessory_scene.environment;
  const canvas = document.createElement("canvas");
  canvas.width = 1536; canvas.height = 1024; canvas.className = "equipment-layer";
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "rgba(18,25,34,.81)"; ctx.strokeStyle = "rgba(234,224,205,.2)";
  ctx.beginPath(); ctx.roundRect(1114,42,380,232,14); ctx.fill(); ctx.stroke();
  ctx.textAlign = "left"; ctx.textBaseline = "top";
  ctx.font = '600 32px "Microsoft YaHei",sans-serif'; ctx.fillStyle = "#fdf7eb";
  let title = `${String(workstation.display_name).slice(0,64)}的工位`;
  if (ctx.measureText(title).width > 328) {
    while (title && ctx.measureText(title + "…").width > 328) title = title.slice(0,-1);
    title += "…";
  }
  ctx.fillText(title,1140,65);
  const environmentComponents = workstation.progression.components.filter(item => item.number <= 5);
  const environmentLevel = Math.min(...environmentComponents.map(item => item.active_level));
  ctx.font = '22px "Microsoft YaHei",sans-serif'; ctx.fillStyle = "#e9ca93"; ctx.fillText(`工位 ${levelLabel(environmentLevel)}`,1140,114);
  ctx.font = '20px "Microsoft YaHei",sans-serif'; ctx.fillStyle = "#c0c8d0";
  let environmentName = workstation.progression.environment_name || {1:"临时办公角落",2:"普通办公环境",3:"专业办公环境",4:"高端办公环境",5:"顶级专属办公室"}[environment];
  if (ctx.measureText(environmentName).width > 154) {
    while (environmentName && ctx.measureText(environmentName + "…").width > 154) environmentName = environmentName.slice(0, -1);
    environmentName += "…";
  }
  ctx.fillText(environmentName,1314,116);
  ctx.strokeStyle = "rgba(231,232,228,.18)"; ctx.beginPath(); ctx.moveTo(1140,152); ctx.lineTo(1468,152); ctx.stroke();
  for (const [i,key] of DEVICE_KEYS.entries()) {
    const state = workstation.progression.components.find(item => item.key === key);
    const x = 1140+i%2*171, y = 174+Math.floor(i/2)*42;
    ctx.font = '21px "Microsoft YaHei",sans-serif'; ctx.fillStyle = "#c0c8d0";
    ctx.fillText(DEVICE_NAMES[i],x,y);
    ctx.fillStyle = "#fdf7eb";
    if (!state.equipped) ctx.font = '19px "Microsoft YaHei",sans-serif';
    ctx.fillText(state.equipped ? levelLabel(state.active_level) : "未装备",x+106,y);
  }
  return canvas;
}

function showWorkstation(workstation) {
  const equipped = workstation.equipped;
  currentWorkstation = workstation;
  document.getElementById("scene").setAttribute("aria-label",
    `${workstation.display_name}的工位，${(workstation.progression?.components || equipped).filter(item => item.equipped !== false).map(item => item.name).join("、") || "暂无装备"}`);
  document.getElementById("workstation-title").textContent = `${workstation.display_name}的工位`;
  const employeeNumber = document.getElementById("employee-number");
  employeeNumber.textContent = workstation.employee_number ? `工号：${workstation.employee_number}` : "";
  employeeNumber.hidden = !workstation.employee_number;
  if (shareButton && typeof source?.share === "function" && workstation.is_owner !== false && selectedNumber === null) {
    document.getElementById("share-panel").hidden = false;
    const selectedGroup = shareGroup.value;
    const options = (workstation.share_groups || []).map(group => {
      const option = document.createElement("option");
      option.value = group.id;
      option.textContent = group.name || "未命名群聊";
      return option;
    });
    shareGroup.replaceChildren(...options);
    if (options.some(option => option.value === selectedGroup)) shareGroup.value = selectedGroup;
    shareGroup.disabled = sharing || !options.length;
    shareButton.disabled = sharing || !options.length;
    if (!sharing) shareStatus.textContent = options.length
      ? "按当前装备合成工位图片，每分钟可发送一次。"
      : "请先在目标群发送 /我的工位，再刷新本页（24小时内有效）。";
  }
  document.title = `${workstation.display_name}的工位 · 摸鱼公司`;
  const components = workstation.progression?.components;
  const activeComponents = components ? components.filter(item => item.equipped) : equipped;
  const environmentComponents = activeComponents.filter(item => item.number <= 5);
  const deviceComponents = activeComponents.filter(item => item.number >= 6 && item.number <= 9);
  const environmentLevel = environmentComponents.length ? Math.min(...environmentComponents.map(item => item.active_level)) : null;
  const environmentIncome = environmentComponents.reduce((sum, item) => sum + (item.daily_income || 0), 0);
  const activeItems = environmentComponents.length
    ? [{number: 1, category: '办公环境', name: '办公环境', active_level: environmentLevel,
        daily_income: environmentIncome}, ...deviceComponents]
    : deviceComponents;
  const settlementNote = document.getElementById('settlement-note');
  if (settlementNote) settlementNote.textContent = workstation.income_settlement_enabled
    ? '每日北京时间00:00自动结算，按当时已装备的环境和设备发放，每个账号每天一次。'
    : '自动结算尚未启用，目前仅展示预计收入。';
  document.getElementById("equipped-count").textContent = `${activeItems.length} 件`;
  const unit = document.createElement("span");
  unit.className = "unit";
  unit.textContent = workstation.currency_name;
  document.getElementById("income").replaceChildren(String(workstation.progression?.daily_income ?? workstation.daily_income), unit);
  const rows = activeItems.map(item => {
    const row = document.createElement("li");
    const label = document.createElement("span");
    label.textContent = `${item.category || item.name}${item.active_level ? ` ${levelLabel(item.active_level)}` : ""}`;
    const income = document.createElement("span");
    income.textContent = `+${item.daily_income}/日`;
    row.append(label, income);
    return row;
  });
  document.getElementById("equipment-list").replaceChildren(...rows);
  document.getElementById("empty").hidden = activeItems.length !== 0;
  document.getElementById("empty").textContent = workstation.is_owner === false
    ? `${workstation.display_name}还没有装备物品。`
    : "还是一个简陋工位。回群里发送 /帮助 工位，查看升级方式。";
  content.hidden = false;
}

function setGrowth(shop) {
  currentGrowth = shop;
  document.getElementById("growth-summary").textContent = `${shop.rank_name} · 升级上限 ${levelLabel(shop.level_cap)} · 余额 ${shop.balance} ${shop.currency_name}`;
  renderGrowth();
}

async function refreshScene(workstation, version) {
  const ticket = ++sceneVersion;
  const equipped = workstation.equipped;
  const expanded = workstation.progression?.accessory_scene;
  const scene = expanded || workstation.progression?.scene;
  if (workstation.progression && !scene) throw new Error("工位外观数据尚未更新，请稍后刷新重试。");
  const visible = equipped.filter(item => Object.hasOwn(layerOrder, item.asset_key))
    .sort((first, second) => layerOrder[first.asset_key] - layerOrder[second.asset_key]);
  statusText.hidden = false;
  statusText.classList.remove("is-error");
  statusText.textContent = "装备已同步，图片正在更新…";
  // Preview transfers a compact image; the download button still requests the original PNG.
  const imageSource = source?.preview || source?.image;
  const rendered = scene && imageSource
    ? await imageSource(Number(workstation.employee_number.replace("#", ""))) : null;
  if (version !== loadVersion || ticket !== sceneVersion) return;
  const images = rendered ? [await loadImage(rendered.data_url, "", true)] : scene ? await Promise.all(scene.layers.map(item => {
    const valid = expanded
      ? /^stage[1-5]-[a-f0-9]{12}-(base|computer-underlay|desk-mat|(?:computer|monitor|keyboard|mouse)-(?:basic|upgraded)|speakers|desk-clock|lightbar|console|handheld|pen-display|headphones|microphone)\.png$/.test(item.filename)
      : /^growth-[a-f0-9]{12}-(location|floor|desk|chair|plant|computer|monitor|keyboard|mouse)-lv(0[1-9]|10)\.png$/.test(item.filename);
    if (!valid) {
      throw new Error("工位图片数据异常，请刷新重试。");
    }
    return loadImage(item.filename, "equipment-layer").then(image => {
      if (image.naturalWidth !== 1536 || image.naturalHeight !== 1024) throw new Error("工位素材尺寸异常，请联系管理员。");
      return image;
    });
  })) : await Promise.all([
    loadImage("core-base.png"),
    ...visible.map(item => loadImage(`${item.asset_key}-layer.png`, "equipment-layer")),
  ]);
  if (expanded && !rendered) images.push(stage5Status(workstation));
  if (version !== loadVersion || ticket !== sceneVersion) return;
  document.getElementById("scene").replaceChildren(...images);
  sceneState = workstation;
  const sceneNote = document.querySelector(".scene-note");
  if (sceneNote) sceneNote.textContent = workstation.progression?.art_notice || "已装备的物品按图层组合展示。";
  statusText.hidden = Boolean(scene) || visible.length === equipped.length;
  statusText.textContent = "部分装备暂未提供图片，已在装备清单中列出。";
}

async function loadWorkstation() {
  const version = beginLoad("detail");
  if (shareButton) shareButton.disabled = true;
  try {
    const response = source ? null : await fetch(`../api/workstations/${encodeURIComponent(token)}`, {
      cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(20000),
    });
    if (response && !response.ok) {
      throw new Error(response.status === 404
        ? "工位链接无效或已失效，请在群里重新发送 /我的工位。"
        : "工位暂时无法加载，请稍后刷新重试。");
    }
    const workstation = source ? await source.load(selectedNumber) : await response.json();
    if (version !== loadVersion) return;
    showWorkstation(workstation);
    const placeholder = document.createElement('p');
    placeholder.className = 'scene-loading';
    placeholder.textContent = '正在加载工位图片…';
    document.getElementById('scene').replaceChildren(placeholder);
    if (growthControls && source?.shop && workstation.is_owner !== false && selectedNumber === null) {
      growthControls.hidden = false;
      document.getElementById("growth-summary").textContent = "正在同步养成状态…";
      growthDevices.replaceChildren();
      // Shop errors must not hide an otherwise usable workstation or image controls.
      source.shop().then(shop => {
        if (version !== loadVersion) return;
        setGrowth(shop);
      }).catch(error => {
        if (version === loadVersion) document.getElementById("growth-summary").textContent = `养成状态加载失败：${error.message} 点击刷新重试。`;
      });
    }
    await refreshScene(workstation, version);
  } catch (error) {
    showLoadError(error, version);
  } finally {
    finishLoad(version);
  }
}

refreshButton.addEventListener("click", () => view === "lobby" ? loadLobby() : loadWorkstation());

async function syncAccount() {
  if (!source?.quote || document.hidden || actionBusy || actionPending || view !== 'detail' || selectedNumber !== null || !currentGrowth || refreshButton.disabled) return;
  const version = loadVersion;
  try {
    const shop = await source.shop();
    if (version !== loadVersion || actionBusy || actionPending) return;
    if (shop.revision !== currentGrowth.revision) {
      await loadWorkstation();
      if (actionMessage) actionMessage.textContent = '已同步群聊或其他页面中的工位变化。';
    } else {
      const permissionsChanged = JSON.stringify(shop.actions) !== JSON.stringify(currentGrowth.actions);
      currentGrowth = shop;
      if (permissionsChanged) renderGrowth();
    }
  } catch { /* Keep the current scene usable; explicit refresh reports outages. */ }
}
if (source?.quote) {
  setInterval(syncAccount, 15000);
  window.addEventListener('focus', syncAccount);
}
lobbyButton?.addEventListener("click", loadLobby);
myButton?.addEventListener("click", () => { selectedNumber = null; loadWorkstation(); });
findButton?.addEventListener('click', () => {
  const search = document.getElementById('lobby-search');
  if (!search) return;
  search.hidden = !search.hidden;
  findButton.setAttribute('aria-expanded', String(!search.hidden));
  if (!search.hidden) document.getElementById('lobby-query').focus();
});
const helpDialog = document.getElementById('help-dialog');
document.getElementById('help-button')?.addEventListener('click', () => helpDialog.showModal());
document.getElementById('close-help')?.addEventListener('click', () => helpDialog.close());
helpDialog?.addEventListener('click', event => { if (event.target === helpDialog) {
  const bounds = helpDialog.getBoundingClientRect();
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) helpDialog.close();
}});

document.getElementById("lobby-search")?.addEventListener("submit", event => {
  event.preventDefault();
  lobbyQuery = document.getElementById("lobby-query").value.trim();
  lobbyPage = 1;
  loadLobby();
});
document.getElementById("clear-search")?.addEventListener("click", () => {
  document.getElementById("lobby-query").value = "";
  lobbyQuery = "";
  lobbyPage = 1;
  loadLobby();
});
document.getElementById("previous-page")?.addEventListener("click", () => { lobbyPage -= 1; loadLobby(); });
document.getElementById("next-page")?.addEventListener("click", () => { lobbyPage += 1; loadLobby(); });

downloadButton?.addEventListener("click", async () => {
  if (!currentWorkstation) return;
  const version = ++downloadVersion;
  const workstation = currentWorkstation;
  const downloadStatus = document.getElementById("download-status");
  const preview = document.getElementById("download-preview");
  const link = document.getElementById("download-file");
  preview.hidden = true;
  preview.removeAttribute("src");
  link.hidden = true;
  link.removeAttribute("href");
  downloadStatus.textContent = "正在合成完整工位图片…";
  downloadDialog.showModal();
  try {
    let dataUrl;
    if (source?.image) {
      const result = await source.image(Number(workstation.employee_number.replace("#", "")));
      dataUrl = result.data_url;
    } else {
      const images = [...document.querySelectorAll("#scene img, #scene canvas")];
      const canvas = document.createElement("canvas");
      canvas.width = workstation.progression?.scene?.width || images[0]?.naturalWidth || 1536;
      canvas.height = workstation.progression?.scene?.height || images[0]?.naturalHeight || 1024;
      const context = canvas.getContext("2d");
      for (const image of images) context.drawImage(image, 0, 0, canvas.width, canvas.height);
      dataUrl = canvas.toDataURL("image/png");
    }
    if (version !== downloadVersion || !downloadDialog.open) return;
    if (!dataUrl?.startsWith("data:image/png;base64,")) throw new Error("工位图片生成失败，请稍后重试。");
    preview.src = dataUrl;
    preview.hidden = false;
    link.href = dataUrl;
    link.download = `${workstation.employee_number}-${workstation.display_name}-工位.png`.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_");
    link.hidden = Boolean(source?.downloadRestricted);
    downloadStatus.textContent = source?.downloadRestricted
      ? "完整原图已生成。平台限制直接下载，请右键图片选择“图片另存为”；手机可长按图片保存。"
      : "完整原图已生成。点击下方下载 PNG 图片，也可以右键或长按图片保存。";
  } catch (error) {
    if (version === downloadVersion) downloadStatus.textContent = error.message || "生成失败，请关闭后重试。";
  }
});
document.getElementById("close-download")?.addEventListener("click", () => downloadDialog.close());
shareButton?.addEventListener("click", async () => {
  if (sharing || !shareGroup.value || !currentWorkstation || selectedNumber !== null || currentWorkstation.is_owner === false) return;
  sharing = true;
  shareButton.disabled = true;
  shareGroup.disabled = true;
  refreshButton.disabled = true;
  pendingShare ||= {group_id: shareGroup.value, request_id: crypto.randomUUID()};
  shareStatus.textContent = "正在提交工位图片…";
  try {
    const result = await source.share(pendingShare);
    if (result.status === "sent") pendingShare = null;
    shareStatus.textContent = result.status === "sent" ? "工位图片已发送到群里。" : "已加入发送队列，正在合成并发送…";
    for (let attempt = 0; attempt < 20 && result.status !== "sent"; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 2000));
      const state = await source.shareStatus(result.request_id);
      if (state.status === "sent") {
        pendingShare = null;
        shareStatus.textContent = "工位图片已发送到群里。";
        break;
      }
      if (state.status === "failed") {
        pendingShare = null;
        throw new Error("图片发送失败，请稍后重试。");
      }
      if (attempt === 19) shareStatus.textContent = "图片仍在排队，请稍后到所选群查看。";
    }
  } catch (error) {
    if (error.status && error.status < 500) pendingShare = null;
    shareStatus.textContent = error.message || "发送状态暂无法确认，请重试；同一次请求不会重复发送。";
  } finally {
    sharing = false;
    shareButton.disabled = !shareGroup.options.length;
    shareGroup.disabled = !shareGroup.options.length;
    refreshButton.disabled = false;
  }
});
shareGroup?.addEventListener("change", () => { pendingShare = null; });
if (view === "lobby") loadLobby();
else loadWorkstation();
