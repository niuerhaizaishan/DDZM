// Uses the same status cards, rule editor, filters and pagination as other games.
const workstationAdmin = {tab: "overview", page: 1, query: "", settings: null, pending: new Map(), generation: 0};
const workstationAdminPath = "/api/game/workstation/";
const workstationDeviceNames = {6: "电脑", 7: "显示器", 8: "键盘", 9: "鼠标"};
const workstationLevel = (n) => `${Math.ceil(n / 2)}-${n % 2 ? 1 : 2}`;
const workstationSuper = () => identity?.role === "super_admin";
const workstationEscape = (value) => escapeHtml(String(value ?? "—"));

async function workstationWrite(resource, body, version) {
  // Retain a request ID on network failures so retrying cannot apply twice.
  const fingerprint = `${resource}:${JSON.stringify(body)}`;
  if (!workstationAdmin.pending.has(fingerprint)) workstationAdmin.pending.set(fingerprint, idempotencyKey());
  const result = await requestGame(workstationAdminPath + resource, {
    method: "POST", headers: {"Content-Type": "application/json", "Idempotency-Key": workstationAdmin.pending.get(fingerprint),
      ...(version === undefined ? {} : {"If-Match": String(version)})}, body: JSON.stringify(body),
  });
  workstationAdmin.pending.delete(fingerprint);
  return result;
}

async function workstationAttempt(operation) {
  try { await operation(); } catch (error) { setResult(`工位操作失败：${error.message}`, "error"); }
}

function workstationTable(headers, rows) {
  return `<div class="table-scroll" role="region" aria-label="工位管理列表" tabindex="0"><table class="data-table"><thead><tr>${headers.map((h) => `<th>${workstationEscape(h)}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}" class="muted">暂无记录。</td></tr>`}</tbody></table></div>`;
}

async function loadWorkstationAdmin() {
  const generation = ++workstationAdmin.generation;
  const panel = document.querySelector("#workstation-admin-panel");
  const tabs = {overview: "运行概览", players: "玩家工位", rules: "价格与收益", settlements: "结算记录", operations: "操作记录"};
  panel.innerHTML = `<div class="command-actions workstation-admin-tabs" role="tablist" aria-label="工位管理">${Object.entries(tabs).map(([key, label]) => `<button class="${key === workstationAdmin.tab ? "primary" : "secondary"}" type="button" role="tab" aria-selected="${key === workstationAdmin.tab}" data-workstation-tab="${key}">${label}</button>`).join("")}</div><div id="workstation-admin-content" aria-live="polite"><p class="muted">正在读取工位数据…</p></div>`;
  panel.querySelectorAll("[data-workstation-tab]").forEach((button) => button.addEventListener("click", () => {
    workstationAdmin.tab = button.dataset.workstationTab;
    workstationAdmin.page = 1; workstationAdmin.query = "";
    void workstationAttempt(loadWorkstationAdmin);
  }));
  const content = panel.querySelector("#workstation-admin-content");
  if (workstationAdmin.tab === "overview" || workstationAdmin.tab === "rules") {
    const [overview, settings] = await Promise.all([requestGame(workstationAdminPath + "overview"), requestGame(workstationAdminPath + "settings")]);
    if (generation !== workstationAdmin.generation) return;
    workstationAdmin.settings = settings;
    if (workstationAdmin.tab === "overview") renderWorkstationOverview(content, overview, settings);
    else renderWorkstationRules(content, settings);
  } else {
    const resource = workstationAdmin.tab === "players" ? "players" : `records/${workstationAdmin.tab}`;
    const data = await requestGame(workstationAdminPath + `${resource}?page=${workstationAdmin.page}&query=${encodeURIComponent(workstationAdmin.query)}`);
    if (generation !== workstationAdmin.generation) return;
    renderWorkstationList(content, data);
  }
}

