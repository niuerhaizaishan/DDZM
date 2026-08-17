let token = sessionStorage.getItem("dzmm-admin-token") || "";
let adminSession = sessionStorage.getItem("dzmm-admin-session") || "";
let identity = JSON.parse(sessionStorage.getItem("dzmm-admin-identity") || "null");
let loginLease = null;
let configurationVersion = null;
let currentState = "unknown";
let currentListening = null;
let currentListeningDesired = null;
let consoleLoading = false;
let refreshLoading = false;
let gameSettings = null;
let profileSettings = null;
let activitySettings = null;
let numberBombSettings = null;
let redPacketSettings = null;
let currentGameplay = null;
let gameplayVersion = null;
let randomEventSettings = null;
let employeePage = 1;
let shopPage = 1;
let departmentPage = 1;
let promotionPage = 1;
let departmentRequestPage = 1;
let randomEventScenePage = 1;
let randomEventSubmissionPage = 1;
let randomEventSubmissionStatus = "pending";
let randomEventSceneOpeningTarget = null;
let randomEventAddScenes = [];
let hideAndSeekSettings = null;
let hideAndSeekScenePage = 1;
let memoryAssessmentSettings = null;
let undercoverSettings = null;
let blameBombSettings = null;
let blameIncidentPage = 1;
let aiAssistantSettings = null;
let aiKnowledgeCards = [];
let currentEmployeeMemory = null;
let commandDefinitions = [];
let commandPage = 1;
let administratorAccounts = [];
let administratorPage = 1;
let todayRandomEvents = [];
let todayRandomEventPage = 1;
let rankDefinitions = [];
let rankPage = 1;
let groupChats = [];
let employeeGroupMessagePage = 1;

const pageSizeOptions = [5, 10, 15, 20, 50];
const pageSizeByList = new Map();
const listFilters = new Map();
const randomEventCommandOptions = [
  ["/入职", "/入职"], ["/我的物品", "/我的物品"], ["/打卡", "/打卡"],
  ["/余额", "/余额"], ["/我", "/我（含 /me）"], ["/编辑档案", "/编辑档案"], ["/编辑档案形象", "/编辑档案形象"], ["/我的档案", "/我的档案"], ["/商店", "/商店"],
  ["/帮助", "/帮助"], ["/加入", "/加入"], ["/退出", "/退出"],
  ["/摸鱼躲猫猫", "/开始摸鱼躲藏、/躲"], ["/记忆考核", "/记忆考核"],
  ["/继续", "/继续"], ["/收手", "/收手"], ["/投降", "/投降"],
  ["/谁是卧底", "/谁是卧底"], ["/开始投票", "/开始投票"], ["/投票", "/投票"],
  ["/退出谁是卧底", "/退出谁是卧底"], ["/结束游戏", "/结束游戏"],
  ["/甩锅游戏", "/甩锅游戏"], ["/甩锅", "/甩锅"], ["/退出甩锅", "/退出甩锅"],
  ["/部门", "/部门"], ["/加入部门", "/加入部门"], ["/切换部门", "/切换部门"],
  ["/部门申请列表", "/部门申请列表"], ["/同意部门", "/同意部门"], ["/全部同意部门", "/全部同意部门"],
  ["/拒绝部门", "/拒绝部门"], ["/全部拒绝部门", "/全部拒绝部门"], ["/职位", "/职位"],
  ["/晋升", "/晋升"], ["/晋升申请列表", "/晋升申请列表"],
  ["/同意", "/同意"], ["/全部同意", "/全部同意"], ["/拒绝", "/拒绝"], ["/全部拒绝", "/全部拒绝"],
];
const pageContext = {
  overview: {crumb: "运营概览", title: "机器人运行状态", description: "查看服务、浏览器和人工登录状态。"},
  events: {crumb: "游戏运营 / 随机事件", title: "随机事件运营", description: "安排今日场次，管理场景、角色席位与剧情事件。"},
  "hide-and-seek": {crumb: "游戏运营 / 躲猫猫", title: "躲猫猫运营", description: "管理单人躲猫猫的经济规则与可用躲藏地点。"},
  "memory-assessment": {crumb: "游戏运营 / 记忆考核", title: "记忆考核运营", description: "配置单人挑战与双人对战的难度、奖池和限制。"},
  undercover: {crumb: "游戏运营 / 谁是卧底", title: "谁是卧底运营", description: "查看公开对局进度，并维护多人推理局的基础规则。"},
  "blame-bomb": {crumb: "游戏运营 / 甩锅游戏", title: "甩锅游戏运营", description: "管理事故卡、逐人数时长规则和当前公开对局。"},
  "ai-assistant": {crumb: "机器人运营 / AI 总监事", title: "AI 总监事", description: "配置群内 AI 人设、系统提示词与各职位每日调用上限。"},
  settings: {crumb: "玩法与资源 / 玩法配置", title: "玩法配置", description: "集中维护经济、打卡、全勤和日活跃度规则。"},
  commands: {crumb: "玩法与资源 / 指令库", title: "指令库", description: "配置群内指令的启用状态与标准回复模板。"},
  shop: {crumb: "玩法与资源 / 物品与商店", title: "物品与商店", description: "上架物品、维护库存，并查看当前兑换资源。"},
  organization: {crumb: "人员与系统 / 职位与部门", title: "职位与部门", description: "维护群内组织结构，以及晋升和部门申请记录。"},
  employees: {crumb: "人员与系统 / 员工", title: "员工管理", description: "查看员工资料、余额和当前群内身份。"},
  "group-chats": {crumb: "人员与系统 / 群聊管理", title: "群聊管理", description: "管理多个群的监听、玩法、随机事件和公告开关。"},
  admins: {crumb: "人员与系统 / 管理员", title: "管理员管理", description: "仅超级管理员可创建、停用或删除后台管理员账号。"},
};

function pageSizeFor(listKey) {
  return pageSizeByList.get(listKey) || 20;
}

function filterList(listKey, items, textForItem) {
  const query = (listFilters.get(listKey) || "").trim().toLocaleLowerCase();
  if (!query) return items;
  return items.filter((item) => textForItem(item).toLocaleLowerCase().includes(query));
}

function statusBadge(label, tone = "") {
  return `<span class="status-badge"${tone ? ` data-tone="${tone}"` : ""}>${escapeHtml(label)}</span>`;
}

function renderPageSizeControl(listKey, onChange) {
  const select = document.querySelector(`[data-list-page-size="${listKey}"]`);
  if (!select) return;
  select.value = String(pageSizeFor(listKey));
  if (select.dataset.boundPageSize === "true") return;
  select.dataset.boundPageSize = "true";
  select.addEventListener("change", () => {
    const next = Number(select.value);
    if (!pageSizeOptions.includes(next)) return;
    pageSizeByList.set(listKey, next);
    onChange();
  });
}

function activateManagementTab(group, paneKey) {
  const view = group.closest(".dashboard-view");
  group.querySelectorAll("[data-management-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.managementTab === paneKey);
  });
  view.querySelectorAll("[data-management-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.managementPane !== paneKey;
  });
}

function initializeManagementTabs() {
  document.querySelectorAll("[data-management-tabs]").forEach((group) => {
    group.querySelectorAll("[data-management-tab]").forEach((button) => {
      button.addEventListener("click", () => activateManagementTab(group, button.dataset.managementTab));
    });
  });
}

function renderLocalPagination(container, items, page, pageSize, unit, onPageChange) {
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.min(Math.max(page, 1), pages);
  const start = (safePage - 1) * pageSize;
  renderPagination(container, {page: safePage, page_size: pageSize, total: items.length, pages}, unit, onPageChange);
  return {items: items.slice(start, start + pageSize), page: safePage};
}

function initializePageSizeControls() {
  renderPageSizeControl("random-event-scenes", () => {
    randomEventScenePage = 1;
    void loadRandomEvents();
  });
  renderPageSizeControl("random-event-today", () => {
    todayRandomEventPage = 1;
    renderTodayRandomEvents(todayRandomEvents);
  });
  renderPageSizeControl("random-event-submissions", () => {
    randomEventSubmissionPage = 1;
    void loadRandomEventSubmissions();
  });
  renderPageSizeControl("hide-and-seek-scenes", () => {
    hideAndSeekScenePage = 1;
    void loadHideAndSeek();
  });
  renderPageSizeControl("blame-incidents", () => {
    blameIncidentPage = 1;
    void loadBlameBomb();
  });
  renderPageSizeControl("employees", () => {
    employeePage = 1;
    void loadEmployees();
  });
  renderPageSizeControl("departments", () => {
    departmentPage = 1;
    void loadOrganization();
  });
  renderPageSizeControl("promotions", () => {
    promotionPage = 1;
    void loadOrganization();
  });
  renderPageSizeControl("department-requests", () => {
    departmentRequestPage = 1;
    void loadOrganization();
  });
  renderPageSizeControl("shop", () => {
    shopPage = 1;
    void loadShop();
  });
  renderPageSizeControl("commands", () => {
    commandPage = 1;
    renderCommands(commandDefinitions);
  });
  renderPageSizeControl("admins", () => {
    administratorPage = 1;
    renderAdministrators(administratorAccounts);
  });
  renderPageSizeControl("ranks", () => {
    rankPage = 1;
    renderRanks(rankDefinitions);
  });
}

function initializeListFilters() {
  document.querySelectorAll("[data-list-filter]").forEach((input) => {
    input.addEventListener("input", () => {
      const listKey = input.dataset.listFilter;
      listFilters.set(listKey, input.value);
      if (listKey === "commands") {
        commandPage = 1;
        renderCommands(commandDefinitions);
      } else if (listKey === "admins") {
        administratorPage = 1;
        renderAdministrators(administratorAccounts);
      } else if (listKey === "random-event-today") {
        todayRandomEventPage = 1;
        renderTodayRandomEvents(todayRandomEvents);
      } else if (listKey === "random-event-scenes") {
        randomEventScenePage = 1;
        void loadRandomEvents();
      } else if (listKey === "hide-and-seek-scenes") {
        hideAndSeekScenePage = 1;
        void loadHideAndSeek();
      } else if (listKey === "blame-incidents") {
        blameIncidentPage = 1;
        void loadBlameBomb();
      } else if (listKey === "employees") {
        employeePage = 1;
        void loadEmployees();
      } else if (listKey === "departments" || listKey === "promotions" || listKey === "department-requests") {
        if (listKey === "departments") departmentPage = 1;
        if (listKey === "promotions") promotionPage = 1;
        if (listKey === "department-requests") departmentRequestPage = 1;
        void loadOrganization();
      } else if (listKey === "shop") {
        shopPage = 1;
        void loadShop();
      } else if (listKey === "ranks") {
        rankPage = 1;
        renderRanks(rankDefinitions);
      }
    });
  });
}

const loginScreen = document.querySelector("#login-screen");
const dashboard = document.querySelector("#dashboard");
const loginForm = document.querySelector("#login-form");
const accountLoginForm = document.querySelector("#account-login-form");
const loginError = document.querySelector("#login-error");
const result = document.querySelector("#result");
const notificationRegion = document.querySelector("#notification-region");
const stateElement = document.querySelector("#state");
const stateHelp = document.querySelector("#state-help");
const loginStep = document.querySelector("#login-step");
const consolePanel = document.querySelector("#login-console-panel");
const consoleFrame = document.querySelector("#login-console-frame");
const templateModal = document.querySelector("#template-modal");
const templateModalTitle = document.querySelector("#template-modal-title");
const templateModalContext = document.querySelector("#template-modal-context");
const templateModalScenario = document.querySelector("#template-modal-scenario");
const templateModalInput = document.querySelector("#template-modal-input");
const templateModalVariables = document.querySelector("#template-modal-variables");
const settingsModal = document.querySelector("#settings-modal");
const profileSettingsModal = document.querySelector("#profile-settings-modal");
const settingsCurrencyName = document.querySelector("#settings-currency-name");
const settingsOnboardingBonus = document.querySelector("#settings-onboarding-bonus");
const settingsCheckinReward = document.querySelector("#settings-checkin-reward");
const settingsWeeklyAttendanceReward = document.querySelector("#settings-weekly-attendance-reward");
const activitySettingsModal = document.querySelector("#activity-settings-modal");
const activityRuleInputs = document.querySelector("#activity-rule-inputs");
const incomeReportTimeInputs = document.querySelector("#income-report-time-inputs");
const numberBombSettingsModal = document.querySelector("#number-bomb-settings-modal");
const numberBombEnabled = document.querySelector("#number-bomb-enabled");
const numberBombSignupMinutes = document.querySelector("#number-bomb-signup-minutes");
const numberBombReminderSeconds = document.querySelector("#number-bomb-reminder-seconds");
const redPacketSettingsModal = document.querySelector("#red-packet-settings-modal");
const redPacketExpiryMinutes = document.querySelector("#red-packet-expiry-minutes");
const redPacketEmptyProbability = document.querySelector("#red-packet-empty-probability");
const forceEndCurrentGame = document.querySelector("#force-end-current-game");
const randomEventSettingsModal = document.querySelector("#random-event-settings-modal");
const randomEventSubmissionModal = document.querySelector("#random-event-submission-modal");
const randomEventSubmissionRoles = document.querySelector("#random-event-submission-roles");
const randomEventSubmissionEvents = document.querySelector("#random-event-submission-events");
const randomEventSceneModal = document.querySelector("#random-event-scene-modal");
const randomEventTimeModal = document.querySelector("#random-event-time-modal");
const randomEventAddModal = document.querySelector("#random-event-add-modal");
const randomEventDetailsModal = document.querySelector("#random-event-details-modal");
const randomEventSceneSeats = document.querySelector("#random-event-scene-seats");
const randomEventSceneOpenings = document.querySelector("#random-event-scene-openings");
const randomEventTimeInputs = document.querySelector("#random-event-time-inputs");
const hideAndSeekSettingsModal = document.querySelector("#hide-and-seek-settings-modal");
const hideAndSeekSceneModal = document.querySelector("#hide-and-seek-scene-modal");
const memoryAssessmentSettingsModal = document.querySelector("#memory-assessment-settings-modal");
const undercoverSettingsModal = document.querySelector("#undercover-settings-modal");
const blameBombSettingsModal = document.querySelector("#blame-bomb-settings-modal");
const blameIncidentModal = document.querySelector("#blame-incident-modal");
const aiAssistantSettingsModal = document.querySelector("#ai-assistant-settings-modal");
const employeeMemoryModal = document.querySelector("#employee-memory-modal");
const employeeBalanceLedgerModal = document.querySelector("#employee-balance-ledger-modal");
let employeeBalanceLedgerRequestId = 0;
const groupChatModal = document.querySelector("#group-chat-modal");
const employeeGroupMessagesModal = document.querySelector("#employee-group-messages-modal");
const employeeProfileModal = document.querySelector("#employee-profile-modal");
let employeeProfileImagePoll = null;
const aiKnowledgeCardModal = document.querySelector("#ai-knowledge-card-modal");
const rankModal = document.querySelector("#rank-modal");
const departmentModal = document.querySelector("#department-modal");

function setPageContext(view) {
  const context = pageContext[view] || pageContext.overview;
  document.querySelector("#page-breadcrumb").textContent = context.crumb;
  document.querySelector("#dashboard-title").textContent = context.title;
  document.querySelector("#page-context").textContent = context.description;
}

function headers() {
  return token ? {"X-Admin-Token": token} : {"X-Admin-Session": adminSession};
}

function setResult(message, type = "") {
  result.textContent = message;
  result.dataset.type = type;
  if (message) showNotification(message, type);
}

function showNotification(message, type = "") {
  const level = type || "info";
  const title = ({success: "操作成功", error: "操作未完成", info: "提示"})[level] || "提示";
  const notification = document.createElement("section");
  notification.className = "notification";
  notification.dataset.type = level;
  notification.innerHTML = '<span class="notification-mark" aria-hidden="true"></span><div class="notification-copy"><b></b><p></p></div><button class="notification-close" type="button" aria-label="关闭提示">×</button>';
  notification.querySelector("b").textContent = title;
  notification.querySelector("p").textContent = message;
  notification.querySelector("button").addEventListener("click", () => notification.remove());
  notificationRegion.replaceChildren(notification);
  window.setTimeout(() => notification.remove(), level === "error" ? 6500 : 3600);
}

function setAuthenticated(authenticated) {
  loginScreen.hidden = authenticated;
  dashboard.hidden = !authenticated;
  document.querySelector(".topbar-meta").hidden = !authenticated;
  document.querySelector("#nav-admins").hidden = !authenticated || identity?.role !== "super_admin";
  document.querySelector("#current-identity").textContent = authenticated ? `${identity?.username || "管理员"} · ${identity?.role === "super_admin" ? "超级管理员" : "管理员"}` : "";
  if (authenticated) setPageContext("overview");
}

function actorId() {
  return identity?.role === "super_admin" ? "super_admin" : identity?.account_id || "";
}

function configurationHeaders() {
  return configurationVersion === null ? {} : {"If-Match": String(configurationVersion)};
}

function idempotencyKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function ownsLoginLease() {
  return Boolean(loginLease && loginLease.operator_id === actorId());
}

function clearAuthentication() {
  token = "";
  adminSession = "";
  identity = null;
  loginLease = null;
  sessionStorage.removeItem("dzmm-admin-token");
  sessionStorage.removeItem("dzmm-admin-session");
  sessionStorage.removeItem("dzmm-admin-identity");
  setAuthenticated(false);
}

function formatHeartbeat(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Shanghai",
  }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", "\"": "&quot;",
  })[character]);
}

function commandLabel(command) {
  return command === "/摸鱼躲猫猫" ? "/开始摸鱼躲藏" : command;
}

function closeTemplateModal() {
  templateModal.hidden = true;
  delete templateModal.dataset.command;
  delete templateModal.dataset.templates;
}

function closeSettingsModal() {
  settingsModal.hidden = true;
}
function closeProfileSettingsModal() { profileSettingsModal.hidden = true; }
function closeEmployeeBalanceLedgerModal() {
  employeeBalanceLedgerRequestId += 1;
  employeeBalanceLedgerModal.hidden = true;
  delete employeeBalanceLedgerModal.dataset.platformId;
}
function closeEmployeeProfileModal() {
  clearTimeout(employeeProfileImagePoll);
  employeeProfileImagePoll = null;
  employeeProfileModal.hidden = true;
  delete employeeProfileModal.dataset.platformId;
}

function closeActivitySettingsModal() {
  activitySettingsModal.hidden = true;
}

function closeNumberBombSettingsModal() {
  numberBombSettingsModal.hidden = true;
}

function closeRedPacketSettingsModal() {
  redPacketSettingsModal.hidden = true;
}

function closeRandomEventSettingsModal() { randomEventSettingsModal.hidden = true; }
function closeRandomEventSceneModal() { randomEventSceneModal.hidden = true; }
function closeRandomEventTimeModal() {
  randomEventTimeModal.hidden = true;
  delete randomEventTimeModal.dataset.scheduleId;
}
function closeRandomEventAddModal() { randomEventAddModal.hidden = true; }
function closeHideAndSeekSettingsModal() { hideAndSeekSettingsModal.hidden = true; }
function closeHideAndSeekSceneModal() {
  hideAndSeekSceneModal.hidden = true;
  delete hideAndSeekSceneModal.dataset.sceneId;
  delete hideAndSeekSceneModal.dataset.enabled;
}
function closeRankModal() {
  rankModal.hidden = true;
  delete rankModal.dataset.rank;
}
function closeDepartmentModal() {
  departmentModal.hidden = true;
  delete departmentModal.dataset.department;
}

function renderSettings(settings) {
  document.querySelector("#settings-card").innerHTML = `
    <article><span>货币名称</span><strong>${escapeHtml(settings.currency_name)}</strong><small>余额、打卡和商店的计价单位</small></article>
    <article><span>入职初始余额</span><strong>${settings.onboarding_bonus}</strong><small>仅影响之后新入职的员工</small></article>
    <article><span>每日打卡奖励</span><strong>${settings.checkin_reward}</strong><small>${escapeHtml(settings.reset_time_label)} 重置</small></article>
    <article><span>每周全勤奖</span><strong>${settings.weekly_attendance_reward}</strong><small>上周全勤于周一自动入账</small></article>`;
}

function renderProfileSettings(settings) {
  document.querySelector("#profile-settings-card").innerHTML = `
    <article><span>每次编辑费用</span><strong>${settings.edit_cost}</strong><small>从编辑者个人余额扣除</small></article>
    <article><span>当前公共人力</span><strong>${settings.shared_labor}</strong><small>每次成功编辑消耗 1 点</small></article>`;
}