function renderWorkstationOverview(content, overview, settings) {
  const state = settings.settlement;
  content.innerHTML = `<div class="panel-heading"><div><h2>工位运行概览</h2><p class="muted">群聊与小游戏共用工位数据。预计收入按当前装备计算；历史结算保留当日快照。</p></div>${workstationSuper() ? '<button id="edit-workstation-income-settings" class="primary" type="button">结算设置</button>' : ""}</div>
    <div class="settings-card workstation-metrics">${[
      ruleStatusCard("玩家工位", `${overview.accounts} 人`, "含尚未升级的初始工位"),
      ruleStatusCard("预计每日发放", `${overview.daily_income} 摸鱼币`, "全体玩家当前装备合计"),
      ruleStatusCard("自动结算", state.enabled ? "已开启" : "已暂停", `首次结算日期：${state.first_date || "未启用"}`),
      ruleStatusCard("今日已结算", `${overview.settled_amount} 摸鱼币`, `${overview.settled_accounts} 人 · ${overview.today}`),
    ].join("")}</div>
    <div class="panel-heading"><div><h2>已拥有环境分布</h2><p class="muted">按购买进度统计，切换旧环境不改变购买进度。</p></div></div>
    ${workstationTable(["环境", "名称", "玩家数", "环境日收益"], Object.entries(overview.environments).map(([level, count]) => `<tr><td>${level}级</td><td>${workstationEscape(settings.rules.environment_names[level - 1])}</td><td>${count}</td><td>${settings.rules.environment_income[level - 1]}</td></tr>`).join(""))}
    <p class="muted">最近结算日期：${workstationEscape(state.last_settled_on)}。结算时点、登录及对外入口沿用部署配置。</p>
    ${workstationSuper() ? '<button id="edit-workstation-settlement-settings" class="secondary" type="button">执行今日结算</button>' : '<p class="muted">结算开关和手动结算仅超级管理员可操作。</p>'}`;
  if (!workstationSuper()) return;
  const modal = mountRuleEditor("workstation-income", "工位结算", "首次启用从今天开始；暂停和重启均保留结算游标。", `<div class="event-input-grid">${birthdayFlagField("workstation-income-enabled", "启用每日自动结算", state.enabled)}<label>修改原因<input id="workstation-income-reason" maxlength="500" required></label></div>`, () => workstationAttempt(async () => {
    await runMutation(document.querySelector("#workstation-income-save"), "保存中…", async () => {
      await workstationWrite("income", {kind: "income", enabled: document.querySelector("#workstation-income-enabled").checked, revision: settings.settlement_revision, reason: document.querySelector("#workstation-income-reason").value});
      modal.remove(); await loadWorkstationAdmin(); setResult("结算设置已保存", "success");
    });
  }));
  const settlementModal = mountRuleEditor("workstation-settlement", "今日结算", "只执行今天未结算的玩家，已结算的不重复发放；不会补算历史日期。", `<p>日期：${workstationEscape(overview.today)} · 今日已结算${overview.settled_accounts}人，共${overview.settled_amount}摸鱼币。</p><p>全体当前日收益合计${overview.daily_income}摸鱼币，实际发放以未结算玩家为准。</p><label>执行原因<input id="workstation-settlement-reason" maxlength="500" required></label>`, () => workstationAttempt(async () => {
    if (!state.enabled) throw new Error("请先启用结算");
    const reason = settlementModal.querySelector("#workstation-settlement-reason").value;
    await runMutation(settlementModal.querySelector("#workstation-settlement-save"), "结算中…", async () => {
      const result = await workstationWrite("income", {kind: "settle", revision: settings.settlement_revision, reason});
      settlementModal.remove();
      await loadWorkstationAdmin(); setResult(`本次结算 ${result.result.accounts} 人，共 ${result.result.amount} 摸鱼币`, "success");
    });
  }), "执行今日结算");
}