function renderActivitySettings(settings) {
  document.querySelector("#activity-settings-card").innerHTML = `
    <article><span>活跃等级</span><strong>LV1–LV10</strong><small>按累计有效字数结算</small></article>
    <article><span>最高每日奖励</span><strong>${settings.rules.at(-1).reward}</strong><small>达到最高等级后自动入账</small></article>
    <article><span>收益榜推送</span><strong>${settings.report_times.length} 个时段</strong><small>${escapeHtml(settings.report_times.join(" · "))}（北京时间）</small></article>`;
}

function renderNumberBombSettings(settings) {
  document.querySelector("#number-bomb-settings-card").innerHTML = `
    <article><span>游戏状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>停用只阻止创建新对局</small></article>
    <article><span>报名超时</span><strong>${settings.signup_timeout_minutes} 分钟</strong><small>未开局报名到期自动释放</small></article>
    <article><span>未报数提醒</span><strong>${settings.reminder_interval_seconds} 秒</strong><small>首次提醒后参与者可使用 /跳过</small></article>`;
}

function renderRedPacketSettings(settings) {
  document.querySelector("#red-packet-settings-card").innerHTML = `
    <article><span>红包过期</span><strong>${settings.expiry_minutes} 分钟</strong><small>到期退还尚未领取的金额</small></article>
    <article><span>空包概率</span><strong>${settings.empty_probability_percent}%</strong><small>强制空包条件不受此概率影响</small></article>`;
}

function renderCurrentGameplay(gameplay) {
  currentGameplay = gameplay;
  gameplayVersion = gameplay.version;
  const card = document.querySelector("#gameplay-current-card");
  const items = gameplay.items || [];
  if (!items.length) {
    card.innerHTML = '<p class="muted">当前没有多人游戏或随机事件占用。</p>';
    forceEndCurrentGame.hidden = true;
    return;
  }
  const names = {
    number_bomb: "蹦蹦数字炸弹", blame_bomb: "甩锅游戏", undercover: "谁是卧底",
    memory_duel: "记忆考核对战", random_event: "随机事件", conflict: "玩法状态冲突",
  };
  const states = {
    signup: "报名中", collecting: "报数中", waiting_continue: "等待继续",
    awaiting_continue: "等待继续", active: "进行中", in_progress: "进行中",
    waiting_opponent: "等待对手", tipping: "打赏中", conflict: "状态冲突",
  };
  card.innerHTML = items.map((item) => {
    const participants = item.participants.map((participant) => {
      const number = participant.number == null ? "" : `${participant.number}号 `;
      const progress = participant.reported == null ? "" : participant.reported ? "（已报数）" : "（未报数）";
      return `${number}${participant.display_name}${progress}`;
    }).join("、") || "暂无";
    const deadline = item.tipping_deadline ? `打赏截止 ${formatHeartbeat(item.tipping_deadline)}` : item.signup_deadline ? `报名截止 ${formatHeartbeat(item.signup_deadline)}` : item.next_reminder_at ? `下次提醒 ${formatHeartbeat(item.next_reminder_at)}` : "当前无倒计时";
    return `<article>
      <span>${escapeHtml(item.group_name)}</span>
      <strong>${escapeHtml(names[item.game_type] || item.game_type)}</strong>
      <small>${escapeHtml(states[item.state] || item.state || "未知状态")} · ${escapeHtml(item.game_id)}</small>
      <small>${item.participants.length} 人：${escapeHtml(participants)}</small>
      <small>${item.state === "tipping" ? `已打赏 ${item.tip_total} 摸鱼币 · ` : ""}${escapeHtml(deadline)}</small>
      <button class="danger-button" type="button" data-force-end-game data-group-chat-id="${escapeHtml(item.group_chat_id)}" data-game-type="${escapeHtml(item.game_type)}" data-game-id="${escapeHtml(item.game_id)}">强制结束</button>
    </article>`;
  }).join("");
  forceEndCurrentGame.hidden = true;
}

async function loadCurrentGameplay() {
  const gameplay = await requestGame("/api/gameplay/current");
  renderCurrentGameplay(gameplay);
  return gameplay;
}

function eventStatusLabel(status) {
  return ({pending: "待开始", signup: "报名中", in_progress: "进行中", tipping: "打赏中", ended: "已结束", dissolved: "已解散", skipped: "已跳过"})[status] || status;
}

function formatBeijingInput(value) {
  const formatter = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"});
  const parts = Object.fromEntries(formatter.formatToParts(new Date(value)).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

function renderRandomEventSettings(settings) {
  document.querySelector("#random-event-settings-card").innerHTML = `
    <article><span>每日固定场次</span><strong>${settings.schedule_times.length} 场</strong><small>${escapeHtml(settings.schedule_times.join(" · "))}（北京时间）</small></article>
    <article><span>报名补充说明</span><strong>已配置</strong><small>${escapeHtml(settings.signup_notice_template)}</small></article>
    <article><span>报名与提醒</span><strong>${settings.signup_timeout_minutes} / ${settings.reminder_interval_minutes} 分钟</strong><small>报名超时 / 未满员提醒</small></article>
    <article><span>打赏环节</span><strong>${settings.tipping_duration_seconds} 秒</strong><small>最后一名参与者退出后开始</small></article>
    <article><span>期间指令放行</span><strong>${settings.signup_allowed_commands.length} / ${settings.in_progress_allowed_commands.length}</strong><small>报名中 / 进行中</small></article>
    <article><span>玩家投稿</span><strong>${settings.submission_enabled ? "已开放" : "已关闭"}</strong><small>草稿 ${settings.submission_draft_timeout_minutes} 分钟过期 · 最多 ${settings.submission_max_participants} 人 · 通过奖励 ${settings.submission_approval_reward}</small></article>`;
}

function renderRandomEventScenes(scenes) {
  const filtered = filterList("random-event-scenes", scenes, (scene) => `${scene.name} ${scene.signup_text} ${scene.events.map((item) => item.name).join(" ")}`);
  document.querySelector("#random-event-scene-list").innerHTML = filtered.map((scene) => `
    <article class="data-row"><div><b>${escapeHtml(scene.name)}</b><small>${statusBadge(scene.enabled ? "已启用" : "已停用", scene.enabled ? "success" : "warning")}</small><small>报名公告：${escapeHtml(scene.signup_text)}</small><small>事件模板：${scene.events.length} 条</small><small>席位：${scene.seats.map((seat) => `${escapeHtml(seat.role)} × ${seat.capacity}`).join(" · ")}</small></div><div class="command-actions"><strong>${scene.target_rounds} 轮 · ${scene.reward} 奖励</strong><button class="secondary" data-random-event-scene="${escapeHtml(JSON.stringify(scene))}" data-scene-action="edit" type="button">编辑</button><button class="secondary" data-random-event-scene="${escapeHtml(JSON.stringify(scene))}" data-scene-action="toggle" type="button">${scene.enabled ? "停用" : "启用"}</button><button class="danger-button" data-random-event-scene="${escapeHtml(JSON.stringify(scene))}" data-scene-action="delete" type="button">删除</button></div></article>`).join("") || "<p class=\"muted\">没有符合条件的场景。</p>";
}

function randomEventSubmissionStatusLabel(status) {
  return ({draft: "草稿", pending: "待审核", approved: "已通过", rejected: "未通过", withdrawn: "已撤回", expired: "已过期", cancelled: "已取消"})[status] || status;
}

function formatRandomEventSubmissionNumber(number) {
  return `#${String(number).padStart(4, "0")}`;
}

function renderRandomEventSubmissions(pageData) {
  document.querySelector("#random-event-submission-list").innerHTML = pageData.items.map((submission) => `
    <article class="data-row"><div><b>${formatRandomEventSubmissionNumber(submission.number)} · ${escapeHtml(submission.content.scene_name || "未命名场景")}</b><small>${statusBadge(randomEventSubmissionStatusLabel(submission.status), submission.status === "pending" ? "warning" : submission.status === "approved" ? "success" : "")}</small><small>投稿人：${escapeHtml(submission.display_name)} ${escapeHtml(submission.employee_number)} · ${submission.content.participant_count || 0} 人 · ${submission.content.events?.length || 0} 个事件</small><small>${submission.submitted_at ? `提交于 ${formatHeartbeat(submission.submitted_at)}` : "尚未提交"}${submission.reviewer ? ` · 审核人 ${escapeHtml(submission.reviewer)}` : ""}</small></div><button class="secondary" data-random-event-submission-id="${submission.id}" type="button">${submission.status === "pending" ? "审核" : "查看"}</button></article>`).join("") || "<p class=\"muted\">当前没有符合条件的投稿。</p>";
  renderPagination(document.querySelector("#random-event-submission-pagination"), pageData, "份投稿", loadRandomEventSubmissions);
}

async function loadRandomEventSubmissions(page = randomEventSubmissionPage) {
  const pageSize = pageSizeFor("random-event-submissions");
  const submissions = await requestGame(buildRandomEventSubmissionsPath(page, pageSize, randomEventSubmissionStatus));
  randomEventSubmissionPage = submissions.page;
  renderRandomEventSubmissions(submissions);
  if (randomEventSubmissionStatus === "pending") {
    document.querySelector("#random-event-submission-pending-count").textContent = submissions.total ? `(${submissions.total})` : "";
  }
}

function renderHideAndSeekSettings(settings) {
  document.querySelector("#hide-and-seek-settings-card").innerHTML = `
    <article><span>游戏状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>停用后玩家无法发起新游戏</small></article>
    <article><span>每局经济</span><strong>${settings.entry_fee} / ${settings.win_reward}</strong><small>被发现扣除 / 胜利奖励</small></article>
    <article><span>每日限制</span><strong>${settings.daily_limit} 次</strong><small>选择超时 ${settings.selection_timeout_minutes} 分钟</small></article>`;
}

function renderHideAndSeekScenes(scenes) {
  const filtered = filterList("hide-and-seek-scenes", scenes, (scene) => scene.name);
  document.querySelector("#hide-and-seek-scene-list").innerHTML = filtered.map((scene) => `
    <article class="data-row"><div><b>${escapeHtml(scene.name)}</b><small>${statusBadge(scene.enabled ? "已启用" : "已停用", scene.enabled ? "success" : "warning")}</small><small>${scene.enabled ? "可被随机抽取为躲藏地点" : "不会进入新的躲猫猫游戏"}</small></div>
    <div class="command-actions"><button class="secondary" data-hide-and-seek-scene="${escapeHtml(JSON.stringify(scene))}" data-hide-and-seek-scene-action="edit" type="button">编辑</button><button class="secondary" data-hide-and-seek-scene="${escapeHtml(JSON.stringify(scene))}" data-hide-and-seek-scene-action="toggle" type="button">${scene.enabled ? "停用" : "启用"}</button><button class="danger-button" data-hide-and-seek-scene="${escapeHtml(JSON.stringify(scene))}" data-hide-and-seek-scene-action="delete" type="button">删除</button></div></article>`).join("") || "<p class=\"muted\">还没有地点。至少新增并启用 7 个地点后，玩家才能开始游戏。</p>";
}

function renderMemoryAssessmentSettings(settings) {
  document.querySelector("#memory-assessment-settings-card").innerHTML = `
    <article><span>游戏状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>考题展示后自动撤回</small></article>
    <article><span>单人挑战</span><strong>每日 ${settings.single_daily_limit} 次 / ${settings.single_recall_seconds} 秒</strong><small>${settings.levels.map((rule) => `LV${rule.level}: ${rule.answer_length} 字符 / ${rule.reward} 奖励`).join(" · ")}</small></article>
    <article><span>双人对战</span><strong>基础奖池 ${settings.duel_base_pool} / 答错冻结 ${settings.duel_wrong_freeze}</strong><small>难度 LV${settings.duel_difficulty_level}，${settings.duel_answer_timeout_minutes} 分钟超时，答错上限 ${settings.duel_wrong_limit} 次</small></article>`;
  const duelSummary = document.querySelector("[data-memory-assessment-duel-summary]");
  if (duelSummary) {
    duelSummary.innerHTML = `
      <article><span>基础奖池</span><strong>${settings.duel_base_pool}</strong><small>创建双人局时投入</small></article>
      <article><span>题目展示</span><strong>${settings.duel_recall_seconds} 秒</strong><small>展示后自动撤回</small></article>
      <article><span>错误限制</span><strong>${settings.duel_wrong_limit} 次</strong><small>每次冻结 ${settings.duel_wrong_freeze}</small></article>`;
  }
}

async function loadMemoryAssessment() {
  memoryAssessmentSettings = await requestGame("/api/game/memory-assessment/settings");
  configurationVersion = memoryAssessmentSettings.version;
  renderMemoryAssessmentSettings(memoryAssessmentSettings);
}

async function openMemoryAssessmentSettingsModal() {
  const settings = memoryAssessmentSettings || await requestGame("/api/game/memory-assessment/settings");
  memoryAssessmentSettings = settings;
  document.querySelector("#memory-assessment-enabled").checked = settings.enabled;
  document.querySelector("#memory-assessment-daily-limit").value = settings.single_daily_limit;
  document.querySelector("#memory-assessment-single-seconds").value = settings.single_recall_seconds;
  document.querySelector("#memory-assessment-duel-seconds").value = settings.duel_recall_seconds;
  document.querySelector("#memory-assessment-duel-level").value = settings.duel_difficulty_level;
  document.querySelector("#memory-assessment-base-pool").value = settings.duel_base_pool;
  document.querySelector("#memory-assessment-wrong-freeze").value = settings.duel_wrong_freeze;
  document.querySelector("#memory-assessment-wrong-limit").value = settings.duel_wrong_limit;
  document.querySelector("#memory-assessment-signup-timeout").value = settings.duel_signup_timeout_minutes;
  document.querySelector("#memory-assessment-timeout").value = settings.duel_answer_timeout_minutes;
  document.querySelector("#memory-assessment-character-set").value = settings.character_set;
  document.querySelector("#memory-assessment-levels").value = settings.levels.map((rule) => `${rule.answer_length},${rule.reward}`).join("\n");
  memoryAssessmentSettingsModal.hidden = false;
}

function closeMemoryAssessmentSettingsModal() { memoryAssessmentSettingsModal.hidden = true; }
function closeUndercoverSettingsModal() { undercoverSettingsModal.hidden = true; }
function closeAiAssistantSettingsModal() { aiAssistantSettingsModal.hidden = true; }
function closeEmployeeMemoryModal() { employeeMemoryModal.hidden = true; }

function renderAiAssistantSettings(settings) {
  document.querySelector("#ai-assistant-settings-card").innerHTML = `
    <article><span>调用状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>仅响应 @总监事 内容</small></article>
    <article><span>每日调用上限</span><strong>${settings.quotas.length} 个职位</strong><small>北京时间 00:00 自动重置</small></article>
    <article><span>回复限制</span><strong>${settings.max_response_chars} 字 / ${settings.timeout_seconds} 秒</strong><small>失败与超限回复均可配置</small></article>
    <article><span>玩家印象</span><strong>${settings.memory_enabled ? "自动提炼" : "已停用"}</strong><small>每 ${settings.batch_message_threshold} 条有效普通消息更新；每类最多 ${settings.max_entries_per_category} 条</small></article>`;
}

function renderAiKnowledgeCards() {
  const topicLabels = {
    economy: "金币与余额", departments: "部门", ranks: "职位与晋升", shop: "商店与物品",
    checkin_activity: "打卡与活跃度", random_events: "随机事件", hide_and_seek: "摸鱼躲猫猫",
    memory_assessment: "记忆考核", undercover: "谁是卧底", blame_bomb: "甩锅游戏", number_bomb: "蹦蹦数字炸弹",
    commands_help: "指令帮助", player_activity: "个人游戏经历",
  };
  document.querySelector("#ai-knowledge-card-list").innerHTML = aiKnowledgeCards.length
    ? aiKnowledgeCards.map((card) => `<article class="data-row" data-ai-knowledge-card-id="${escapeHtml(card.id)}"><div><b>${escapeHtml(card.title)}</b><small>${escapeHtml(topicLabels[card.topic] || card.topic)} · 优先级 ${card.priority} · ${card.enabled ? "已启用" : "已停用"}</small><small>${card.keywords.map(escapeHtml).join("、")}</small></div><div class="command-actions"><button class="secondary" data-edit-ai-knowledge-card type="button">编辑</button><button class="secondary" data-toggle-ai-knowledge-card type="button">${card.enabled ? "停用" : "启用"}</button><button class="danger-button" data-delete-ai-knowledge-card type="button">删除</button></div></article>`).join("")
    : '<p class="muted">暂无玩法知识卡。</p>';
}

async function loadAiAssistant() {
  const [settings, knowledge] = await Promise.all([
    requestGame("/api/ai-assistant/settings"),
    requestGame("/api/ai-knowledge-cards"),
  ]);
  aiAssistantSettings = settings;
  aiKnowledgeCards = knowledge.items;
  configurationVersion = Math.max(settings.version, knowledge.version);
  renderAiAssistantSettings(aiAssistantSettings);
  renderAiKnowledgeCards();
}

function openAiKnowledgeCardModal(card = null) {
  aiKnowledgeCardModal.dataset.cardId = card?.id || "";
  document.querySelector("#ai-knowledge-card-modal-title").textContent = card ? "编辑知识卡" : "新增知识卡";
  document.querySelector("#ai-knowledge-card-topic").value = card?.topic || "economy";
  document.querySelector("#ai-knowledge-card-title").value = card?.title || "";
  document.querySelector("#ai-knowledge-card-keywords").value = card?.keywords.join("\n") || "";
  document.querySelector("#ai-knowledge-card-content").value = card?.content || "";
  document.querySelector("#ai-knowledge-card-priority").value = card?.priority ?? 100;
  document.querySelector("#ai-knowledge-card-enabled").checked = card?.enabled ?? true;
  aiKnowledgeCardModal.hidden = false;
}

function closeAiKnowledgeCardModal() { aiKnowledgeCardModal.hidden = true; }

async function reloadAiKnowledgeCards() {
  const result = await requestGame("/api/ai-knowledge-cards");
  aiKnowledgeCards = result.items;
  configurationVersion = result.version;
  renderAiKnowledgeCards();
}

async function openAiAssistantSettingsModal() {
  const settings = aiAssistantSettings || await requestGame("/api/ai-assistant/settings");
  aiAssistantSettings = settings;
  document.querySelector("#ai-assistant-enabled").checked = settings.enabled;
  document.querySelector("#ai-assistant-persona").value = settings.persona;
  document.querySelector("#ai-assistant-system-prompt").value = settings.system_prompt;
  document.querySelector("#ai-assistant-over-limit-reply").value = settings.over_limit_reply;
  document.querySelector("#ai-assistant-failure-reply").value = settings.failure_reply;
  document.querySelector("#ai-assistant-max-chars").value = settings.max_response_chars;
  document.querySelector("#ai-assistant-timeout").value = settings.timeout_seconds;
  document.querySelector("#ai-memory-enabled").checked = settings.memory_enabled;
  document.querySelector("#ai-memory-extraction-prompt").value = settings.extraction_prompt;
  document.querySelector("#ai-memory-batch-threshold").value = settings.batch_message_threshold;
  document.querySelector("#ai-memory-max-entries").value = settings.max_entries_per_category;
  document.querySelector("#ai-memory-candidate-expiry-days").value = settings.candidate_expiry_days;
  document.querySelector("#ai-assistant-quotas").innerHTML = settings.quotas.map((quota) => `
    <tr><td><b>${escapeHtml(quota.rank_name)}</b></td><td>${escapeHtml(quota.rank_level_label)}</td><td><input data-ai-quota="${escapeHtml(quota.rank_id)}" type="number" min="0" max="100" value="${quota.daily_limit}"></td></tr>`).join("");
  aiAssistantSettingsModal.hidden = false;
}

const impressionCategories = [
  ["expression_style", "表达方式"],
  ["group_interaction", "群聊互动"],
  ["humor_style", "幽默风格"],
  ["interests", "长期兴趣"],
  ["supervisor_interaction", "与总监事互动"],
  ["boundaries", "互动边界"],
];

function activityTypeLabel(value) {
  return ({
    random_event: "随机事件",
    hide_and_seek: "摸鱼躲猫猫",
    memory_assessment: "记忆考核",
    undercover: "谁是卧底",
    blame_bomb: "甩锅游戏",
    number_bomb: "蹦蹦数字炸弹",
  })[value] || value;
}

function activityResultLabel(value) {
  return ({win: "胜利", loss: "失败", draw: "平局", participated: "已参与", ended: "已参与"})[value] || value;
}

function renderEmployeeMemory(memory) {
  currentEmployeeMemory = memory;
  document.querySelector("#employee-memory-impressions").innerHTML = impressionCategories.map(([category, label]) => {
    const entries = memory.impressions.filter((entry) => entry.category === category);
    return `<section class="impression-section" data-impression-category="${category}">
      <h3>${label}</h3>
      ${entries.length ? entries.map((entry) => `<article class="impression-entry" data-impression-id="${escapeHtml(entry.id)}">
        <p>${escapeHtml(entry.content)} <small>${entry.pinned ? "管理员固定" : "自动维护"}</small></p>
        <div class="impression-entry-actions"><button class="secondary" data-impression-edit="${escapeHtml(entry.id)}" type="button">编辑</button><button class="secondary" data-impression-pin="${escapeHtml(entry.id)}" type="button">${entry.pinned ? "解除固定" : "固定"}</button><button class="danger-button" data-impression-delete="${escapeHtml(entry.id)}" type="button">删除</button></div>
      </article>`).join("") : '<p class="muted">暂无</p>'}
    </section>`;
  }).join("");
  document.querySelector("#employee-memory-activity-facts").innerHTML = memory.activity_facts.length
    ? memory.activity_facts.map((fact) => `<article class="data-row"><div><b>${escapeHtml(activityTypeLabel(fact.activity_type))}</b><small>参与 ${fact.participation_count} 次 · 胜 ${fact.win_count} · 负 ${fact.loss_count}</small></div><div><span>${escapeHtml(activityResultLabel(fact.last_result))}</span><small>${formatHeartbeat(fact.last_result_at)}</small></div></article>`).join("")
    : '<p class="muted">暂无已结算的活动事实。</p>';
  document.querySelector("#employee-memory-legacy-text").textContent = memory.legacy_memory_text || "无";
  document.querySelector("#employee-memory-updated-at").textContent = memory.updated_at
    ? `最近更新：${formatHeartbeat(memory.updated_at)}`
    : "尚未形成稳定印象。";
}

async function refreshEmployeeMemory() {
  const platformId = employeeMemoryModal.dataset.platformId;
  renderEmployeeMemory(await requestGame(`/api/game/users/${platformId}/ai-memory`));
}

async function openEmployeeMemoryModal(platformId, displayName) {
  const memory = await requestGame(`/api/game/users/${platformId}/ai-memory`);
  employeeMemoryModal.dataset.platformId = platformId;
  document.querySelector("#employee-memory-modal-title").textContent = `管理 ${displayName} 的稳定印象`;
  renderEmployeeMemory(memory);
  employeeMemoryModal.hidden = false;
}

function undercoverStateLabel(state) {
  return ({signup: "报名中", dealing: "发牌中", speaking: "发言中", voting: "投票中", tie_break: "并列补充发言", awaiting_continue: "等待下一局", ended: "已结束"})[state] || "暂无对局";
}

function renderUndercoverSettings(settings) {
  document.querySelector("#undercover-settings-card").innerHTML = `
    <article><span>游戏状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>仅影响之后新创建的对局</small></article>
    <article><span>投票时长</span><strong>${settings.vote_seconds} 秒</strong><small>到时自动结算当轮投票</small></article>
    <article><span>白板胜利阈值</span><strong>存活 ≤ ${settings.whiteboard_win_remaining} 人</strong><small>白板仍在场时优先判定</small></article>
    <article><span>角色配比</span><strong>4–8 人共 ${settings.roles.length} 档</strong><small>${settings.roles.map((rule) => `${rule.player_count}人：平${rule.civilian_count}/卧${rule.undercover_count}/白${rule.whiteboard_count}`).join(" · ")}</small></article>`;
}

function renderUndercoverSession(session) {
  const voteDeadline = session.vote_deadline ? ` · 截止 ${formatHeartbeat(session.vote_deadline)}` : "";
  document.querySelector("#undercover-session-card").innerHTML = `
    <article><span>对局状态</span><strong>${undercoverStateLabel(session.state)}</strong><small>${session.state ? "当前群内唯一的谁是卧底对局" : "可以由玩家使用 /谁是卧底 人数 发起"}</small></article>
    <article><span>本局人数</span><strong>${session.player_count} / ${session.target_player_count || "—"}</strong><small>候场队列 ${session.queued_count} 人</small></article>
    <article><span>投票进度</span><strong>${session.current_vote_round ? `第 ${session.current_vote_round} 轮` : "未开始"}</strong><small>${escapeHtml(voteDeadline || "暂无投票倒计时")}</small></article>`;
}

async function loadUndercover() {
  const [settings, session] = await Promise.all([
    requestGame("/api/game/undercover/settings"),
    requestGame("/api/game/undercover/session"),
  ]);
  undercoverSettings = settings;
  configurationVersion = settings.version;
  renderUndercoverSettings(settings);
  renderUndercoverSession(session);
}

function renderUndercoverRoleInputs(roles) {
  document.querySelector("#undercover-role-inputs").innerHTML = roles.map((rule) => `
    <div class="undercover-role-row" data-player-count="${rule.player_count}"><b>${rule.player_count} 人局</b><label>平民<input data-undercover-civilian type="number" min="0" max="8" value="${rule.civilian_count}"></label><label>卧底<input data-undercover-undercover type="number" min="0" max="8" value="${rule.undercover_count}"></label><label>白板<input data-undercover-whiteboard type="number" min="0" max="8" value="${rule.whiteboard_count}"></label></div>`).join("");
}

async function openUndercoverSettingsModal() {
  const settings = undercoverSettings || await requestGame("/api/game/undercover/settings");
  undercoverSettings = settings;
  document.querySelector("#undercover-enabled").checked = settings.enabled;
  document.querySelector("#undercover-vote-seconds").value = settings.vote_seconds;
  document.querySelector("#undercover-signup-timeout").value = settings.signup_timeout_minutes;
  document.querySelector("#undercover-whiteboard-threshold").value = settings.whiteboard_win_remaining;
  renderUndercoverRoleInputs(settings.roles);
  undercoverSettingsModal.hidden = false;
}

function blameStateLabel(state) {
  return ({signup: "报名中", active: "进行中"})[state] || "暂无对局";
}

function renderBlameBombSettings(settings) {
  document.querySelector("#blame-bomb-settings-card").innerHTML = `
    <article><span>游戏状态</span><strong>${settings.enabled ? "已启用" : "已停用"}</strong><small>停用后不允许创建新对局</small></article>
    <article><span>报名与操作</span><strong>${settings.signup_timeout_seconds} / ${settings.turn_timeout_seconds} 秒</strong><small>报名时限 / 单次持锅时限</small></article>
    <article><span>引爆范围</span><strong>2–10 人共 ${settings.durations.length} 档</strong><small>${settings.durations.map((rule) => `${rule.player_count}人 ${rule.minimum_seconds}–${rule.maximum_seconds}秒`).join(" · ")}</small></article>`;
}

function renderBlameBombSession(session) {
  const players = session.players.map((player) => `${player.seat_number ? `${player.seat_number}号 ` : ""}${player.display_name}`).join("、");
  const holder = session.current_holder ? `${session.current_holder.seat_number}号 ${session.current_holder.display_name}` : "—";
  const incident = session.incident ? `${session.incident.name}：${session.incident.description}` : "尚未抽取事故卡";
  document.querySelector("#blame-bomb-session-card").innerHTML = `
    <article><span>对局状态</span><strong>${blameStateLabel(session.state)}</strong><small>${session.state ? `${session.players.length} / ${session.target_player_count} 人` : "玩家可使用 /甩锅游戏 人数 发起"}</small></article>
    <article><span>参与者</span><strong>${escapeHtml(players || "—")}</strong><small>固定编号在开局时生成</small></article>
    <article><span>事故</span><strong>${escapeHtml(incident)}</strong><small>${session.incident ? `关键词：${escapeHtml(session.incident.keywords.join("、"))}` : "—"}</small></article>
    <article><span>当前持锅者</span><strong>${escapeHtml(holder)}</strong><small>温度：${escapeHtml(session.temperature || "—")}</small></article>`;
  document.querySelector("#end-blame-bomb-session").disabled = !session.state;
}

function renderBlameIncidents(incidents) {
  const filtered = filterList("blame-incidents", incidents, (incident) => `${incident.name} ${incident.description} ${incident.keywords.join(" ")}`);
  document.querySelector("#blame-incident-list").innerHTML = filtered.map((incident) => `
    <article class="data-row"><div><b>${escapeHtml(incident.name)}</b><small>${statusBadge(incident.enabled ? "已启用" : "已停用", incident.enabled ? "success" : "warning")}</small><small>${escapeHtml(incident.description)}</small><small>关键词：${escapeHtml(incident.keywords.join("、"))}</small></div><div class="command-actions"><button class="secondary" data-blame-incident="${escapeHtml(JSON.stringify(incident))}" data-blame-incident-action="edit" type="button">编辑</button><button class="secondary" data-blame-incident="${escapeHtml(JSON.stringify(incident))}" data-blame-incident-action="toggle" type="button">${incident.enabled ? "停用" : "启用"}</button><button class="danger-button" data-blame-incident="${escapeHtml(JSON.stringify(incident))}" data-blame-incident-action="delete" type="button">删除</button></div></article>`).join("") || "<p class=\"muted\">还没有事故卡，新增并启用至少一张后才能创建游戏。</p>";
}

async function loadBlameBomb(page = blameIncidentPage) {
  const [settings, incidents, session] = await Promise.all([
    requestGame("/api/game/blame-bomb/settings"),
    requestGame(`/api/game/blame-bomb/incidents?page=${page}&page_size=${pageSizeFor("blame-incidents")}`),
    requestGame("/api/game/blame-bomb/session"),
  ]);
  blameBombSettings = settings;
  blameIncidentPage = incidents.page;
  configurationVersion = settings.version;
  renderBlameBombSettings(settings);
  renderBlameBombSession(session);
  renderBlameIncidents(incidents.items);
  renderPagination(document.querySelector("#blame-incident-pagination"), incidents, "张事故卡", loadBlameBomb);
}

async function openBlameBombSettingsModal() {
  const settings = blameBombSettings || await requestGame("/api/game/blame-bomb/settings");
  blameBombSettings = settings;
  document.querySelector("#blame-bomb-enabled").checked = settings.enabled;
  document.querySelector("#blame-bomb-signup-seconds").value = settings.signup_timeout_seconds;
  document.querySelector("#blame-bomb-turn-seconds").value = settings.turn_timeout_seconds;
  document.querySelector("#blame-bomb-duration-inputs").innerHTML = settings.durations.map((rule) => `
    <div class="undercover-role-row" data-player-count="${rule.player_count}"><b>${rule.player_count} 人局</b><label>最短秒数<input data-blame-minimum type="number" min="1" max="3600" value="${rule.minimum_seconds}"></label><label>最长秒数<input data-blame-maximum type="number" min="1" max="3600" value="${rule.maximum_seconds}"></label></div>`).join("");
  blameBombSettingsModal.hidden = false;
}

function closeBlameBombSettingsModal() { blameBombSettingsModal.hidden = true; }

function openBlameIncidentModal(incident = null) {
  blameIncidentModal.dataset.incidentId = incident?.id || "";
  document.querySelector("#blame-incident-modal-title").textContent = incident ? `编辑事故卡：${incident.name}` : "新增事故卡";
  document.querySelector("#blame-incident-name").value = incident?.name || "";
  document.querySelector("#blame-incident-description").value = incident?.description || "";
  document.querySelector("#blame-incident-keywords").value = incident?.keywords.join("\n") || "";
  document.querySelector("#blame-incident-enabled").checked = incident?.enabled ?? true;
  document.querySelector("#blame-incident-enabled-row").hidden = !incident;
  document.querySelector("#save-blame-incident").textContent = incident ? "保存事故卡" : "创建事故卡";
  blameIncidentModal.hidden = false;
}

function closeBlameIncidentModal() { blameIncidentModal.hidden = true; }

async function loadHideAndSeek(page = hideAndSeekScenePage) {
  const [settings, scenes] = await Promise.all([
    requestGame("/api/game/hide-and-seek/settings"),
    requestGame(`/api/game/hide-and-seek/scenes?page=${page}&page_size=${pageSizeFor("hide-and-seek-scenes")}`),
  ]);
  hideAndSeekSettings = settings;
  hideAndSeekScenePage = scenes.page;
  configurationVersion = settings.version;
  renderHideAndSeekSettings(settings);
  renderHideAndSeekScenes(scenes.items);
  renderPagination(document.querySelector("#hide-and-seek-scene-pagination"), scenes, "个地点", loadHideAndSeek);
}

async function openHideAndSeekSettingsModal() {
  const settings = hideAndSeekSettings || await requestGame("/api/game/hide-and-seek/settings");
  hideAndSeekSettings = settings;
  document.querySelector("#hide-and-seek-enabled").checked = settings.enabled;
  document.querySelector("#hide-and-seek-entry-fee").value = settings.entry_fee;
  document.querySelector("#hide-and-seek-win-reward").value = settings.win_reward;
  document.querySelector("#hide-and-seek-daily-limit").value = settings.daily_limit;
  document.querySelector("#hide-and-seek-timeout").value = settings.selection_timeout_minutes;
  hideAndSeekSettingsModal.hidden = false;
}

function openHideAndSeekSceneModal(scene = null) {
  hideAndSeekSceneModal.dataset.sceneId = scene?.id || "";
  hideAndSeekSceneModal.dataset.enabled = String(scene?.enabled ?? true);
  document.querySelector("#hide-and-seek-scene-modal-title").textContent = scene ? `编辑地点：${scene.name}` : "新增地点";
  document.querySelector("#save-hide-and-seek-scene").textContent = scene ? "保存地点" : "创建地点";
  document.querySelector("#hide-and-seek-scene-name").value = scene?.name || "";
  hideAndSeekSceneModal.hidden = false;
  document.querySelector("#hide-and-seek-scene-name").focus();
}

function renderTodayRandomEvents(events) {
  const groupNames = new Map(groupChats.map((group) => [group.id, group.name]));
  const filtered = filterList("random-event-today", events, (event) => `${groupNames.get(event.group_chat_id) || ""} ${event.scene_name || ""} ${event.event_name || ""} ${eventStatusLabel(event.status)}`);
  const pageData = renderLocalPagination(
    document.querySelector("#today-random-event-pagination"),
    filtered,
    todayRandomEventPage,
    pageSizeFor("random-event-today"),
    "场次",
    (page) => {
      todayRandomEventPage = page;
      renderTodayRandomEvents(todayRandomEvents);
    },
  );
  todayRandomEventPage = pageData.page;
  document.querySelector("#today-random-event-list").innerHTML = pageData.items.map((event) => `
    <article class="data-row"><div><b>${escapeHtml(groupNames.get(event.group_chat_id) || "未知群聊")} · ${escapeHtml(event.scene_name || "未安排场景")}－${escapeHtml(event.event_name || "未安排事件")}${event.is_cross_day ? "（跨日）" : ""}</b><small>${statusBadge(eventStatusLabel(event.status), event.status === "in_progress" ? "success" : event.status === "pending" ? "warning" : "")}</small><small>${formatHeartbeat(event.scheduled_at)}</small></div>${event.status === "pending" ? `<div class="command-actions"><button class="secondary" data-trigger-random-event="${event.id}" type="button">立即触发</button><button class="secondary" data-adjust-random-event="${event.id}" data-scheduled-at="${event.scheduled_at}" type="button">调整时间</button><button class="danger-button" data-delete-random-event="${event.id}" type="button">移除</button></div>` : event.status === "skipped" ? "" : `<button class="secondary" data-view-random-event-details="${event.id}" type="button">查看详情</button>`}</article>`).join("") || "<p class=\"muted\">暂无符合条件的今日场次。</p>";
}

async function loadRandomEvents(page = randomEventScenePage) {
  const [settings, scenes, today, submissions, groups] = await Promise.all([
    requestGame("/api/game/random-events/settings"),
    requestGame(`/api/game/random-events/scenes?page=${page}&page_size=${pageSizeFor("random-event-scenes")}`),
    requestGame("/api/game/random-events/today"),
    requestGame(buildRandomEventSubmissionsPath(randomEventSubmissionPage, pageSizeFor("random-event-submissions"), randomEventSubmissionStatus)),
    requestGame("/api/group-chats", {cache: "no-store"}),
  ]);
  randomEventSettings = settings;
  randomEventScenePage = scenes.page;
  todayRandomEvents = today.items;
  groupChats = groups.items;
  configurationVersion = settings.version;
  renderRandomEventSettings(settings);
  renderRandomEventScenes(scenes.items);
  renderPagination(document.querySelector("#random-event-scene-pagination"), scenes, "个场景", loadRandomEvents);
  renderTodayRandomEvents(today.items);
  randomEventSubmissionPage = submissions.page;
  renderRandomEventSubmissions(submissions);
  if (randomEventSubmissionStatus === "pending") {
    document.querySelector("#random-event-submission-pending-count").textContent = submissions.total ? `(${submissions.total})` : "";
  }
}

function renderRandomEventSceneSeat(role = "", capacity = 1) {
  const row = document.createElement("div");
  row.className = "scene-seat-row";
  row.innerHTML = `<input data-random-event-role maxlength="32" placeholder="角色，例如：主持" value="${escapeHtml(role)}"><input data-random-event-capacity type="number" min="1" max="99" value="${capacity}"><button class="text-button" data-remove-random-event-seat type="button">删除</button>`;
  randomEventSceneSeats.append(row);
  renderRandomEventSceneOpeningVariables();
}

function renderRandomEventSceneOpening(event = {}) {
  const row = document.createElement("div");
  row.className = "scene-opening-row";
  row.innerHTML = '<div class="scene-opening-editor"><input data-random-event-name maxlength="64" placeholder="事件名称，例如：咖啡事故"><textarea data-random-event-formal-opening rows="4" maxlength="2000" placeholder="例如：咖啡洒了一桌，主持人正在组织抢救。"></textarea><div class="scene-opening-variable-buttons"></div></div><button class="text-button" data-remove-random-event-opening type="button">删除</button>';
  row.querySelector("[data-random-event-name]").value = event.name || "";
  row.querySelector("textarea").value = event.opening_text || "";
  randomEventSceneOpenings.append(row);
  renderRandomEventSceneOpeningVariables();
}

function renderRandomEventSceneOpeningVariables() {
  const roles = [...new Set([...randomEventSceneSeats.querySelectorAll("[data-random-event-role]")]
    .map((input) => input.value.trim())
    .filter(Boolean))];
  randomEventSceneOpenings.querySelectorAll(".scene-opening-variable-buttons").forEach((container) => {
    container.innerHTML = roles.map((role) => `<button class="variable-chip" data-random-event-role-variable="${escapeHtml(role)}" type="button">{${escapeHtml(role)}}</button>`).join("");
  });
}

function insertRandomEventRoleVariable(role) {
  const hasTarget = randomEventSceneOpenings.contains(randomEventSceneOpeningTarget);
  const opening = hasTarget
    ? randomEventSceneOpeningTarget
    : randomEventSceneOpenings.querySelector("[data-random-event-formal-opening]");
  if (!opening) return;
  const token = `{${role}}`;
  if (hasTarget) {
    opening.setRangeText(token, opening.selectionStart, opening.selectionEnd, "end");
  } else {
    opening.value += token;
  }
  randomEventSceneOpeningTarget = opening;
  opening.focus();
}

function renderRandomEventSubmissionRole(role = {}) {
  const row = document.createElement("div");
  row.className = "scene-seat-row";
  row.innerHTML = `<input data-submission-role maxlength="32" placeholder="身份名称" value="${escapeHtml(role.role || "")}"><input data-submission-capacity type="number" min="1" max="999" value="${role.capacity || 1}"><button class="text-button" data-remove-submission-role type="button">删除</button>`;
  randomEventSubmissionRoles.append(row);
}

function renderRandomEventSubmissionEvent(item = {}) {
  const row = document.createElement("div");
  row.className = "scene-opening-row";
  row.innerHTML = `<div class="scene-opening-editor"><input data-submission-event-name maxlength="64" placeholder="事件名称" value="${escapeHtml(item.name || "")}"><textarea data-submission-event-opening rows="4" maxlength="2000" placeholder="正式剧情开场白">${escapeHtml(item.opening_text || "")}</textarea></div><button class="text-button" data-remove-submission-event type="button">删除</button>`;
  randomEventSubmissionEvents.append(row);
}

function randomEventSubmissionContentFromModal() {
  return {
    scene_name: document.querySelector("#random-event-submission-scene-name").value.trim(),
    signup_text: document.querySelector("#random-event-submission-signup-text").value.trim(),
    participant_count: Number(document.querySelector("#random-event-submission-participant-count").value),
    roles: [...randomEventSubmissionRoles.querySelectorAll(".scene-seat-row")].map((row) => ({
      role: row.querySelector("[data-submission-role]").value.trim(),
      capacity: Number(row.querySelector("[data-submission-capacity]").value),
    })),
    events: [...randomEventSubmissionEvents.querySelectorAll(".scene-opening-row")].map((row) => ({
      name: row.querySelector("[data-submission-event-name]").value.trim(),
      opening_text: row.querySelector("[data-submission-event-opening]").value.trim(),
    })),
  };
}

async function openRandomEventSubmissionModal(submissionId) {
  const submission = await requestGame(`/api/game/random-events/submissions/${submissionId}`);
  randomEventSubmissionModal.dataset.submissionId = submission.id;
  randomEventSubmissionModal.dataset.status = submission.status;
  document.querySelector("#random-event-submission-modal-title").textContent = `审核投稿 ${formatRandomEventSubmissionNumber(submission.number)}`;
  document.querySelector("#random-event-submission-meta").textContent = `${submission.display_name} ${submission.employee_number} · ${randomEventSubmissionStatusLabel(submission.status)}`;
  document.querySelector("#random-event-submission-scene-name").value = submission.content.scene_name || "";
  document.querySelector("#random-event-submission-signup-text").value = submission.content.signup_text || "";
  document.querySelector("#random-event-submission-participant-count").value = submission.content.participant_count || 1;
  randomEventSubmissionRoles.innerHTML = "";
  (submission.content.roles || []).forEach(renderRandomEventSubmissionRole);
  randomEventSubmissionEvents.innerHTML = "";
  (submission.content.events || []).forEach(renderRandomEventSubmissionEvent);
  document.querySelector("#random-event-submission-rewards").textContent = `固定配置：${submission.target_rounds} 轮 · 完成奖励 ${submission.event_reward} · 通过奖励 ${submission.approval_reward}`;
  document.querySelector("#random-event-submission-rejection-reason").value = submission.rejection_reason || "";
  const editable = submission.status === "pending";
  randomEventSubmissionModal.querySelectorAll("input, textarea").forEach((input) => { input.disabled = !editable; });
  randomEventSubmissionModal.querySelectorAll("[data-remove-submission-role], [data-remove-submission-event]").forEach((button) => { button.hidden = !editable; });
  for (const id of ["add-random-event-submission-role", "add-random-event-submission-event", "save-random-event-submission", "reject-random-event-submission", "approve-random-event-submission"]) {
    document.querySelector(`#${id}`).hidden = !editable;
  }
  randomEventSubmissionModal.hidden = false;
}

function closeRandomEventSubmissionModal() {
  randomEventSubmissionModal.hidden = true;
  delete randomEventSubmissionModal.dataset.submissionId;
}

async function openRandomEventSettingsModal() {
  const settings = randomEventSettings || await requestGame("/api/game/random-events/settings");
  randomEventSettings = settings;
  randomEventTimeInputs.innerHTML = "";
  settings.schedule_times.forEach((value) => renderRandomEventTime(value));
  document.querySelector("#random-event-signup-notice").value = settings.signup_notice_template;
  document.querySelector("#random-event-signup-timeout").value = settings.signup_timeout_minutes;
  document.querySelector("#random-event-reminder-interval").value = settings.reminder_interval_minutes;
  document.querySelector("#random-event-tipping-duration").value = settings.tipping_duration_seconds;
  document.querySelector("#random-event-blocked-message").value = settings.blocked_message;
  document.querySelector("#random-event-submission-enabled").checked = settings.submission_enabled;
  document.querySelector("#random-event-submission-timeout").value = settings.submission_draft_timeout_minutes;
  document.querySelector("#random-event-submission-max-participants").value = settings.submission_max_participants;
  document.querySelector("#random-event-submission-target-rounds").value = settings.submission_default_target_rounds;
  document.querySelector("#random-event-submission-event-reward").value = settings.submission_default_event_reward;
  document.querySelector("#random-event-submission-approval-reward").value = settings.submission_approval_reward;
  renderRandomEventCommandPermissions("#random-event-signup-command-permissions", "signup", settings.signup_allowed_commands);
  renderRandomEventCommandPermissions("#random-event-progress-command-permissions", "progress", settings.in_progress_allowed_commands);
  randomEventSettingsModal.hidden = false;
}

function renderRandomEventCommandPermissions(selector, phase, allowed) {
  document.querySelector(selector).innerHTML = randomEventCommandOptions.map(([value, label]) =>
    `<label><input data-random-event-${phase}-command type="checkbox" value="${value}"${allowed.includes(value) ? " checked" : ""}>${label}</label>`
  ).join("");
}

function renderRandomEventTime(value = "") {
  const row = document.createElement("div");
  row.className = "income-report-time-row";
  row.innerHTML = `<input data-random-event-time type="time" value="${escapeHtml(value)}"><button class="text-button" data-remove-random-event-time type="button">删除</button>`;
  randomEventTimeInputs.append(row);
}

function renderRandomEventAddTemplates() {
  const scene = randomEventAddScenes.find((item) => item.id === document.querySelector("#random-event-add-scene").value);
  document.querySelector("#random-event-add-template").innerHTML = (scene?.events || []).map((item) => `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`).join("");
}

async function openRandomEventAddModal() {
  const [scenes, groups] = await Promise.all([
    requestGame("/api/game/random-events/scenes?page=1&page_size=100"),
    requestGame("/api/group-chats", {cache: "no-store"}),
  ]);
  groupChats = groups.items;
  document.querySelector("#random-event-add-group").innerHTML = groupChats
    .filter((group) => group.listening_enabled && group.random_events_enabled)
    .map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`)
    .join("");
  randomEventAddScenes = scenes.items.filter((scene) => scene.enabled && scene.events.length);
  const sceneInput = document.querySelector("#random-event-add-scene");
  sceneInput.innerHTML = randomEventAddScenes.map((scene) => `<option value="${scene.id}">${escapeHtml(scene.name)}</option>`).join("");
  renderRandomEventAddTemplates();
  document.querySelector("#random-event-add-scheduled-at").value = "";
  randomEventAddModal.hidden = false;
}

function openRandomEventSceneModal(scene = null) {
  randomEventSceneModal.dataset.sceneId = scene?.id || "";
  randomEventSceneModal.dataset.enabled = String(scene?.enabled ?? true);
  document.querySelector("#random-event-scene-modal-title").textContent = scene ? `编辑场景：${scene.name}` : "新增场景";
  document.querySelector("#save-random-event-scene").textContent = scene ? "保存场景" : "创建场景";
  document.querySelector("#random-event-scene-name").value = scene?.name || "";
  document.querySelector("#random-event-scene-signup").value = scene?.signup_text || "";
  document.querySelector("#random-event-scene-rounds").value = scene?.target_rounds || 10;
  document.querySelector("#random-event-scene-reward").value = scene?.reward ?? 1;
  randomEventSceneSeats.innerHTML = "";
  (scene?.seats || [{role: "", capacity: 1}]).forEach((seat) => renderRandomEventSceneSeat(seat.role, seat.capacity));
  randomEventSceneOpenings.innerHTML = "";
  randomEventSceneOpeningTarget = null;
  (scene?.events || scene?.openings?.map((opening) => ({name: "未命名事件", opening_text: opening})) || [{}]).forEach((event) => renderRandomEventSceneOpening(event));
  randomEventSceneModal.hidden = false;
}

function openRandomEventTimeModal(button) {
  randomEventTimeModal.dataset.scheduleId = button.dataset.adjustRandomEvent;
  document.querySelector("#random-event-scheduled-at").value = formatBeijingInput(button.dataset.scheduledAt);
  randomEventTimeModal.hidden = false;
}

async function openRandomEventDetailsModal(scheduleId) {
  const details = await requestGame(`/api/game/random-events/today/${scheduleId}/details`);
  const dialogueRows = details.items.map((detail) => `<article class="data-row"><div><b>${escapeHtml(detail.display_name)}：${escapeHtml(detail.content)}</b><small>${formatHeartbeat(detail.occurred_at)}</small></div></article>`).join("");
  const tipRows = details.tips.map((tip) => `<article class="data-row"><div><b>${escapeHtml(tip.sender_display_name)} → ${escapeHtml(tip.recipient_display_name)}：${tip.amount} 摸鱼币</b><small>${formatHeartbeat(tip.created_at)}</small></div></article>`).join("");
  document.querySelector("#random-event-details-list").innerHTML = `${dialogueRows || '<p class="muted">暂无参与者发言记录。</p>'}<h3>打赏明细</h3>${tipRows || '<p class="muted">暂无打赏记录。</p>'}`;
  randomEventDetailsModal.hidden = false;
}

async function loadSettings() {
  gameSettings = await requestGame("/api/game/settings");
  configurationVersion = gameSettings.version;
  renderSettings(gameSettings);
  return gameSettings;
}

async function loadProfileSettings() {
  profileSettings = await requestGame("/api/game/profile-settings");
  renderProfileSettings(profileSettings);
  return profileSettings;
}

async function openProfileSettingsModal() {
  const settings = profileSettings || await loadProfileSettings();
  document.querySelector("#profile-settings-edit-cost").value = settings.edit_cost;
  document.querySelector("#profile-settings-shared-labor").value = settings.shared_labor;
  profileSettingsModal.hidden = false;
}

async function openEmployeeProfileModal(platformId, displayName) {
  const profile = await requestGame(`/api/game/users/${platformId}/profile`);
  employeeProfileModal.dataset.platformId = platformId;
  document.querySelector("#employee-profile-modal-title").textContent = `编辑档案：${displayName}`;
  document.querySelector("#employee-profile-text").value = profile.profile_text;
  renderEmployeeProfileImage(profile.profile_image_url, profile.latest_upload);
  employeeProfileModal.hidden = false;
}

function formatSignedAmount(amount) {
  return amount > 0 ? `+${amount}` : String(amount);
}

async function loadEmployeeBalanceLedger(page = 1) {
  const platformId = employeeBalanceLedgerModal.dataset.platformId;
  const requestId = ++employeeBalanceLedgerRequestId;
  const ledger = await requestGame(`/api/game/users/${platformId}/balance-transactions?page=${page}&page_size=20`);
  const currencyName = (gameSettings || await loadSettings()).currency_name;
  if (
    requestId !== employeeBalanceLedgerRequestId
    || platformId !== employeeBalanceLedgerModal.dataset.platformId
  ) return false;
  document.querySelector("#employee-balance-ledger-modal-title").textContent = `摸鱼币流水：${ledger.display_name}`;
  document.querySelector("#employee-balance-ledger-summary").innerHTML = `<strong>当前余额：${ledger.current_balance} ${escapeHtml(currencyName)}</strong><small>共 ${ledger.total} 条流水</small>`;
  document.querySelector("#employee-balance-ledger-list").innerHTML = ledger.items.map((item) => {
    const tone = item.amount > 0 ? "positive" : item.amount < 0 ? "negative" : "neutral";
    return `<article class="data-row balance-ledger-entry" data-tone="${tone}"><div><b>${escapeHtml(item.source_label)}</b><small>${formatHeartbeat(item.occurred_at)}</small></div><div class="balance-ledger-values"><strong class="balance-ledger-amount">${formatSignedAmount(item.amount)}</strong><small>变动后：${item.balance_after} ${escapeHtml(currencyName)}</small></div></article>`;
  }).join("") || '<p class="muted">暂无摸鱼币流水记录。</p>';
  renderPagination(document.querySelector("#employee-balance-ledger-pagination"), ledger, "条流水", (nextPage) => {
    void loadEmployeeBalanceLedger(nextPage).catch((error) => {
      setResult(`读取摸鱼币流水失败（${error.message}）`, "error");
    });
  });
  return true;
}

async function openEmployeeBalanceLedgerModal(platformId) {
  employeeBalanceLedgerModal.dataset.platformId = platformId;
  if (await loadEmployeeBalanceLedger(1)) employeeBalanceLedgerModal.hidden = false;
}

function renderEmployeeProfileImage(imageUrl, latestUpload = null) {
  const image = document.querySelector("#employee-profile-image");
  const empty = document.querySelector("#employee-profile-image-empty");
  image.hidden = !imageUrl;
  empty.hidden = Boolean(imageUrl);
  if (imageUrl) image.src = imageUrl;
  else image.removeAttribute("src");
  document.querySelector("#employee-profile-image-status").textContent = latestUpload
    ? `上传状态：${latestUpload.status}${latestUpload.failure_summary ? `（${latestUpload.failure_summary}）` : ""}`
    : "";
}

async function pollEmployeeProfileImage(taskId) {
  clearTimeout(employeeProfileImagePoll);
  const task = await requestGame(`/api/game/profile-image-uploads/${taskId}`);
  document.querySelector("#employee-profile-image-status").textContent = `上传状态：${task.status}${task.failure_summary ? `（${task.failure_summary}）` : ""}`;
  if (["pending", "processing"].includes(task.status)) {
    employeeProfileImagePoll = window.setTimeout(() => void pollEmployeeProfileImage(taskId), 1500);
    return;
  }
  if (task.status === "completed") {
    const profile = await requestGame(`/api/game/users/${employeeProfileModal.dataset.platformId}/profile`);
    renderEmployeeProfileImage(profile.profile_image_url, null);
  }
}

async function loadActivitySettings() {
  activitySettings = await requestGame("/api/game/activity-settings");
  configurationVersion = activitySettings.version;
  renderActivitySettings(activitySettings);
  return activitySettings;
}

async function loadNumberBombSettings() {
  numberBombSettings = await requestGame("/api/game/number-bomb/settings");
  configurationVersion = numberBombSettings.version;
  renderNumberBombSettings(numberBombSettings);
  return numberBombSettings;
}

async function loadRedPacketSettings() {
  redPacketSettings = await requestGame("/api/game/red-packet/settings");
  configurationVersion = redPacketSettings.version;
  renderRedPacketSettings(redPacketSettings);
  return redPacketSettings;
}

async function openNumberBombSettingsModal() {
  const settings = numberBombSettings || await loadNumberBombSettings();
  numberBombEnabled.checked = settings.enabled;
  numberBombSignupMinutes.value = settings.signup_timeout_minutes;
  numberBombReminderSeconds.value = settings.reminder_interval_seconds;
  numberBombSettingsModal.hidden = false;
  numberBombSignupMinutes.focus();
}

async function openRedPacketSettingsModal() {
  const settings = redPacketSettings || await loadRedPacketSettings();
  redPacketExpiryMinutes.value = settings.expiry_minutes;
  redPacketEmptyProbability.value = settings.empty_probability_percent;
  redPacketSettingsModal.hidden = false;
  redPacketExpiryMinutes.focus();
}

async function openSettingsModal() {
  const settings = gameSettings || await loadSettings();
  settingsCurrencyName.value = settings.currency_name;
  settingsOnboardingBonus.value = settings.onboarding_bonus;
  settingsCheckinReward.value = settings.checkin_reward;
  settingsWeeklyAttendanceReward.value = settings.weekly_attendance_reward;
  settingsModal.hidden = false;
  settingsCurrencyName.focus();
}

function renderActivitySettingsInputs() {
  activityRuleInputs.innerHTML = activitySettings.rules.map((rule) => `
    <div class="activity-rule-row"><b>LV${rule.level}</b><label>累计字数<input data-activity-threshold type="number" min="0" value="${rule.character_threshold}"></label><label>奖励<input data-activity-reward type="number" min="0" max="999" value="${rule.reward}"></label></div>`).join("");
  incomeReportTimeInputs.innerHTML = activitySettings.report_times.map((reportTime) => `
    <div class="income-report-time-row"><input data-income-report-time type="time" value="${escapeHtml(reportTime)}"><button class="text-button" data-remove-income-report-time type="button">删除</button></div>`).join("");
}

async function openActivitySettingsModal() {
  const settings = activitySettings || await loadActivitySettings();
  activitySettings = settings;
  renderActivitySettingsInputs();
  activitySettingsModal.hidden = false;
}

function openTemplateModal(button) {
  const templates = JSON.parse(button.dataset.commandTemplates);
  templateModal.dataset.command = button.dataset.command;
  templateModal.dataset.templates = button.dataset.commandTemplates;
  templateModalTitle.textContent = `配置 ${commandLabel(button.dataset.command)} 回复`;
  templateModalContext.textContent = button.dataset.commandDescription;
  templateModalScenario.innerHTML = templates
    .map((template) => `<option value="${escapeHtml(template.scenario)}">${escapeHtml(template.label)}</option>`)
    .join("");
  templateModalScenario.value = templates[0].scenario;
  loadTemplateScenario();
  templateModal.hidden = false;
  templateModalInput.focus();
}

function loadTemplateScenario() {
  const template = JSON.parse(templateModal.dataset.templates).find(
    (item) => item.scenario === templateModalScenario.value,
  );
  templateModalInput.value = template.template;
  templateModalVariables.innerHTML = template.variables
    .map((variable) => `<button class="variable-pill" data-variable="${escapeHtml(variable)}" type="button">${escapeHtml(variable)}</button>`)
    .join("");
}

async function requestGame(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const mutationHeaders = method === "GET" || method === "HEAD"
    ? {}
    : {"Idempotency-Key": idempotencyKey()};
  const response = await fetch(path, {
    ...options,
    headers: {...headers(), ...mutationHeaders, ...(options.headers || {})},
  });
  if (!response.ok) throw new Error(await responseError(response));
  return response.json();
}

async function responseError(response) {
  const body = await response.text();
  try {
    const detail = JSON.parse(body).detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => item.msg).filter(Boolean).join("；") || String(response.status);
    }
    if (detail && typeof detail === "object") return String(detail.message || response.status);
    return String(detail || response.status);
  } catch (_) {
    return body.trim() || String(response.status);
  }
}

async function runMutation(button, busyLabel, operation) {
  if (button.dataset.busy === "true") return;
  const label = button.textContent;
  button.dataset.busy = "true";
  button.disabled = true;
  button.textContent = busyLabel;
  try {
    return await operation();
  } finally {
    delete button.dataset.busy;
    button.disabled = false;
    button.textContent = label;
  }
}

function renderPagination(container, pageData, unit, onPageChange) {
  if (!pageData.total) {
    container.hidden = true;
    container.innerHTML = "";
    return;
  }
  const start = (pageData.page - 1) * pageData.page_size + 1;
  const end = Math.min(pageData.page * pageData.page_size, pageData.total);
  container.hidden = false;
  container.innerHTML = `<small>显示 ${start}–${end} 条，共 ${pageData.total} ${unit}</small>
    <button class="secondary" data-page="${pageData.page - 1}" type="button" ${pageData.page <= 1 ? "disabled" : ""}>上一页</button>
    <button class="secondary" data-page="${pageData.page + 1}" type="button" ${pageData.page >= pageData.pages ? "disabled" : ""}>下一页</button>`;
  for (const button of container.querySelectorAll("button[data-page]")) {
    button.addEventListener("click", () => void onPageChange(Number(button.dataset.page)));
  }
}

function formatEmployeeNumber(number) {
  return `#${String(number).padStart(4, "0")}`;
}

function groupConnectionLabel(state) {
  return ({connected: "已连接", pending: "连接中", failed: "连接失败", disabled: "已停用"})[state] || "状态未知";
}

function renderGroupChats(items) {
  document.querySelector("#group-chat-list").innerHTML = items.map((group) => {
    const runtime = group.runtime || {};
    const switches = [
      ["监听", group.listening_enabled],
      ["游戏", group.games_enabled],
      ["随机事件", group.random_events_enabled],
      ["公告", group.announcements_enabled],
    ].map(([label, enabled]) => `${label}：${enabled ? "开" : "关"}`).join(" · ");
    return `<article class="data-row"><div><b>${escapeHtml(group.name)}</b><small>${statusBadge(groupConnectionLabel(runtime.connection_state), runtime.connection_state === "connected" ? "success" : runtime.connection_state === "failed" ? "warning" : "")}</small><small>群聊 ID：${escapeHtml(group.chatroom_id || "未识别")} · ${escapeHtml(switches)}</small><small>${escapeHtml(group.chat_url || "未配置链接")}</small><small>最近接收：${formatHeartbeat(runtime.last_inbound_at)} · 最近发送：${formatHeartbeat(runtime.last_outbound_at)}</small>${runtime.last_error_summary ? `<small class="form-error">${escapeHtml(runtime.last_error_summary)}</small>` : ""}</div><div class="command-actions"><button class="secondary" data-edit-group-chat="${group.id}" type="button">编辑</button><button class="danger-button" data-delete-group-chat="${group.id}" type="button" ${group.listening_enabled ? "disabled" : ""}>删除</button></div></article>`;
  }).join("") || '<p class="muted">还没有可管理的群聊。</p>';
}

async function loadGroupChats() {
  const response = await requestGame("/api/group-chats", {cache: "no-store"});
  groupChats = response.items;
  configurationVersion = response.version;
  renderGroupChats(groupChats);
  return groupChats;
}

function openGroupChatModal(group = null) {
  groupChatModal.dataset.groupId = group?.id || "";
  document.querySelector("#group-chat-modal-title").textContent = group ? `编辑群聊：${group.name}` : "新增群聊";
  document.querySelector("#group-chat-name").value = group?.name || "";
  document.querySelector("#group-chat-url").value = group?.chat_url || "";
  document.querySelector("#group-chat-room-id").value = group?.chatroom_id || "";
  document.querySelector("#group-chat-listening-enabled").checked = group?.listening_enabled ?? true;
  document.querySelector("#group-chat-games-enabled").checked = group?.games_enabled ?? true;
  document.querySelector("#group-chat-random-events-enabled").checked = group?.random_events_enabled ?? true;
  document.querySelector("#group-chat-announcements-enabled").checked = group?.announcements_enabled ?? true;
  groupChatModal.hidden = false;
  document.querySelector("#group-chat-name").focus();
}

function closeGroupChatModal() {
  groupChatModal.hidden = true;
  groupChatModal.dataset.groupId = "";
}

async function loadEmployeeGroupMessages(page = employeeGroupMessagePage) {
  const platformId = employeeGroupMessagesModal.dataset.platformId;
  const groupId = document.querySelector("#employee-group-message-filter").value;
  const params = new URLSearchParams({page: String(page), page_size: "20"});
  if (groupId) params.set("group_chat_id", groupId);
  const history = await requestGame(`/api/game/users/${platformId}/group-messages?${params}`);
  employeeGroupMessagePage = history.page;
  document.querySelector("#employee-group-messages-modal-title").textContent = `消息记录：${history.display_name}`;
  document.querySelector("#employee-group-message-list").innerHTML = history.items.map((item) => `<article class="data-row"><div><b>${escapeHtml(item.group_name)}</b><small>${formatHeartbeat(item.received_at)}</small><p>${escapeHtml(item.content)}</p></div></article>`).join("") || '<p class="muted">该范围内暂无群聊消息。</p>';
  renderPagination(document.querySelector("#employee-group-message-pagination"), history, "条消息", loadEmployeeGroupMessages);
}

async function openEmployeeGroupMessagesModal(platformId) {
  if (!groupChats.length) await loadGroupChats();
  employeeGroupMessagesModal.dataset.platformId = platformId;
  const select = document.querySelector("#employee-group-message-filter");
  select.innerHTML = '<option value="">全部群聊</option>' + groupChats.map((group) => `<option value="${group.id}">${escapeHtml(group.name)}</option>`).join("");
  employeeGroupMessagePage = 1;
  await loadEmployeeGroupMessages(1);
  employeeGroupMessagesModal.hidden = false;
}

async function loadEmployees(page = employeePage) {
  const settings = gameSettings || await loadSettings();
  const employees = await requestGame(`/api/game/users?page=${page}&page_size=${pageSizeFor("employees")}`);
  employeePage = employees.page;
  const filtered = filterList("employees", employees.items, (employee) => `${employee.display_name} ${formatEmployeeNumber(employee.employee_number)} ${employee.employee_number} ${employee.rank_name || ""} ${employee.department_name || ""}`);
  document.querySelector("#employee-list").innerHTML = filtered.map((employee) => `
    <article class="data-row"><div><b>${escapeHtml(employee.display_name)}</b><small>工号：${formatEmployeeNumber(employee.employee_number)} · ${escapeHtml(employee.rank_name || "职位未分配")}（${escapeHtml(employee.rank_level_label || "—")}）· ${escapeHtml(employee.department_name || "未分配部门")}</small><small>入职：${formatHeartbeat(employee.joined_at)}</small></div><div class="command-actions"><strong>${employee.balance} ${escapeHtml(settings.currency_name)}</strong><button class="secondary" data-balance-ledger="${escapeHtml(employee.platform_id)}" type="button">摸鱼币流水</button><button class="secondary" data-employee-group-messages="${escapeHtml(employee.platform_id)}" type="button">群聊记录</button><button class="secondary" data-personal-profile="${escapeHtml(employee.platform_id)}" data-personal-profile-name="${escapeHtml(employee.display_name)}" type="button">档案</button><button class="secondary" data-ai-memory="${escapeHtml(employee.platform_id)}" data-ai-memory-name="${escapeHtml(employee.display_name)}" type="button">AI 记忆</button>${identity?.role === "super_admin" ? `<button class="secondary" data-board-member="${escapeHtml(employee.platform_id)}" data-board-active="${employee.rank_name === "核心董事会"}" type="button">${employee.rank_name === "核心董事会" ? "撤销董事会" : "授予董事会"}</button>` : ""}</div></article>`).join("") || "<p class=\"muted\">还没有员工入职。</p>";
  renderPagination(document.querySelector("#employee-pagination"), employees, "位员工", loadEmployees);
}

function openRankModal(rank) {
  rankModal.dataset.rank = JSON.stringify(rank);
  document.querySelector("#rank-modal-title").textContent = `编辑职位：${rank.name}`;
  document.querySelector("#rank-name").value = rank.name;
  document.querySelector("#rank-promotion-price").value = rank.promotion_price;
  document.querySelector("#rank-vote-weight").value = rank.vote_weight;
  document.querySelector("#rank-game-limit").value = rank.multiplayer_game_limit;
  document.querySelector("#rank-group-management").checked = rank.has_group_management;
  document.querySelector("#rank-enabled").checked = rank.enabled;
  document.querySelector("#rank-enabled").disabled = rank.is_board;
  rankModal.hidden = false;
}

function openDepartmentModal(department = null) {
  departmentModal.dataset.department = department ? JSON.stringify(department) : "";
  document.querySelector("#department-modal-title").textContent = department ? `编辑部门：${department.name}` : "新增部门";
  document.querySelector("#save-department").textContent = department ? "保存部门" : "创建部门";
  document.querySelector("#department-name").value = department?.name || "";
  document.querySelector("#department-description").value = department?.description || "";
  document.querySelector("#department-enabled").checked = department?.enabled ?? true;
  document.querySelector("#department-name").disabled = Boolean(department?.is_default);
  document.querySelector("#department-enabled").disabled = Boolean(department?.is_default);
  departmentModal.hidden = false;
}

function renderRanks(ranks) {
  const filtered = filterList("ranks", ranks, (rank) => `${rank.name} ${rank.level_label}`);
  const pageData = renderLocalPagination(
    document.querySelector("#rank-pagination"),
    filtered,
    rankPage,
    pageSizeFor("ranks"),
    "个职位",
    (page) => {
      rankPage = page;
      renderRanks(rankDefinitions);
    },
  );
  rankPage = pageData.page;
  document.querySelector("#rank-list").innerHTML = pageData.items.map((rank) => `
    <article class="data-row"><div><b>${escapeHtml(rank.name)}（${escapeHtml(rank.level_label)}）</b><small>${statusBadge(rank.enabled ? "已启用" : "已停用", rank.enabled ? "success" : "warning")}</small><small>晋升价格 ${rank.promotion_price} · 投票权益 ${rank.vote_weight} · 多人小游戏 ${rank.multiplayer_game_limit < 0 ? "不限" : `${rank.multiplayer_game_limit} 次`}</small><small>${rank.has_group_management ? "显示群内管理资格" : "无群内管理资格"}</small></div><button class="secondary" data-rank="${escapeHtml(JSON.stringify(rank))}" type="button">编辑</button></article>`).join("") || "<p class=\"muted\">暂无符合条件的职位。</p>";
}

function renderDepartments(departments) {
  const filtered = filterList("departments", departments, (department) => `${department.name} ${department.description || ""}`);
  document.querySelector("#department-list").innerHTML = filtered.map((department) => `
    <article class="data-row"><div><b>${escapeHtml(department.name)}</b><small>${statusBadge(department.enabled ? "已启用" : "已停用", department.enabled ? "success" : "warning")}</small><small>${escapeHtml(department.description || "暂无部门说明")}</small></div><div class="command-actions"><button class="secondary" data-department="${escapeHtml(JSON.stringify(department))}" data-department-action="edit" type="button">编辑</button>${department.is_default ? "" : `<button class="danger-button" data-department="${escapeHtml(JSON.stringify(department))}" data-department-action="delete" type="button">删除</button>`}</div></article>`).join("") || "<p class=\"muted\">没有符合条件的部门。</p>";
}

function renderPromotions(promotions, currencyName) {
  const filtered = filterList("promotions", promotions, (promotion) => `${promotion.number} ${promotion.applicant_name} ${promotion.source_rank_name} ${promotion.target_rank_name} ${promotion.state}`);
  document.querySelector("#promotion-list").innerHTML = filtered.map((promotion) => `
    <article class="data-row"><div><b>#${promotion.number} ${escapeHtml(promotion.applicant_name)}：${escapeHtml(promotion.source_rank_name)} → ${escapeHtml(promotion.target_rank_name)}</b><small>${promotion.price} ${escapeHtml(currencyName)} · ${escapeHtml(promotion.state)} · 申请于 ${formatHeartbeat(promotion.requested_at)}</small></div></article>`).join("") || "<p class=\"muted\">暂无晋升申请记录。</p>";
}

function renderDepartmentRequests(requests) {
  const filtered = filterList("department-requests", requests, (request) => `${request.number} ${request.applicant_name} ${request.source_department_name} ${request.target_department_name} ${request.state}`);
  document.querySelector("#department-request-list").innerHTML = filtered.map((request) => `
    <article class="data-row"><div><b>#${request.number} ${escapeHtml(request.applicant_name)}：${escapeHtml(request.source_department_name)} → ${escapeHtml(request.target_department_name)}</b><small>${escapeHtml(request.state)} · 申请于 ${formatHeartbeat(request.requested_at)}${request.approver_name ? ` · ${escapeHtml(request.approver_name)} ${escapeHtml(request.decision)}` : ""}</small></div></article>`).join("") || "<p class=\"muted\">暂无部门申请记录。</p>";
}

async function loadOrganization(departmentTarget = departmentPage, promotionTarget = promotionPage, departmentRequestTarget = departmentRequestPage) {
  const settings = gameSettings || await loadSettings();
  const [ranks, departments, promotions, departmentRequests] = await Promise.all([
    requestGame("/api/game/ranks"),
    requestGame(`/api/game/departments?page=${departmentTarget}&page_size=${pageSizeFor("departments")}`),
    requestGame(`/api/game/promotions?page=${promotionTarget}&page_size=${pageSizeFor("promotions")}`),
    requestGame(`/api/game/department-requests?page=${departmentRequestTarget}&page_size=${pageSizeFor("department-requests")}`),
  ]);
  departmentPage = departments.page;
  promotionPage = promotions.page;
  departmentRequestPage = departmentRequests.page;
  configurationVersion = departments.version;
  rankDefinitions = ranks;
  renderRanks(rankDefinitions);
  renderDepartments(departments.items);
  renderPromotions(promotions.items, settings.currency_name);
  renderDepartmentRequests(departmentRequests.items);
  renderPagination(document.querySelector("#department-pagination"), departments, "个部门", (page) => loadOrganization(page, promotionPage, departmentRequestPage));
  renderPagination(document.querySelector("#promotion-pagination"), promotions, "条申请", (page) => loadOrganization(departmentPage, page, departmentRequestPage));
  renderPagination(document.querySelector("#department-request-pagination"), departmentRequests, "条申请", (page) => loadOrganization(departmentPage, promotionPage, page));
}

async function loadShop(page = shopPage) {
  const settings = gameSettings || await loadSettings();
  const items = await requestGame(`/api/game/items?page=${page}&page_size=${pageSizeFor("shop")}`);
  shopPage = items.page;
  const filtered = filterList("shop", items.items, (item) => `${item.name} ${item.description}`);
  document.querySelector("#shop-list").innerHTML = filtered.map((item) => `
    <article class="data-row"><div><b>${escapeHtml(item.name)}</b><small>${escapeHtml(item.description)}</small></div><strong>${item.price} ${escapeHtml(settings.currency_name)} · 库存 ${item.stock}</strong></article>`).join("") || "<p class=\"muted\">尚未上架商品。</p>";
  renderPagination(document.querySelector("#shop-pagination"), items, "件物品", loadShop);
}

function renderCommands(commands) {
  const filtered = filterList("commands", commands, (command) => `${command.command} ${commandLabel(command.command)} ${command.description}`);
  const pageData = renderLocalPagination(
    document.querySelector("#command-pagination"),
    filtered,
    commandPage,
    pageSizeFor("commands"),
    "条指令",
    (page) => {
      commandPage = page;
      renderCommands(commandDefinitions);
    },
  );
  commandPage = pageData.page;
  document.querySelector("#command-list").innerHTML = pageData.items.map((command) => `
    <article class="command-card">
      <div class="command-heading"><div><b>${escapeHtml(commandLabel(command.command))}</b><small>${statusBadge(command.enabled ? "已启用" : "已停用", command.enabled ? "success" : "warning")}</small><small>${escapeHtml(command.description)}</small></div>
      <div class="command-actions"><button class="secondary" data-command-templates="${escapeHtml(JSON.stringify(command.templates))}" data-command="${escapeHtml(command.command)}" data-command-description="${escapeHtml(command.description)}" type="button">配置回复</button>
      <button class="${command.enabled ? "secondary" : "primary"}" data-command="${escapeHtml(command.command)}" data-enabled="${!command.enabled}" type="button">${command.enabled ? "停用" : "启用"}</button></div></div>
    </article>`).join("") || "<p class=\"muted\">暂无指令。</p>";
}

function renderAdministrators(accounts) {
  const filtered = filterList("admins", accounts, (account) => account.username);
  const pageData = renderLocalPagination(
    document.querySelector("#admin-pagination"),
    filtered,
    administratorPage,
    pageSizeFor("admins"),
    "位管理员",
    (page) => {
      administratorPage = page;
      renderAdministrators(administratorAccounts);
    },
  );
  administratorPage = pageData.page;
  document.querySelector("#admin-account-list").innerHTML = pageData.items.map((account) => `
    <article class="data-row"><div><b>${escapeHtml(account.username)}</b><small>${statusBadge(account.active ? "可登录" : "已停用", account.active ? "success" : "warning")}</small><small>${account.active ? "可登录，可运营" : "所有会话已失效"}</small></div>
    <div class="command-actions"><button class="secondary" data-admin-action="toggle" data-admin-id="${account.id}" data-admin-active="${account.active}" type="button">${account.active ? "停用" : "启用"}</button><button class="secondary" data-admin-action="password" data-admin-id="${account.id}" type="button">重置密码</button><button class="danger-button" data-admin-action="delete" data-admin-id="${account.id}" type="button">删除</button></div></article>`).join("") || "<p class=\"muted\">还没有普通管理员账号。</p>";
}

async function loadAdministrators() {
  const accounts = await requestGame("/api/admins", {cache: "no-store"});
  administratorAccounts = accounts;
  renderAdministrators(administratorAccounts);
}

function showView(view) {
  for (const element of document.querySelectorAll(".dashboard-view")) {
    element.hidden = element.id !== `${view}-view`;
  }
  for (const button of document.querySelectorAll(".nav-item")) {
    button.classList.toggle("active", button.dataset.view === view);
  }
}

async function loadGameView(view) {
  setPageContext(view);
  showView(view);
  try {
    if (view === "overview") return refresh();
    if (view === "settings") {
      await Promise.all([loadSettings(), loadProfileSettings(), loadActivitySettings(), loadNumberBombSettings(), loadRedPacketSettings()]);
      return;
    }
    if (view === "events") return loadRandomEvents();
    if (view === "hide-and-seek") return loadHideAndSeek();
    if (view === "memory-assessment") return loadMemoryAssessment();
    if (view === "undercover") return loadUndercover();
    if (view === "blame-bomb") return loadBlameBomb();
    if (view === "ai-assistant") return loadAiAssistant();
    if (view === "commands") {
      const commands = await requestGame("/api/game/commands");
      configurationVersion = commands[0]?.version ?? configurationVersion;
      commandDefinitions = commands;
      renderCommands(commandDefinitions);
      return;
    }
    if (view === "organization") return loadOrganization();
    if (view === "group-chats") return loadGroupChats();
    if (view === "employees") {
      return loadEmployees();
    }
    if (view === "shop") return loadShop();
    if (identity?.role !== "super_admin") throw new Error("仅超级管理员可管理账号");
    return loadAdministrators();
  } catch (error) {
    setResult(`数据读取失败（${error.message}）`, "error");
  }
}

function updateControls(state) {
  const isRequired = state === "auth_required";
  const isProgress = state === "auth_in_progress";
  const hasLease = Boolean(loginLease);
  document.querySelector("#start-login").disabled = !isRequired || hasLease;
  document.querySelector("#open-login-console").disabled = !isProgress || !ownsLoginLease();
  document.querySelector("#finish-login").disabled = !isProgress || !ownsLoginLease();
  document.querySelector("#cancel-login").disabled = !hasLease;
  document.querySelector("#restart-browser").disabled = isProgress;
  document.querySelector("#step-required").classList.toggle("active", isRequired);
  document.querySelector("#step-console").classList.toggle("active", isProgress);
  document.querySelector("#step-finish").classList.toggle("active", state === "ready");
  loginStep.textContent = isProgress ? "验证进行中" : isRequired ? "需要登录" : state === "ready" ? "已登录" : "等待开始";
  const listenerUnknown = typeof currentListeningDesired !== "boolean";
  document.querySelector("#start-listening").disabled = listenerUnknown || currentListeningDesired;
  document.querySelector("#pause-listening").disabled = listenerUnknown || !currentListeningDesired;
  if (!isProgress || !ownsLoginLease()) {
    consolePanel.hidden = true;
    consoleFrame.removeAttribute("src");
  }
}

function renderListenerStatus(status) {
  currentListening = typeof status.listening === "boolean" ? status.listening : null;
  currentListeningDesired = typeof status.listening_desired === "boolean" ? status.listening_desired : null;
  const badge = document.querySelector("#listener-state");
  const help = document.querySelector("#listener-help");
  let tone = "";
  if (currentListeningDesired === null) {
    badge.textContent = "状态未知";
    help.textContent = "等待 Worker 心跳。";
  } else if (!currentListeningDesired) {
    badge.textContent = "已暂停";
    help.textContent = "管理员已暂停读取群聊消息，重启后仍保持暂停。";
    tone = "warning";
  } else if (status.state === "ready" && currentListening) {
    badge.textContent = "监听中";
    help.textContent = "机器人正在读取并处理群聊消息。";
    tone = "success";
  } else {
    badge.textContent = "等待恢复";
    help.textContent = "监听已开启，将在浏览器恢复后自动继续。";
    tone = "warning";
  }
  if (tone) badge.dataset.tone = tone;
  else delete badge.dataset.tone;
}

function renderStatus(status) {
  currentState = status.state || "unknown";
  stateElement.textContent = currentState.replaceAll("_", " ");
  stateElement.dataset.state = currentState;
  stateHelp.textContent = currentState === "auth_required" ? "登录已失效，请启动人工登录" : currentState === "auth_in_progress" ? "请在登录控制台完成验证" : currentState === "ready" ? "浏览器已就绪" : "等待 Worker 心跳";
  document.querySelector("#last-heartbeat").textContent = formatHeartbeat(status.last_heartbeat);
  const queue = status.queue_counts || {};
  document.querySelector("#queue-total").textContent = String(queue.inbound_accepted || 0);
  document.querySelector("#queue-counts").textContent = Object.entries(queue).map(([key, value]) => `${key}: ${value}`).join(" · ") || "队列为空";
  renderListenerStatus(status);
  updateControls(currentState);
}

function renderLoginLease() {
  const leaseElement = document.querySelector("#login-lease");
  if (!loginLease) {
    leaseElement.textContent = "当前没有人工登录操作。";
  } else {
    const seconds = Math.max(0, Math.ceil((new Date(loginLease.expires_at).getTime() - Date.now()) / 1000));
    leaseElement.textContent = `当前由 ${loginLease.operator_name} 操作，剩余 ${seconds} 秒。${ownsLoginLease() ? " 你可完成或终止本次登录。" : " 任何管理员均可终止本次登录。"}`;
  }
  updateControls(currentState);
  if (currentState === "auth_in_progress" && ownsLoginLease() && !consoleFrame.getAttribute("src")) void openConsole();
}

async function refreshLoginLease() {
  loginLease = await requestGame("/api/login/lease");
  renderLoginLease();
}

async function refresh() {
  if ((!token && !adminSession) || refreshLoading) return;
  refreshLoading = true;
  try {
    const response = await fetch("/api/status", {headers: headers()});
    if (response.status === 401) {
      clearAuthentication();
      loginError.textContent = "登录已失效，请重新登录。";
      return;
    }
    if (!response.ok) {
      setResult(`状态读取失败（${await responseError(response)}）`, "error");
      return;
    }
    renderStatus(await response.json());
    await Promise.all([refreshLoginLease(), loadCurrentGameplay()]);
  } catch (error) {
    setResult(`状态读取失败（${error.message}）`, "error");
  } finally {
    refreshLoading = false;
  }
}

async function submitAction(button) {
  const busyLabel = button.id === "start-login" ? "启动中…" : button.id === "restart-browser" ? "重启中…" : button.id === "start-listening" ? "开启中…" : button.id === "pause-listening" ? "暂停中…" : "提交中…";
  try {
    await runMutation(button, busyLabel, async () => {
      await requestGame(button.dataset.action, {method: "POST"});
      if (button.id === "start-login") {
        setResult("正在启动安全登录桌面…", "success");
        if (await waitForLoginDesktop()) await openConsole();
      } else {
        setResult("操作指令已发送，正在等待 Worker 响应。", "success");
        window.setTimeout(refresh, 800);
      }
    });
  } catch (error) {
    setResult(`操作失败（${error.message}）`, "error");
  } finally {
    updateControls(currentState);
  }
}

async function waitForLoginDesktop() {
  for (let attempt = 0; attempt < 24; attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500));
    await refresh();
    if (currentState === "auth_in_progress") return true;
    if (currentState !== "auth_required") break;
  }
  setResult("登录桌面启动超时，请刷新状态后重试。", "error");
  return false;
}