function renderWorkstationRules(content, settings) {
  const rules = settings.rules;
  content.innerHTML = ruleOverview("workstation-rules", "工位", "设备共10档、环境共5级；环境费用按五项基础布置的设备升级价合计。保存前会计算全体日收益变化。", [
    ruleStatusCard("规则版本", settings.revision, "群聊、小游戏、结算共用"),
    ruleStatusCard("预计每日发放", `${settings.projection.daily_income} 摸鱼币`, "历史订单和结算金额保持原值"),
    ruleStatusCard("职级门槛", "沿用职位配置", "不超过职级上限，四件设备购买进度达标才可升级环境"),
  ].join("")) + `<h3>环境名称与日收益</h3>${workstationTable(["等级", "环境名称", "日收益"], rules.environment_names.map((name, i) => `<tr><td>${i + 1}级</td><td>${workstationEscape(name)}</td><td>${rules.environment_income[i]}摸鱼币</td></tr>`).join(""))}<h3>设备名称、日收益与升级费用</h3><p class="muted">四类设备按相同档位共用下表收益和升级费用；名称可分别修改。</p>${workstationTable(["档位", "电脑", "显示器", "键盘", "鼠标", "每件日收益", "升至下一档费用"], rules.tool_income.map((income, i) => `<tr><td>${workstationLevel(i + 1)}</td>${["computer", "monitor", "keyboard", "mouse"].map((key) => `<td>${workstationEscape(rules.device_names[key][i])}</td>`).join("")}<td>${income}摸鱼币</td><td>${rules.upgrade_costs[i] ?? "已满"}</td></tr>`).join(""))}`;
  content.querySelector("#edit-workstation-rules-settings").textContent = "编辑名称、收益和价格";
  let fields = `<h3>环境名称与日收益</h3><div class="event-input-grid">${rules.environment_names.map((name, i) => `<label>${i + 1}级名称<input data-wk-env-name="${i}" value="${workstationEscape(name)}" maxlength="80" required></label>${birthdayNumberField(`wk-env-income-${i}`, `${i + 1}级日收益`, rules.environment_income[i], 0, 1000000)}`).join("")}</div>
    <h3>设备日收益与升级费用（四类共用）</h3><div class="event-input-grid">${rules.tool_income.map((income, i) => birthdayNumberField(`wk-income-${i}`, `${workstationLevel(i + 1)}日收益`, income, 0, 1000000) + (i < 9 ? birthdayNumberField(`wk-cost-${i}`, `${workstationLevel(i + 1)}→${workstationLevel(i + 2)}费用`, rules.upgrade_costs[i], 1, 1000000) : "")).join("")}</div>`;
  for (const [key, names] of Object.entries(rules.device_names)) {
    const label = {computer: "电脑", monitor: "显示器", keyboard: "键盘", mouse: "鼠标"}[key];
    fields += `<details open><summary>${label}各档名称</summary><div class="event-input-grid">${names.map((name, i) => `<label>${workstationLevel(i + 1)}<input data-wk-device="${key}" data-level="${i}" value="${workstationEscape(name)}" maxlength="80" required></label>`).join("")}</div></details>`;
  }
  fields += '<label>修改原因<input id="workstation-rules-reason" maxlength="500" required></label>';
  const modal = mountRuleEditor("workstation-rules", "工位", "修改影响后续报价与结算；不会重写历史订单和结算快照。", fields, () => workstationAttempt(async () => {
    const number = (id) => Number(modal.querySelector(`#${id}`).value);
    const data = {environment_names: [...modal.querySelectorAll("[data-wk-env-name]")].map((el) => el.value),
      environment_income: Array.from({length: 5}, (_, i) => number(`wk-env-income-${i}`)),
      tool_income: Array.from({length: 10}, (_, i) => number(`wk-income-${i}`)),
      upgrade_costs: Array.from({length: 9}, (_, i) => number(`wk-cost-${i}`)), device_names: {}};
    for (const key of Object.keys(rules.device_names)) data.device_names[key] = [...modal.querySelectorAll(`[data-wk-device="${key}"]`)].map((el) => el.value);
    const body = {kind: "rules", revision: settings.revision, data, reason: modal.querySelector("#workstation-rules-reason").value};
    await runMutation(modal.querySelector("#workstation-rules-save"), "校验中…", async () => {
      const preview = await workstationWrite("settings/preview", data);
      if (preview.revision !== settings.revision) throw new Error("规则已变化，请关闭并刷新页面");
      if (!window.confirm(`全体预计日收益：${preview.before.daily_income} → ${preview.after.daily_income} 摸鱼币。确认保存？`)) return;
      configurationVersion = (await workstationWrite("settings", body, settings.version)).version;
      modal.remove(); await loadWorkstationAdmin(); setResult("工位规则已保存", "success");
    });
  }), "校验并保存规则");
}

function renderWorkstationList(content, data) {
  const players = workstationAdmin.tab === "players";
  const settlements = workstationAdmin.tab === "settlements";
  content.innerHTML = `<div class="panel-heading"><div><h2>${players ? "玩家工位" : settlements ? "每日结算记录" : "管理员操作记录"}</h2><p class="muted">${players ? "修正工位需填写原因，并在提交前核对变化。" : settlements ? "金额与设备快照为实际结算时的记录。" : "记录操作者、原因和修改前后状态。"}</p></div></div><form id="workstation-filter" class="command-actions"><label>搜索<input id="workstation-query" maxlength="64" placeholder="${players || settlements ? "姓名或工号" : "操作者或原因"}" value="${workstationEscape(workstationAdmin.query)}"></label><button class="secondary" type="submit">查询</button></form>
    ${players ? workstationTable(["工号", "姓名", "已拥有环境", "当前环境", "日收益", "操作"], data.items.map((item) => `<tr><td>${workstationEscape(item.employee_number)}</td><td>${workstationEscape(item.display_name)}</td><td>${item.highest_environment}级</td><td>${item.active_environment}级</td><td>${item.daily_income}</td><td><button class="secondary" type="button" data-workstation-player="${item.number}">查看与修正</button></td></tr>`).join("")) : workstationTable(settlements ? ["日期", "工号", "姓名", "实发收益", "快照"] : ["时间", "操作者", "操作", "原因", "变化"], data.items.map((item) => settlements ? `<tr><td>${workstationEscape(item.date)}</td><td>${item.employee_number}</td><td>${workstationEscape(item.display_name)}</td><td>${item.amount}</td><td><details><summary>查看结算设备</summary>${workstationComponents(item.components, true)}</details></td></tr>` : `<tr><td>${workstationEscape(item.created_at)}</td><td>${workstationEscape(item.actor)}</td><td>${workstationEscape({grant: "补授工位", equip: "修正装备", backfill: "补齐自动配件", rules: "规则修改", income: "结算开关", settle: "今日结算"}[item.kind] || item.kind)}</td><td>${workstationEscape(item.reason)}</td><td><details><summary>查看前后状态</summary><p>修改前</p><pre>${workstationEscape(JSON.stringify(item.before, null, 2))}</pre><p>修改后</p><pre>${workstationEscape(JSON.stringify(item.after, null, 2))}</pre></details></td></tr>`).join(""))}
    <div id="workstation-pagination" class="pagination"></div>`;
  renderPagination(content.querySelector("#workstation-pagination"), {...data, pages: Math.ceil(data.total / data.page_size)}, players ? "位玩家" : "条记录", (page) => {workstationAdmin.page = page; void workstationAttempt(loadWorkstationAdmin);});
  content.querySelector("#workstation-filter").addEventListener("submit", (event) => {event.preventDefault(); workstationAdmin.query = content.querySelector("#workstation-query").value.trim(); workstationAdmin.page = 1; void workstationAttempt(loadWorkstationAdmin);});
  content.querySelectorAll("[data-workstation-player]").forEach((button) => button.addEventListener("click", () => void workstationAttempt(() => openWorkstationPlayer(Number(button.dataset.workstationPlayer)))));
}

function workstationComponents(components, snapshot = false) {
  const environment = components.filter((c) => c.number <= 5);
  const summary = snapshot && environment.length ? `<p>环境：${Math.ceil(Math.min(...environment.map((c) => c.active_level)) / 2)}级 · 日收益：${environment.reduce((sum, c) => sum + c.daily_income, 0)}摸鱼币</p>` : "";
  return summary + workstationTable(["设备", "已拥有最高档", "当前装备", "日收益"], components.filter((c) => c.number >= 6).map((c) => `<tr><td>${workstationEscape(c.category)} ${workstationEscape(c.name)}</td><td>${workstationLevel(c.highest_level)}</td><td>${c.equipped ? workstationLevel(c.active_level) : "未装备"}</td><td>${c.daily_income}</td></tr>`).join(""));
}