async function openConsole() {
  if (consoleLoading || consoleFrame.getAttribute("src")) return;
  consoleLoading = true;
  const button = document.querySelector("#open-login-console");
  try {
    await runMutation(button, "加载中…", async () => {
      const response = await fetch("/api/session", {method: "POST", headers: headers()});
      if (!response.ok) throw new Error(await responseError(response));
      consoleFrame.src = "/login-console";
      consolePanel.hidden = false;
      consolePanel.scrollIntoView({behavior: "smooth", block: "start"});
      setResult("登录桌面已就绪，请在下方完成验证。", "success");
    });
  } catch (error) {
    setResult(`登录控制台授权失败（${error.message}）`, "error");
  } finally {
    consoleLoading = false;
    updateControls(currentState);
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  token = document.querySelector("#admin-token").value.trim();
  if (!token) return;
  adminSession = "";
  identity = {account_id: null, username: "超级管理员", role: "super_admin"};
  sessionStorage.setItem("dzmm-admin-token", token);
  sessionStorage.removeItem("dzmm-admin-session");
  sessionStorage.setItem("dzmm-admin-identity", JSON.stringify(identity));
  loginError.textContent = "";
  setAuthenticated(true);
  await refresh();
});

accountLoginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await runMutation(button, "登录中…", async () => {
      const response = await fetch("/api/auth/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
      if (!response.ok) throw new Error(await responseError(response));
      const login = await response.json();
      token = "";
      adminSession = login.session_token;
      identity = {account_id: login.account_id, username: login.username, role: login.role};
      sessionStorage.removeItem("dzmm-admin-token");
      sessionStorage.setItem("dzmm-admin-session", adminSession);
      sessionStorage.setItem("dzmm-admin-identity", JSON.stringify(identity));
      loginError.textContent = "";
      setAuthenticated(true);
      await refresh();
    });
  } catch (error) {
    loginError.textContent = `登录失败：${error.message}`;
  }
});

document.querySelector("#logout").addEventListener("click", async () => {
  if (adminSession) await fetch("/api/auth/logout", {method: "POST", headers: headers()});
  clearAuthentication();
  loginForm.reset();
  accountLoginForm.reset();
});
document.querySelector("#refresh").addEventListener("click", async (event) => {
  await runMutation(event.currentTarget, "刷新中…", refresh);
});
document.querySelector("#open-login-console").addEventListener("click", openConsole);
document.querySelector("#cancel-login").addEventListener("click", async (event) => {
  try {
    await runMutation(event.currentTarget, "终止中…", async () => {
      await requestGame("/api/login/cancel", {method: "POST"});
      consolePanel.hidden = true;
      consoleFrame.removeAttribute("src");
      await refresh();
    });
    setResult("人工登录已终止，浏览器将恢复常驻 Worker。", "success");
  } catch (error) {
    setResult(`终止失败（${error.message}）`, "error");
  }
});
document.querySelector("#edit-settings").addEventListener("click", () => void openSettingsModal());
document.querySelector("#edit-profile-settings").addEventListener("click", () => void openProfileSettingsModal());
document.querySelector("#edit-activity-settings").addEventListener("click", () => void openActivitySettingsModal());
document.querySelector("#edit-number-bomb-settings").addEventListener("click", () => void openNumberBombSettingsModal());
document.querySelector("#edit-red-packet-settings").addEventListener("click", () => void openRedPacketSettingsModal());
document.querySelector("#edit-random-event-settings").addEventListener("click", () => void openRandomEventSettingsModal());
document.querySelector("#create-random-event-scene").addEventListener("click", () => openRandomEventSceneModal());
document.querySelector("#edit-hide-and-seek-settings").addEventListener("click", () => void openHideAndSeekSettingsModal());
document.querySelector("#create-hide-and-seek-scene").addEventListener("click", () => openHideAndSeekSceneModal());
document.querySelector("#edit-memory-assessment-settings").addEventListener("click", () => void openMemoryAssessmentSettingsModal());
document.querySelector("#edit-undercover-settings").addEventListener("click", () => void openUndercoverSettingsModal());
document.querySelector("#edit-blame-bomb-settings").addEventListener("click", () => void openBlameBombSettingsModal());
document.querySelector("#create-blame-incident").addEventListener("click", () => openBlameIncidentModal());
document.querySelector("#edit-ai-assistant-settings").addEventListener("click", () => void openAiAssistantSettingsModal());
document.querySelector("#add-ai-knowledge-card").addEventListener("click", () => openAiKnowledgeCardModal());
document.querySelector("#create-department").addEventListener("click", () => openDepartmentModal());
document.querySelector("#add-today-random-event").addEventListener("click", async (event) => {
  try {
    await runMutation(event.currentTarget, "加载中…", openRandomEventAddModal);
  } catch (error) {
    setResult(`加载场景失败（${error.message}）`, "error");
  }
});
document.querySelector("#refresh-random-events").addEventListener("click", async (event) => {
  try {
    await runMutation(event.currentTarget, "刷新中…", loadRandomEvents);
  } catch (error) {
    setResult(`刷新失败（${error.message}）`, "error");
  }
});
document.querySelector("#refresh-random-event-submissions").addEventListener("click", async (event) => {
  try {
    await runMutation(event.currentTarget, "刷新中…", loadRandomEventSubmissions);
  } catch (error) {
    setResult(`刷新投稿失败（${error.message}）`, "error");
  }
});
document.querySelector("#random-event-submission-status").addEventListener("change", (event) => {
  randomEventSubmissionStatus = event.target.value;
  randomEventSubmissionPage = 1;
  void loadRandomEventSubmissions();
});
for (const button of document.querySelectorAll("button[data-action]")) {
  button.addEventListener("click", () => submitAction(button));
}
for (const button of document.querySelectorAll(".nav-item")) {
  button.addEventListener("click", () => void loadGameView(button.dataset.view));
}
document.querySelector("#create-group-chat").addEventListener("click", () => openGroupChatModal());
groupChatModal.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-group-chat-modal]")) closeGroupChatModal();
});
document.querySelector("#save-group-chat").addEventListener("click", async (event) => {
  const groupId = groupChatModal.dataset.groupId;
  const payload = {
    name: document.querySelector("#group-chat-name").value,
    chat_url: document.querySelector("#group-chat-url").value,
    listening_enabled: document.querySelector("#group-chat-listening-enabled").checked,
    games_enabled: document.querySelector("#group-chat-games-enabled").checked,
    random_events_enabled: document.querySelector("#group-chat-random-events-enabled").checked,
    announcements_enabled: document.querySelector("#group-chat-announcements-enabled").checked,
  };
  try {
    await runMutation(event.currentTarget, "保存中…", async () => {
      const updated = await requestGame(groupId ? `/api/group-chats/${groupId}` : "/api/group-chats", {
        method: groupId ? "PATCH" : "POST",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify(payload),
      });
      configurationVersion = updated.version;
      closeGroupChatModal();
      await loadGroupChats();
    });
    setResult(groupId ? "群聊配置已保存" : "群聊已新增", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#group-chat-list").addEventListener("click", async (event) => {
  const edit = event.target.closest("button[data-edit-group-chat]");
  if (edit) {
    openGroupChatModal(groupChats.find((group) => group.id === edit.dataset.editGroupChat));
    return;
  }
  const remove = event.target.closest("button[data-delete-group-chat]");
  if (!remove || !window.confirm("确定删除这个已停用群聊？历史消息和业务记录会保留。")) return;
  try {
    await runMutation(remove, "删除中…", async () => {
      const updated = await requestGame(`/api/group-chats/${remove.dataset.deleteGroupChat}`, {
        method: "DELETE",
        headers: configurationHeaders(),
      });
      configurationVersion = updated.version;
      await loadGroupChats();
    });
    setResult("群聊已删除", "success");
  } catch (error) {
    setResult(`删除失败（${error.message}）`, "error");
  }
});
employeeGroupMessagesModal.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-employee-group-messages-modal]")) employeeGroupMessagesModal.hidden = true;
});
document.querySelector("#employee-group-message-filter").addEventListener("change", () => {
  employeeGroupMessagePage = 1;
  void loadEmployeeGroupMessages(1).catch((error) => setResult(`读取群聊记录失败（${error.message}）`, "error"));
});
document.querySelector("#employee-list").addEventListener("click", async (event) => {
  const ledgerButton = event.target.closest("button[data-balance-ledger]");
  if (ledgerButton) {
    try {
      await openEmployeeBalanceLedgerModal(ledgerButton.dataset.balanceLedger);
    } catch (error) {
      setResult(`读取摸鱼币流水失败（${error.message}）`, "error");
    }
    return;
  }
  const groupMessagesButton = event.target.closest("button[data-employee-group-messages]");
  if (groupMessagesButton) {
    try {
      await openEmployeeGroupMessagesModal(groupMessagesButton.dataset.employeeGroupMessages);
    } catch (error) {
      setResult(`读取群聊记录失败（${error.message}）`, "error");
    }
    return;
  }
  const profileButton = event.target.closest("button[data-personal-profile]");
  if (profileButton) {
    try {
      await openEmployeeProfileModal(
        profileButton.dataset.personalProfile,
        profileButton.dataset.personalProfileName,
      );
    } catch (error) {
      setResult(`读取员工档案失败（${error.message}）`, "error");
    }
    return;
  }
  const memoryButton = event.target.closest("button[data-ai-memory]");
  if (memoryButton) {
    try {
      await openEmployeeMemoryModal(
        memoryButton.dataset.aiMemory,
        memoryButton.dataset.aiMemoryName,
      );
    } catch (error) {
      setResult(`读取玩家记忆失败（${error.message}）`, "error");
    }
    return;
  }
  const button = event.target.closest("button[data-board-member]");
  if (!button) return;
  const member = button.dataset.boardActive !== "true";
  if (!window.confirm(member ? "确认授予该员工核心董事会身份？" : "确认撤销该员工的核心董事会身份？")) return;
  try {
    await runMutation(button, "处理中…", async () => {
      await requestGame(`/api/game/users/${button.dataset.boardMember}/board-membership`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({member}),
      });
      await loadEmployees();
    });
    setResult(member ? "已授予核心董事会身份" : "已撤销核心董事会身份", "success");
  } catch (error) {
    setResult(`操作失败（${error.message}）`, "error");
  }
});
document.querySelector("#rank-list").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-rank]");
  if (button) openRankModal(JSON.parse(button.dataset.rank));
});
document.querySelector("#department-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-department]");
  if (!button) return;
  const department = JSON.parse(button.dataset.department);
  if (button.dataset.departmentAction === "edit") {
    openDepartmentModal(department);
    return;
  }
  if (!window.confirm(`确认删除部门“${department.name}”？`)) return;
  try {
    await runMutation(button, "删除中…", async () => {
      const updated = await requestGame(`/api/game/departments/${department.id}`, {
        method: "DELETE", headers: configurationHeaders(),
      });
      configurationVersion = updated.version;
      await loadOrganization();
    });
    setResult("部门已删除", "success");
  } catch (error) {
    setResult(`删除失败（${error.message}）`, "error");
  }
});
rankModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-rank-modal]")) {
    closeRankModal();
    return;
  }
  if (event.target.id !== "save-rank") return;
  const rank = JSON.parse(rankModal.dataset.rank);
  const payload = {
    name: document.querySelector("#rank-name").value.trim(),
    promotion_price: Number(document.querySelector("#rank-promotion-price").value),
    vote_weight: Number(document.querySelector("#rank-vote-weight").value),
    multiplayer_game_limit: Number(document.querySelector("#rank-game-limit").value),
    has_group_management: document.querySelector("#rank-group-management").checked,
    enabled: document.querySelector("#rank-enabled").checked,
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      const updated = await requestGame(`/api/game/ranks/${rank.id}`, {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(payload),
      });
      configurationVersion = updated.version;
      closeRankModal();
      await loadOrganization();
    });
    setResult("职位配置已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
departmentModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-department-modal]")) {
    closeDepartmentModal();
    return;
  }
  if (event.target.id !== "save-department") return;
  const existing = departmentModal.dataset.department ? JSON.parse(departmentModal.dataset.department) : null;
  const payload = {
    name: document.querySelector("#department-name").value.trim(),
    description: document.querySelector("#department-description").value.trim(),
    enabled: document.querySelector("#department-enabled").checked,
  };
  try {
    await runMutation(event.target, existing ? "保存中…" : "创建中…", async () => {
      const updated = await requestGame(
        existing ? `/api/game/departments/${existing.id}` : "/api/game/departments",
        {
          method: existing ? "PUT" : "POST",
          headers: {"Content-Type": "application/json", ...configurationHeaders()},
          body: JSON.stringify(existing ? payload : {name: payload.name, description: payload.description}),
        },
      );
      configurationVersion = updated.version;
      closeDepartmentModal();
      await loadOrganization();
    });
    setResult(existing ? "部门配置已保存" : "部门已创建", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#command-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-command][data-enabled]");
  if (button) {
    try {
      await runMutation(button, button.dataset.enabled === "true" ? "启用中…" : "停用中…", async () => {
        const updated = await requestGame("/api/game/commands", {
          method: "PATCH",
          headers: {"Content-Type": "application/json", ...configurationHeaders()},
          body: JSON.stringify({command: button.dataset.command, enabled: button.dataset.enabled === "true"}),
        });
        configurationVersion = updated.version;
        await loadGameView("commands");
      });
      setResult("指令状态已更新", "success");
    } catch (error) {
      setResult(`更新失败（${error.message}）`, "error");
    }
    return;
  }
  const configure = event.target.closest("button[data-command-templates]");
  if (configure) openTemplateModal(configure);
});
templateModalScenario.addEventListener("change", loadTemplateScenario);
templateModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-template-modal]")) {
    closeTemplateModal();
    return;
  }
  const variable = event.target.closest("button[data-variable]");
  if (variable) {
    const start = templateModalInput.selectionStart;
    const end = templateModalInput.selectionEnd;
    templateModalInput.value = `${templateModalInput.value.slice(0, start)}${variable.dataset.variable}${templateModalInput.value.slice(end)}`;
    templateModalInput.focus();
    templateModalInput.selectionStart = templateModalInput.selectionEnd = start + variable.dataset.variable.length;
    return;
  }
  if (event.target.id !== "save-template-modal") return;
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      const updated = await requestGame("/api/game/command-templates", {
        method: "PATCH",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          command: templateModal.dataset.command,
          scenario: templateModalScenario.value,
          template: templateModalInput.value,
        }),
      });
      configurationVersion = updated.version;
      closeTemplateModal();
      await loadGameView("commands");
    });
    setResult("回复模板已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
settingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-settings-modal]")) {
    closeSettingsModal();
    return;
  }
  if (event.target.id !== "save-settings-modal") return;
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      gameSettings = await requestGame("/api/game/settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          currency_name: settingsCurrencyName.value.trim(),
          onboarding_bonus: Number(settingsOnboardingBonus.value),
          checkin_reward: Number(settingsCheckinReward.value),
          weekly_attendance_reward: Number(settingsWeeklyAttendanceReward.value),
        }),
      });
      configurationVersion = gameSettings.version;
      renderSettings(gameSettings);
      closeSettingsModal();
    });
    setResult("经济规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
profileSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-profile-settings-modal]")) {
    closeProfileSettingsModal();
    return;
  }
  if (event.target.id !== "save-profile-settings") return;
  try {
    await runMutation(event.target, "保存中…", async () => {
      profileSettings = await requestGame("/api/game/profile-settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          edit_cost: Number(document.querySelector("#profile-settings-edit-cost").value),
          shared_labor: Number(document.querySelector("#profile-settings-shared-labor").value),
          version: profileSettings.version,
        }),
      });
      renderProfileSettings(profileSettings);
      closeProfileSettingsModal();
    });
    setResult("档案设置已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}），请刷新后重试`, "error");
  }
});
employeeBalanceLedgerModal.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-employee-balance-ledger-modal]")) {
    closeEmployeeBalanceLedgerModal();
  }
});
employeeProfileModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-employee-profile-modal]")) {
    closeEmployeeProfileModal();
    return;
  }
  const platformId = employeeProfileModal.dataset.platformId;
  if (event.target.id === "upload-employee-profile-image") {
    const fileInput = document.querySelector("#employee-profile-image-file");
    const file = fileInput.files[0];
    if (!file || !["image/jpeg", "image/png", "image/webp"].includes(file.type) || file.size > 10 * 1024 * 1024) {
      setResult("请选择不超过 10 MB 的 JPEG、PNG 或 WebP 图片", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    try {
      const task = await requestGame(`/api/game/users/${platformId}/profile-image`, {method: "POST", body: form});
      document.querySelector("#employee-profile-image-status").textContent = "上传状态：pending";
      void pollEmployeeProfileImage(task.id);
    } catch (error) {
      setResult(`形象上传失败（${error.message}）`, "error");
    }
    return;
  }
  if (event.target.id === "clear-employee-profile-image") {
    try {
      const profile = await requestGame(`/api/game/users/${platformId}/profile-image`, {method: "DELETE"});
      renderEmployeeProfileImage(profile.profile_image_url, null);
      setResult("档案形象已清除", "success");
    } catch (error) {
      setResult(`清除失败（${error.message}）`, "error");
    }
    return;
  }
  if (event.target.id !== "save-employee-profile") return;
  try {
    await runMutation(event.target, "保存中…", async () => {
      const profile = await requestGame(`/api/game/users/${platformId}/profile`, {
        method: "PUT",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({profile_text: document.querySelector("#employee-profile-text").value}),
      });
      renderEmployeeProfileImage(profile.profile_image_url, null);
      closeEmployeeProfileModal();
    });
    setResult("员工档案已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
activitySettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-activity-settings-modal]")) {
    closeActivitySettingsModal();
    return;
  }
  if (event.target.closest("[data-remove-income-report-time]")) {
    activitySettings.report_times.splice([...incomeReportTimeInputs.querySelectorAll("[data-remove-income-report-time]")].indexOf(event.target.closest("[data-remove-income-report-time]")), 1);
    renderActivitySettingsInputs();
    return;
  }
  if (event.target.id === "add-income-report-time") {
    activitySettings.report_times.push("12:00");
    renderActivitySettingsInputs();
    return;
  }
  if (event.target.id !== "save-activity-settings-modal") return;
  const rules = [...activityRuleInputs.querySelectorAll(".activity-rule-row")].map((row, index) => ({
    level: index + 1,
    character_threshold: Number(row.querySelector("[data-activity-threshold]").value),
    reward: Number(row.querySelector("[data-activity-reward]").value),
  }));
  const report_times = [...incomeReportTimeInputs.querySelectorAll("[data-income-report-time]")].map((input) => input.value);
  if (!report_times.length || new Set(report_times).size !== report_times.length || report_times.some((value) => !value)) {
    setResult("请至少保留一个不重复的推送时段", "error");
    return;
  }
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      activitySettings = await requestGame("/api/game/activity-settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({rules, report_times}),
      });
      configurationVersion = activitySettings.version;
      renderActivitySettings(activitySettings);
      closeActivitySettingsModal();
    });
    setResult("日活跃度规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
numberBombSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-number-bomb-settings-modal]")) {
    closeNumberBombSettingsModal();
    return;
  }
  if (event.target.id !== "save-number-bomb-settings") return;
  const signup_timeout_minutes = Number(numberBombSignupMinutes.value);
  const reminder_interval_seconds = Number(numberBombReminderSeconds.value);
  if (!Number.isInteger(signup_timeout_minutes) || signup_timeout_minutes < 1 || signup_timeout_minutes > 60) {
    setResult("报名超时必须为 1–60 分钟", "error");
    return;
  }
  if (!Number.isInteger(reminder_interval_seconds) || reminder_interval_seconds < 5 || reminder_interval_seconds > 300) {
    setResult("提醒间隔必须为 5–300 秒", "error");
    return;
  }
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      numberBombSettings = await requestGame("/api/game/number-bomb/settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          enabled: numberBombEnabled.checked,
          signup_timeout_minutes,
          reminder_interval_seconds,
        }),
      });
      configurationVersion = numberBombSettings.version;
      renderNumberBombSettings(numberBombSettings);
      closeNumberBombSettingsModal();
    });
    setResult("蹦蹦数字炸弹设置已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
redPacketSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-red-packet-settings-modal]")) {
    closeRedPacketSettingsModal();
    return;
  }
  if (event.target.id !== "save-red-packet-settings") return;
  const expiry_minutes = Number(redPacketExpiryMinutes.value);
  const empty_probability_percent = Number(redPacketEmptyProbability.value);
  if (!Number.isInteger(expiry_minutes) || expiry_minutes < 1 || expiry_minutes > 60) {
    setResult("红包过期时间必须为 1–60 分钟", "error");
    return;
  }
  if (!Number.isInteger(empty_probability_percent) || empty_probability_percent < 0 || empty_probability_percent > 30) {
    setResult("空包概率必须为 0–30%", "error");
    return;
  }
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      redPacketSettings = await requestGame("/api/game/red-packet/settings", {
        method: "PATCH",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({expiry_minutes, empty_probability_percent}),
      });
      configurationVersion = redPacketSettings.version;
      renderRedPacketSettings(redPacketSettings);
      closeRedPacketSettingsModal();
    });
    setResult("随机运气红包设置已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#gameplay-current-card").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-force-end-game]");
  if (!button) return;
  const {groupChatId, gameType, gameId} = button.dataset;
  if (!window.confirm(`确认强制结束${gameType === "number_bomb" ? "蹦蹦数字炸弹" : "当前游戏"}？`)) return;
  try {
    await runMutation(button, "结束中…", async () => {
      const ended = await requestGame(
        `/api/gameplay/${encodeURIComponent(groupChatId)}/${encodeURIComponent(gameType)}/${encodeURIComponent(gameId)}/force-end`,
        {
          method: "POST",
          headers: {
            "If-Match": String(gameplayVersion),
            "Idempotency-Key": idempotencyKey(),
          },
        },
      );
      gameplayVersion = ended.version;
      await loadCurrentGameplay();
    });
    setResult("当前游戏已强制结束", "success");
  } catch (error) {
    setResult(`强制结束失败（${error.message}）`, "error");
  }
});
randomEventSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-random-event-settings-modal]")) {
    closeRandomEventSettingsModal();
    return;
  }
  if (event.target.id === "add-random-event-time") {
    renderRandomEventTime();
    return;
  }
  if (event.target.closest("[data-remove-random-event-time]")) {
    event.target.closest(".income-report-time-row").remove();
    return;
  }
  const signupVariable = event.target.closest("[data-random-event-signup-variable]");
  if (signupVariable) {
    const input = document.querySelector("#random-event-signup-notice");
    input.setRangeText(signupVariable.dataset.randomEventSignupVariable, input.selectionStart, input.selectionEnd, "end");
    input.focus();
    return;
  }
  if (event.target.id !== "save-random-event-settings") return;
  const button = event.target;
  const settings = {
    schedule_times: [...randomEventTimeInputs.querySelectorAll("[data-random-event-time]")].map((input) => input.value).filter(Boolean),
    signup_notice_template: document.querySelector("#random-event-signup-notice").value.trim(),
    signup_timeout_minutes: Number(document.querySelector("#random-event-signup-timeout").value),
    reminder_interval_minutes: Number(document.querySelector("#random-event-reminder-interval").value),
    tipping_duration_seconds: Number(document.querySelector("#random-event-tipping-duration").value),
    signup_allowed_commands: [...randomEventSettingsModal.querySelectorAll("[data-random-event-signup-command]:checked")].map((input) => input.value),
    in_progress_allowed_commands: [...randomEventSettingsModal.querySelectorAll("[data-random-event-progress-command]:checked")].map((input) => input.value),
    blocked_message: document.querySelector("#random-event-blocked-message").value.trim(),
    submission_enabled: document.querySelector("#random-event-submission-enabled").checked,
    submission_draft_timeout_minutes: Number(document.querySelector("#random-event-submission-timeout").value),
    submission_max_participants: Number(document.querySelector("#random-event-submission-max-participants").value),
    submission_default_target_rounds: Number(document.querySelector("#random-event-submission-target-rounds").value),
    submission_default_event_reward: Number(document.querySelector("#random-event-submission-event-reward").value),
    submission_approval_reward: Number(document.querySelector("#random-event-submission-approval-reward").value),
  };
  if (!settings.schedule_times.length || !settings.signup_notice_template || !settings.blocked_message) {
    setResult("请至少设置一个触发时刻、报名补充说明和拦截提示", "error");
    return;
  }
  try {
    await runMutation(button, "保存中…", async () => {
      randomEventSettings = await requestGame("/api/game/random-events/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = randomEventSettings.version;
      renderRandomEventSettings(randomEventSettings);
      closeRandomEventSettingsModal();
    });
    setResult("随机事件规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
randomEventSceneModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-random-event-scene-modal]")) {
    closeRandomEventSceneModal();
    return;
  }
  if (event.target.id === "add-random-event-scene-seat") {
    renderRandomEventSceneSeat();
    return;
  }
  if (event.target.id === "add-random-event-scene-opening") {
    renderRandomEventSceneOpening();
    return;
  }
  if (event.target.closest("[data-remove-random-event-seat]")) {
    event.target.closest(".scene-seat-row").remove();
    renderRandomEventSceneOpeningVariables();
    return;
  }
  if (event.target.closest("[data-remove-random-event-opening]")) {
    event.target.closest(".scene-opening-row").remove();
    return;
  }
  const roleVariable = event.target.closest("[data-random-event-role-variable]");
  if (roleVariable) {
    insertRandomEventRoleVariable(roleVariable.dataset.randomEventRoleVariable);
    return;
  }
  if (event.target.id !== "save-random-event-scene") return;
  const name = document.querySelector("#random-event-scene-name").value.trim();
  const signupText = document.querySelector("#random-event-scene-signup").value.trim();
  const events = [...randomEventSceneOpenings.querySelectorAll(".scene-opening-row")].map((row) => ({
    name: row.querySelector("[data-random-event-name]").value.trim(),
    opening_text: row.querySelector("[data-random-event-formal-opening]").value.trim(),
  }));
  if (!name || !signupText || !events.length || events.some((item) => !item.name || !item.opening_text)) {
    setResult("请填写场景名称、报名公告和每个事件的名称、开场白", "error");
    return;
  }
  const seats = [...randomEventSceneSeats.querySelectorAll(".scene-seat-row")].map((row) => ({
    role: row.querySelector("[data-random-event-role]").value.trim(),
    capacity: Number(row.querySelector("[data-random-event-capacity]").value),
  }));
  if (!seats.length || seats.some((seat) => !seat.role || !seat.capacity)) {
    setResult("请至少设置一个有效角色席位", "error");
    return;
  }
  const button = event.target;
  try {
    const sceneId = randomEventSceneModal.dataset.sceneId;
    await runMutation(button, sceneId ? "保存中…" : "创建中…", async () => {
      const created = await requestGame(
        sceneId ? `/api/game/random-events/scenes/${sceneId}` : "/api/game/random-events/scenes",
        {
        method: sceneId ? "PUT" : "POST", headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          name,
          signup_text: signupText,
          events,
          target_rounds: Number(document.querySelector("#random-event-scene-rounds").value),
          reward: Number(document.querySelector("#random-event-scene-reward").value), seats,
          ...(sceneId ? {enabled: randomEventSceneModal.dataset.enabled === "true"} : {}),
        }),
      });
      configurationVersion = created.version;
      closeRandomEventSceneModal();
      await loadRandomEvents();
    });
    setResult(sceneId ? "随机事件场景已保存" : "随机事件场景已创建", "success");
  } catch (error) {
    setResult(
      error.message === "场景名称已存在"
        ? "场景已存在，请直接编辑现有场景。"
        : `创建失败（${error.message}）`,
      "error",
    );
  }
});
randomEventSceneModal.addEventListener("input", (event) => {
  if (event.target.matches("[data-random-event-role]")) {
    renderRandomEventSceneOpeningVariables();
  }
});
randomEventSceneModal.addEventListener("focusin", (event) => {
  if (event.target.matches("[data-random-event-formal-opening]")) {
    randomEventSceneOpeningTarget = event.target;
  }
});
document.querySelector("#random-event-scene-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-scene-action]");
  if (!button) return;
  const scene = JSON.parse(button.dataset.randomEventScene);
  if (button.dataset.sceneAction === "edit") {
    openRandomEventSceneModal(scene);
    return;
  }
  if (button.dataset.sceneAction === "delete" && !window.confirm(`确定删除场景“${scene.name}”？`)) return;
  const deletion = button.dataset.sceneAction === "delete";
  const payload = {...scene, enabled: deletion ? scene.enabled : !scene.enabled};
  try {
    await runMutation(button, deletion ? "删除中…" : "保存中…", async () => {
      const updated = await requestGame(`/api/game/random-events/scenes/${scene.id}`, {
        method: deletion ? "DELETE" : "PUT",
        headers: configurationHeaders(),
        ...(deletion ? {} : {headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(payload)}),
      });
      configurationVersion = updated.version;
      await loadRandomEvents();
    });
    setResult(deletion ? "场景已删除" : `场景已${scene.enabled ? "停用" : "启用"}`, "success");
  } catch (error) {
    setResult(`更新失败（${error.message}）`, "error");
  }
});
document.querySelector("#random-event-add-scene").addEventListener("change", renderRandomEventAddTemplates);
randomEventAddModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-random-event-add-modal]")) {
    closeRandomEventAddModal();
    return;
  }
  if (event.target.id !== "save-random-event-add") return;
  const scheduledAt = document.querySelector("#random-event-add-scheduled-at").value;
  if (!scheduledAt) {
    setResult("请选择今日未来的开始时间", "error");
    return;
  }
  const button = event.target;
  try {
    await runMutation(button, "补充中…", async () => {
      const created = await requestGame("/api/game/random-events/today", {
        method: "POST", headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          group_chat_id: document.querySelector("#random-event-add-group").value,
          scene_id: document.querySelector("#random-event-add-scene").value,
          event_name: document.querySelector("#random-event-add-template").value,
          scheduled_at: `${scheduledAt}:00+08:00`,
        }),
      });
      configurationVersion = created.version;
      closeRandomEventAddModal();
      await loadRandomEvents();
    });
    setResult("今日随机事件已补充", "success");
  } catch (error) {
    setResult(`补充失败（${error.message}）`, "error");
  }
});
document.querySelector("#today-random-event-list").addEventListener("click", async (event) => {
  const adjustButton = event.target.closest("button[data-adjust-random-event]");
  if (adjustButton) {
    openRandomEventTimeModal(adjustButton);
    return;
  }
  const detailButton = event.target.closest("button[data-view-random-event-details]");
  if (detailButton) {
    try {
      await openRandomEventDetailsModal(detailButton.dataset.viewRandomEventDetails);
    } catch (error) {
      setResult(`获取详情失败（${error.message}）`, "error");
    }
    return;
  }
  const triggerButton = event.target.closest("button[data-trigger-random-event]");
  const deleteButton = event.target.closest("button[data-delete-random-event]");
  if (deleteButton) {
    if (!window.confirm("确定移除这个待开始事件吗？")) return;
    try {
      await runMutation(deleteButton, "移除中…", async () => {
        const removed = await requestGame(`/api/game/random-events/today/${deleteButton.dataset.deleteRandomEvent}`, {
          method: "DELETE", headers: configurationHeaders(),
        });
        configurationVersion = removed.version;
        await loadRandomEvents();
      });
      setResult("今日随机事件已移除", "success");
    } catch (error) {
      setResult(`移除失败（${error.message}）`, "error");
    }
    return;
  }
  if (!triggerButton) return;
  try {
    await runMutation(triggerButton, "触发中…", async () => {
      const updated = await requestGame(`/api/game/random-events/today/${triggerButton.dataset.triggerRandomEvent}/trigger`, {
        method: "POST", headers: configurationHeaders(),
      });
      configurationVersion = updated.version;
      await loadRandomEvents();
    });
    setResult("随机事件已开始报名", "success");
  } catch (error) {
    setResult(`立即触发失败（${error.message}）`, "error");
  }
});
document.querySelector("#random-event-submission-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-random-event-submission-id]");
  if (!button) return;
  try {
    await runMutation(button, "加载中…", () => openRandomEventSubmissionModal(button.dataset.randomEventSubmissionId));
  } catch (error) {
    setResult(`读取投稿失败（${error.message}）`, "error");
  }
});
randomEventSubmissionModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-random-event-submission-modal]")) {
    closeRandomEventSubmissionModal();
    return;
  }
  if (event.target.id === "add-random-event-submission-role") {
    renderRandomEventSubmissionRole();
    return;
  }
  if (event.target.id === "add-random-event-submission-event") {
    renderRandomEventSubmissionEvent();
    return;
  }
  const removeRole = event.target.closest("[data-remove-submission-role]");
  if (removeRole) {
    removeRole.closest(".scene-seat-row").remove();
    return;
  }
  const removeEvent = event.target.closest("[data-remove-submission-event]");
  if (removeEvent) {
    removeEvent.closest(".scene-opening-row").remove();
    return;
  }
  const submissionId = randomEventSubmissionModal.dataset.submissionId;
  if (!submissionId) return;
  const button = event.target.closest("#save-random-event-submission, #approve-random-event-submission, #reject-random-event-submission");
  if (!button) return;
  try {
    await runMutation(button, "处理中…", async () => {
      if (button.id === "save-random-event-submission") {
        await requestGame(`/api/game/random-events/submissions/${submissionId}`, {
          method: "PATCH",
          headers: {"Content-Type": "application/json", "Idempotency-Key": idempotencyKey()},
          body: JSON.stringify({content: randomEventSubmissionContentFromModal()}),
        });
        setResult("投稿修改已保存", "success");
        await openRandomEventSubmissionModal(submissionId);
        return;
      }
      if (button.id === "approve-random-event-submission") {
        await requestGame(`/api/game/random-events/submissions/${submissionId}/approve`, {
          method: "POST", headers: {"Idempotency-Key": idempotencyKey()},
        });
        setResult("投稿已通过，场景与奖励已生效", "success");
      } else {
        const reason = document.querySelector("#random-event-submission-rejection-reason").value.trim();
        if (!reason) throw new Error("请填写拒绝原因");
        await requestGame(`/api/game/random-events/submissions/${submissionId}/reject`, {
          method: "POST",
          headers: {"Content-Type": "application/json", "Idempotency-Key": idempotencyKey()},
          body: JSON.stringify({reason}),
        });
        setResult("投稿已拒绝", "success");
      }
      closeRandomEventSubmissionModal();
      await loadRandomEventSubmissions();
    });
  } catch (error) {
    setResult(`审核操作失败（${error.message}）`, "error");
  }
});
randomEventDetailsModal.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-random-event-details-modal]")) randomEventDetailsModal.hidden = true;
});
randomEventTimeModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-random-event-time-modal]")) {
    closeRandomEventTimeModal();
    return;
  }
  if (event.target.id !== "save-random-event-time") return;
  const scheduledAt = document.querySelector("#random-event-scheduled-at").value;
  if (!scheduledAt) return;
  const button = event.target;
  try {
    await runMutation(button, "保存中…", async () => {
      const updated = await requestGame(`/api/game/random-events/today/${randomEventTimeModal.dataset.scheduleId}`, {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({scheduled_at: `${scheduledAt}:00+08:00`}),
      });
      configurationVersion = updated.version;
      closeRandomEventTimeModal();
      await loadRandomEvents();
    });
    setResult("今日事件时间已调整", "success");
  } catch (error) {
    setResult(`调整失败（${error.message}）`, "error");
  }
});
hideAndSeekSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-hide-and-seek-settings-modal]")) {
    closeHideAndSeekSettingsModal();
    return;
  }
  if (event.target.id !== "save-hide-and-seek-settings") return;
  const button = event.target;
  const settings = {
    enabled: document.querySelector("#hide-and-seek-enabled").checked,
    entry_fee: Number(document.querySelector("#hide-and-seek-entry-fee").value),
    win_reward: Number(document.querySelector("#hide-and-seek-win-reward").value),
    daily_limit: Number(document.querySelector("#hide-and-seek-daily-limit").value),
    selection_timeout_minutes: Number(document.querySelector("#hide-and-seek-timeout").value),
  };
  try {
    await runMutation(button, "保存中…", async () => {
      hideAndSeekSettings = await requestGame("/api/game/hide-and-seek/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = hideAndSeekSettings.version;
      renderHideAndSeekSettings(hideAndSeekSettings);
      closeHideAndSeekSettingsModal();
    });
    setResult("躲猫猫规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
memoryAssessmentSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-memory-assessment-settings-modal]")) {
    closeMemoryAssessmentSettingsModal();
    return;
  }
  if (event.target.id !== "save-memory-assessment-settings") return;
  const levels = document.querySelector("#memory-assessment-levels").value.trim().split("\n").filter(Boolean).map((line, index) => {
    const [answerLength, reward] = line.split(",").map((value) => Number(value.trim()));
    return {level: index + 1, answer_length: answerLength, reward};
  });
  const settings = {
    enabled: document.querySelector("#memory-assessment-enabled").checked,
    single_daily_limit: Number(document.querySelector("#memory-assessment-daily-limit").value),
    single_recall_seconds: Number(document.querySelector("#memory-assessment-single-seconds").value),
    duel_recall_seconds: Number(document.querySelector("#memory-assessment-duel-seconds").value),
    duel_difficulty_level: Number(document.querySelector("#memory-assessment-duel-level").value),
    duel_base_pool: Number(document.querySelector("#memory-assessment-base-pool").value),
    duel_wrong_freeze: Number(document.querySelector("#memory-assessment-wrong-freeze").value),
    duel_wrong_limit: Number(document.querySelector("#memory-assessment-wrong-limit").value),
    duel_signup_timeout_minutes: Number(document.querySelector("#memory-assessment-signup-timeout").value),
    duel_answer_timeout_minutes: Number(document.querySelector("#memory-assessment-timeout").value),
    character_set: document.querySelector("#memory-assessment-character-set").value,
    levels,
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      memoryAssessmentSettings = await requestGame("/api/game/memory-assessment/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = memoryAssessmentSettings.version;
      renderMemoryAssessmentSettings(memoryAssessmentSettings);
      closeMemoryAssessmentSettingsModal();
    });
    setResult("记忆考核规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
undercoverSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-undercover-settings-modal]")) {
    closeUndercoverSettingsModal();
    return;
  }
  if (event.target.id !== "save-undercover-settings") return;
  const roles = [...document.querySelectorAll(".undercover-role-row")].map((row) => ({
    player_count: Number(row.dataset.playerCount),
    civilian_count: Number(row.querySelector("[data-undercover-civilian]").value),
    undercover_count: Number(row.querySelector("[data-undercover-undercover]").value),
    whiteboard_count: Number(row.querySelector("[data-undercover-whiteboard]").value),
  }));
  const settings = {
    enabled: document.querySelector("#undercover-enabled").checked,
    vote_seconds: Number(document.querySelector("#undercover-vote-seconds").value),
    signup_timeout_minutes: Number(document.querySelector("#undercover-signup-timeout").value),
    whiteboard_win_remaining: Number(document.querySelector("#undercover-whiteboard-threshold").value),
    roles,
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      undercoverSettings = await requestGame("/api/game/undercover/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = undercoverSettings.version;
      renderUndercoverSettings(undercoverSettings);
      closeUndercoverSettingsModal();
    });
    setResult("谁是卧底规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
blameBombSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-blame-bomb-settings-modal]")) {
    closeBlameBombSettingsModal();
    return;
  }
  if (event.target.id !== "save-blame-bomb-settings") return;
  const durations = [...document.querySelectorAll("#blame-bomb-duration-inputs .undercover-role-row")].map((row) => ({
    player_count: Number(row.dataset.playerCount),
    minimum_seconds: Number(row.querySelector("[data-blame-minimum]").value),
    maximum_seconds: Number(row.querySelector("[data-blame-maximum]").value),
  }));
  const settings = {
    enabled: document.querySelector("#blame-bomb-enabled").checked,
    signup_timeout_seconds: Number(document.querySelector("#blame-bomb-signup-seconds").value),
    turn_timeout_seconds: Number(document.querySelector("#blame-bomb-turn-seconds").value),
    durations,
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      blameBombSettings = await requestGame("/api/game/blame-bomb/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = blameBombSettings.version;
      closeBlameBombSettingsModal();
      await loadBlameBomb();
    });
    setResult("甩锅游戏规则已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
blameIncidentModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-blame-incident-modal]")) {
    closeBlameIncidentModal();
    return;
  }
  if (event.target.id !== "save-blame-incident") return;
  const incidentId = blameIncidentModal.dataset.incidentId;
  const keywords = document.querySelector("#blame-incident-keywords").value
    .split("\n").map((value) => value.trim()).filter(Boolean);
  const incident = {
    name: document.querySelector("#blame-incident-name").value.trim(),
    description: document.querySelector("#blame-incident-description").value.trim(),
    keywords,
    ...(incidentId ? {enabled: document.querySelector("#blame-incident-enabled").checked} : {}),
  };
  try {
    await runMutation(event.target, incidentId ? "保存中…" : "创建中…", async () => {
      const saved = await requestGame(
        incidentId ? `/api/game/blame-bomb/incidents/${incidentId}` : "/api/game/blame-bomb/incidents",
        {method: incidentId ? "PUT" : "POST", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(incident)},
      );
      configurationVersion = saved.version;
      closeBlameIncidentModal();
      await loadBlameBomb();
    });
    setResult(incidentId ? "事故卡已保存" : "事故卡已创建", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#blame-incident-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-blame-incident-action]");
  if (!button) return;
  const incident = JSON.parse(button.dataset.blameIncident);
  if (button.dataset.blameIncidentAction === "edit") {
    openBlameIncidentModal(incident);
    return;
  }
  const deletion = button.dataset.blameIncidentAction === "delete";
  if (deletion && !window.confirm(`确定删除事故卡“${incident.name}”？`)) return;
  try {
    await runMutation(button, deletion ? "删除中…" : "保存中…", async () => {
      const result = await requestGame(`/api/game/blame-bomb/incidents/${incident.id}`, {
        method: deletion ? "DELETE" : "PUT",
        ...(deletion
          ? {headers: configurationHeaders()}
          : {headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify({...incident, enabled: !incident.enabled})}),
      });
      configurationVersion = result.version;
      await loadBlameBomb();
    });
    setResult(deletion ? "事故卡已删除" : `事故卡已${incident.enabled ? "停用" : "启用"}`, "success");
  } catch (error) {
    setResult(`更新失败（${error.message}）`, "error");
  }
});
document.querySelector("#end-blame-bomb-session").addEventListener("click", async (event) => {
  if (!window.confirm("确定强制结束当前甩锅游戏并退回全部保证金？")) return;
  try {
    await runMutation(event.currentTarget, "结束中…", async () => {
      const result = await requestGame("/api/game/blame-bomb/end", {method: "POST"});
      if (!result.accepted) throw new Error("当前没有可结束的甩锅游戏");
      await loadBlameBomb();
    });
    setResult("当前甩锅游戏已处理", "success");
  } catch (error) {
    setResult(`结束失败（${error.message}）`, "error");
  }
});
aiAssistantSettingsModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-ai-assistant-settings-modal]")) {
    closeAiAssistantSettingsModal();
    return;
  }
  if (event.target.id !== "save-ai-assistant-settings") return;
  const settings = {
    enabled: document.querySelector("#ai-assistant-enabled").checked,
    persona: document.querySelector("#ai-assistant-persona").value,
    system_prompt: document.querySelector("#ai-assistant-system-prompt").value,
    over_limit_reply: document.querySelector("#ai-assistant-over-limit-reply").value,
    failure_reply: document.querySelector("#ai-assistant-failure-reply").value,
    max_response_chars: Number(document.querySelector("#ai-assistant-max-chars").value),
    timeout_seconds: Number(document.querySelector("#ai-assistant-timeout").value),
    memory_enabled: document.querySelector("#ai-memory-enabled").checked,
    extraction_prompt: document.querySelector("#ai-memory-extraction-prompt").value,
    history_limit: aiAssistantSettings.history_limit,
    max_memory_chars: aiAssistantSettings.max_memory_chars,
    batch_message_threshold: Number(document.querySelector("#ai-memory-batch-threshold").value),
    max_entries_per_category: Number(document.querySelector("#ai-memory-max-entries").value),
    candidate_expiry_days: Number(document.querySelector("#ai-memory-candidate-expiry-days").value),
    quotas: aiAssistantSettings.quotas.map((quota) => ({
      rank_id: quota.rank_id,
      daily_limit: Number(document.querySelector(`[data-ai-quota="${quota.rank_id}"]`).value),
    })),
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      aiAssistantSettings = await requestGame("/api/ai-assistant/settings", {
        method: "PATCH", headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify(settings),
      });
      configurationVersion = aiAssistantSettings.version;
      renderAiAssistantSettings(aiAssistantSettings);
      closeAiAssistantSettingsModal();
    });
    setResult("AI 总监事配置已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#ai-knowledge-card-list").addEventListener("click", async (event) => {
  const row = event.target.closest("[data-ai-knowledge-card-id]");
  if (!row) return;
  const card = aiKnowledgeCards.find((item) => String(item.id) === row.dataset.aiKnowledgeCardId);
  if (!card) return;
  if (event.target.closest("[data-edit-ai-knowledge-card]")) {
    openAiKnowledgeCardModal(card);
    return;
  }
  const deleting = Boolean(event.target.closest("[data-delete-ai-knowledge-card]"));
  const toggling = Boolean(event.target.closest("[data-toggle-ai-knowledge-card]"));
  if (!deleting && !toggling) return;
  if (deleting && !window.confirm(`确认删除知识卡“${card.title}”？`)) return;
  try {
    await runMutation(event.target.closest("button"), "处理中…", async () => {
      const result = await requestGame(`/api/ai-knowledge-cards/${card.id}`, deleting ? {
        method: "DELETE", headers: configurationHeaders(),
      } : {
        method: "PUT", headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          topic: card.topic, title: card.title, keywords: card.keywords,
          content: card.content, enabled: !card.enabled, priority: card.priority,
        }),
      });
      configurationVersion = result.version;
      await reloadAiKnowledgeCards();
    });
    setResult(deleting ? "知识卡已删除" : `知识卡已${card.enabled ? "停用" : "启用"}`, "success");
  } catch (error) {
    setResult(`知识卡操作失败（${error.message}）`, "error");
  }
});
aiKnowledgeCardModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-ai-knowledge-card-modal]")) {
    closeAiKnowledgeCardModal();
    return;
  }
  if (event.target.id !== "save-ai-knowledge-card") return;
  const cardId = aiKnowledgeCardModal.dataset.cardId;
  const payload = {
    topic: document.querySelector("#ai-knowledge-card-topic").value,
    title: document.querySelector("#ai-knowledge-card-title").value.trim(),
    keywords: document.querySelector("#ai-knowledge-card-keywords").value.split("\n").map((value) => value.trim()).filter(Boolean),
    content: document.querySelector("#ai-knowledge-card-content").value.trim(),
    enabled: document.querySelector("#ai-knowledge-card-enabled").checked,
    priority: Number(document.querySelector("#ai-knowledge-card-priority").value),
  };
  try {
    await runMutation(event.target, "保存中…", async () => {
      const result = await requestGame(cardId ? `/api/ai-knowledge-cards/${cardId}` : "/api/ai-knowledge-cards", {
        method: cardId ? "PUT" : "POST",
        headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify(payload),
      });
      configurationVersion = result.version;
      closeAiKnowledgeCardModal();
      await reloadAiKnowledgeCards();
    });
    setResult("知识卡已保存", "success");
  } catch (error) {
    setResult(`保存失败（${error.message}）`, "error");
  }
});
employeeMemoryModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-employee-memory-modal]")) {
    closeEmployeeMemoryModal();
    return;
  }
  const platformId = employeeMemoryModal.dataset.platformId;
  if (event.target.id === "add-employee-impression") {
    const category = document.querySelector("#employee-memory-new-category").value;
    const content = document.querySelector("#employee-memory-new-content").value.trim();
    if (!content) {
      setResult("请填写稳定印象内容", "error");
      return;
    }
    try {
      await runMutation(event.target, "新增中…", async () => {
        const created = await requestGame(`/api/game/users/${platformId}/ai-impressions`, {
          method: "POST",
          headers: {"Content-Type": "application/json", ...configurationHeaders()},
          body: JSON.stringify({category, content}),
        });
        configurationVersion = created.version;
        document.querySelector("#employee-memory-new-content").value = "";
        await refreshEmployeeMemory();
      });
      setResult("稳定印象已新增并固定", "success");
    } catch (error) {
      setResult(`新增失败（${error.message}）`, "error");
    }
    return;
  }
  if (event.target.id === "clear-employee-memory") {
    if (!window.confirm("确认清空该玩家的稳定印象和候选？旧版备份会保留。")) return;
    try {
      await runMutation(event.target, "清空中…", async () => {
        const updated = await requestGame(`/api/game/users/${platformId}/ai-memory`, {
          method: "DELETE", headers: configurationHeaders(),
        });
        configurationVersion = updated.version;
        await refreshEmployeeMemory();
      });
      setResult("玩家稳定印象和候选已清空", "success");
    } catch (error) {
      setResult(`清空失败（${error.message}）`, "error");
    }
    return;
  }
  const actionButton = event.target.closest("[data-impression-edit], [data-impression-pin], [data-impression-delete]");
  if (!actionButton) return;
  const entryId = actionButton.dataset.impressionEdit || actionButton.dataset.impressionPin || actionButton.dataset.impressionDelete;
  const entry = currentEmployeeMemory?.impressions.find((item) => String(item.id) === entryId);
  if (!entry) return;
  if (actionButton.dataset.impressionDelete && !window.confirm(`确认删除“${entry.content}”？`)) return;
  let content = entry.content;
  if (actionButton.dataset.impressionEdit) {
    const edited = window.prompt("编辑稳定印象", entry.content);
    if (edited === null) return;
    content = edited.trim();
    if (!content) {
      setResult("稳定印象内容不能为空", "error");
      return;
    }
  }
  try {
    await runMutation(actionButton, "处理中…", async () => {
      const deleting = Boolean(actionButton.dataset.impressionDelete);
      const updated = await requestGame(`/api/game/users/${platformId}/ai-impressions/${entryId}`, deleting ? {
        method: "DELETE", headers: configurationHeaders(),
      } : {
        method: "PUT", headers: {"Content-Type": "application/json", ...configurationHeaders()},
        body: JSON.stringify({
          category: entry.category,
          content,
          pinned: actionButton.dataset.impressionPin ? !entry.pinned : entry.pinned,
        }),
      });
      configurationVersion = updated.version;
      await refreshEmployeeMemory();
    });
    setResult(actionButton.dataset.impressionDelete ? "稳定印象已删除" : "稳定印象已更新", "success");
  } catch (error) {
    setResult(`操作失败（${error.message}）`, "error");
  }
});
hideAndSeekSceneModal.addEventListener("click", async (event) => {
  if (event.target.closest("[data-close-hide-and-seek-scene-modal]")) {
    closeHideAndSeekSceneModal();
    return;
  }
  if (event.target.id !== "save-hide-and-seek-scene") return;
  const name = document.querySelector("#hide-and-seek-scene-name").value.trim();
  if (!name) {
    setResult("请填写地点名称", "error");
    return;
  }
  const button = event.target;
  const sceneId = hideAndSeekSceneModal.dataset.sceneId;
  try {
    await runMutation(button, sceneId ? "保存中…" : "创建中…", async () => {
      const scene = await requestGame(
        sceneId ? `/api/game/hide-and-seek/scenes/${sceneId}` : "/api/game/hide-and-seek/scenes",
        {
          method: sceneId ? "PUT" : "POST",
          headers: {"Content-Type": "application/json", ...configurationHeaders()},
          body: JSON.stringify({name, ...(sceneId ? {enabled: hideAndSeekSceneModal.dataset.enabled === "true"} : {})}),
        },
      );
      configurationVersion = scene.version;
      closeHideAndSeekSceneModal();
      await loadHideAndSeek();
    });
    setResult(sceneId ? "躲猫猫地点已保存" : "躲猫猫地点已创建", "success");
  } catch (error) {
    setResult(error.message === "躲猫猫地点名称已存在" ? "地点已存在，请直接编辑现有地点。" : `保存失败（${error.message}）`, "error");
  }
});
document.querySelector("#hide-and-seek-scene-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-hide-and-seek-scene-action]");
  if (!button) return;
  const scene = JSON.parse(button.dataset.hideAndSeekScene);
  if (button.dataset.hideAndSeekSceneAction === "edit") {
    openHideAndSeekSceneModal(scene);
    return;
  }
  const deletion = button.dataset.hideAndSeekSceneAction === "delete";
  if (deletion && !window.confirm(`确定删除地点“${scene.name}”？`)) return;
  try {
    await runMutation(button, deletion ? "删除中…" : "保存中…", async () => {
      const updated = await requestGame(`/api/game/hide-and-seek/scenes/${scene.id}`, {
        method: deletion ? "DELETE" : "PUT",
        ...(deletion
          ? {headers: configurationHeaders()}
          : {headers: {"Content-Type": "application/json", ...configurationHeaders()}, body: JSON.stringify({...scene, enabled: !scene.enabled})}),
      });
      configurationVersion = updated.version;
      await loadHideAndSeek();
    });
    setResult(deletion ? "地点已删除" : `地点已${scene.enabled ? "停用" : "启用"}`, "success");
  } catch (error) {
    setResult(`更新失败（${error.message}）`, "error");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !groupChatModal.hidden) closeGroupChatModal();
  if (event.key === "Escape" && !employeeGroupMessagesModal.hidden) employeeGroupMessagesModal.hidden = true;
  if (event.key === "Escape" && !templateModal.hidden) closeTemplateModal();
  if (event.key === "Escape" && !settingsModal.hidden) closeSettingsModal();
  if (event.key === "Escape" && !profileSettingsModal.hidden) closeProfileSettingsModal();
  if (event.key === "Escape" && !employeeProfileModal.hidden) closeEmployeeProfileModal();
  if (event.key === "Escape" && !randomEventDetailsModal.hidden) randomEventDetailsModal.hidden = true;
  if (event.key === "Escape" && !activitySettingsModal.hidden) closeActivitySettingsModal();
  if (event.key === "Escape" && !numberBombSettingsModal.hidden) closeNumberBombSettingsModal();
  if (event.key === "Escape" && !randomEventSettingsModal.hidden) closeRandomEventSettingsModal();
  if (event.key === "Escape" && !randomEventSceneModal.hidden) closeRandomEventSceneModal();
  if (event.key === "Escape" && !randomEventTimeModal.hidden) closeRandomEventTimeModal();
  if (event.key === "Escape" && !randomEventAddModal.hidden) closeRandomEventAddModal();
  if (event.key === "Escape" && !hideAndSeekSettingsModal.hidden) closeHideAndSeekSettingsModal();
  if (event.key === "Escape" && !hideAndSeekSceneModal.hidden) closeHideAndSeekSceneModal();
  if (event.key === "Escape" && !blameBombSettingsModal.hidden) closeBlameBombSettingsModal();
  if (event.key === "Escape" && !blameIncidentModal.hidden) closeBlameIncidentModal();
  if (event.key === "Escape" && !aiAssistantSettingsModal.hidden) closeAiAssistantSettingsModal();
  if (event.key === "Escape" && !aiKnowledgeCardModal.hidden) closeAiKnowledgeCardModal();
  if (event.key === "Escape" && !employeeMemoryModal.hidden) closeEmployeeMemoryModal();
});
document.querySelector("#item-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  const button = event.currentTarget.querySelector("button[type=submit]");
  try {
    await runMutation(button, "上架中…", async () => {
      await requestGame("/api/game/items", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({...values, price: Number(values.price), stock: Number(values.stock)}),
      });
      event.currentTarget.reset();
      await loadShop(shopPage);
    });
    setResult("物品已上架", "success");
  } catch (error) {
    setResult(`上架失败（${error.message}）`, "error");
  }
});