async function openWorkstationPlayer(number) {
  const detail = await requestGame(workstationAdminPath + `players/${number}`);
  const ws = detail.workstation, growth = ws.progression.growth;
  const content = document.querySelector("#workstation-admin-content");
  content.querySelector("#workstation-player-detail")?.remove();
  const element = document.createElement("section"); element.id = "workstation-player-detail";
  element.innerHTML = `<div class="panel-heading"><div><h2>${workstationEscape(ws.display_name)}的工位</h2><p class="muted">已拥有环境${growth.highest_environment}级 · 当前环境${growth.active_environment ? growth.active_environment + "级" : "混合"} · 日收益${ws.daily_income}摸鱼币</p></div><button id="edit-workstation-player-settings" class="secondary" type="button">修正工位</button></div>${workstationComponents(ws.progression.components)}`;
  content.append(element); element.scrollIntoView({block: "nearest"});
  const options = (value) => Array.from({length: 10}, (_, i) => `<option value="${i + 1}"${i + 1 === value ? " selected" : ""}>${workstationLevel(i + 1)}</option>`).join("");
  const fields = `<div class="event-input-grid"><label>操作<select id="wk-player-kind"><option value="equip">调整已拥有的装备</option><option value="backfill">补齐已拥有环境的自动配件</option>${workstationSuper() ? '<option value="grant">补授环境与设备（不扣币）</option>' : ""}</select></label><label>环境<select id="wk-player-environment">${Array.from({length: 5}, (_, i) => `<option value="${i + 1}"${i + 1 === growth.active_environment ? " selected" : ""}>${i + 1}级</option>`).join("")}</select></label>${ws.progression.components.filter((c) => c.number >= 6).map((c) => `<label>${workstationDeviceNames[c.number]}<select data-wk-level="${c.number}">${options(c.active_level)}</select></label>${birthdayFlagField(`wk-equipped-${c.number}`, `装备${workstationDeviceNames[c.number]}`, c.equipped)}`).join("")}</div><label>修正原因<input id="wk-player-reason" maxlength="500" required></label>`;
  const modal = mountRuleEditor("workstation-player", "玩家工位", "补授保留更高的购买进度，不调整余额；四件设备须属于选定环境。", fields, () => workstationAttempt(async () => {
    const body = {kind: modal.querySelector("#wk-player-kind").value, environment: Number(modal.querySelector("#wk-player-environment").value), devices: {}};
    modal.querySelectorAll("[data-wk-level]").forEach((el) => {body.devices[el.dataset.wkLevel] = {level: Number(el.value), equipped: modal.querySelector(`#wk-equipped-${el.dataset.wkLevel}`).checked};});
    const reason = modal.querySelector("#wk-player-reason").value;
    await runMutation(modal.querySelector("#workstation-player-save"), "核对中…", async () => {
      const preview = await workstationWrite(`players/${number}/preview`, body);
      if (preview.revision !== detail.revision) throw new Error("工位已变化，请关闭后重新打开");
      const lines = preview.after.progression.components.filter((c) => c.number >= 6).map((c) => `${c.category}：${workstationLevel(c.active_level)}${c.equipped ? " 已装备" : " 未装备"}（最高${workstationLevel(c.highest_level)}）`);
      if (!window.confirm(`修正后：已拥有环境${preview.after.progression.growth.highest_environment}级\n${lines.join("\n")}\n日收益：${preview.before.daily_income} → ${preview.after.daily_income}\n原因：${reason}\n确认提交？`)) return;
      await workstationWrite(`players/${number}/actions`, {...body, reason, revision: preview.revision});
      modal.remove(); await loadWorkstationAdmin(); await openWorkstationPlayer(number); setResult("工位已修正，操作已记录", "success");
    });
  }), "核对并提交");
}