document.querySelector("#admin-account-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  const values = Object.fromEntries(new FormData(event.currentTarget));
  try {
    await runMutation(button, "创建中…", async () => {
      await requestGame("/api/admins", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(values),
      });
      event.currentTarget.reset();
      await loadAdministrators();
    });
    setResult("管理员账号已创建", "success");
  } catch (error) {
    setResult(`创建失败（${error.message}）`, "error");
  }
});

document.querySelector("#admin-account-list").addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-admin-action]");
  if (!button) return;
  const {adminAction, adminId, adminActive} = button.dataset;
  let body;
  let method = "PATCH";
  if (adminAction === "toggle") body = {active: adminActive !== "true"};
  if (adminAction === "password") {
    const password = window.prompt("输入新密码（至少 8 位）");
    if (password === null) return;
    body = {password};
  }
  if (adminAction === "delete") {
    if (!window.confirm("确定删除该管理员账号？该操作会使其所有会话立即失效。")) return;
    method = "DELETE";
  }
  try {
    await runMutation(button, adminAction === "delete" ? "删除中…" : "保存中…", async () => {
      await requestGame(`/api/admins/${adminId}`, {
        method,
        ...(body ? {headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {}),
      });
      await loadAdministrators();
    });
    setResult("管理员账号已更新", "success");
  } catch (error) {
    setResult(`更新失败（${error.message}）`, "error");
  }
});

document.querySelectorAll("[data-open-memory-assessment-settings]").forEach((button) => {
  button.addEventListener("click", () => void openMemoryAssessmentSettingsModal());
});

initializeManagementTabs();
initializePageSizeControls();
initializeListFilters();

async function restoreIdentity() {
  if (identity || (!token && !adminSession)) return;
  const response = await fetch("/api/auth/me", {headers: headers()});
  if (!response.ok) return;
  identity = await response.json();
  sessionStorage.setItem("dzmm-admin-identity", JSON.stringify(identity));
  setAuthenticated(true);
}

setAuthenticated(Boolean(token || adminSession));
if (token || adminSession) {
  void restoreIdentity().then(refresh);
  window.setInterval(refresh, 10000);
}
window.setInterval(renderLoginLease, 1000);
