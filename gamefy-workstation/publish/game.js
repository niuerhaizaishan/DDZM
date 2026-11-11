"use strict";

(() => {
  const config = window.workstationConfig;
  const banner = document.getElementById("connection-state");
  const previewControls = document.getElementById("preview-controls");
  const previewSelect = document.getElementById("preview-equipment");
  const art = window.workstationArt;
  const displayNumber = number => ({6: 2, 7: 3, 8: 4, 9: 5}[number] || number);
  const demoComponents = art.categories.map(item => ({
    number: item.number, key: item.key, category: item.name, name: item.names[0], highest_level: 1, active_level: 1, equipped: true, daily_income: 0,
  }));

  function preview(number) {
    const level = number === 2 ? 5 : ({all: 10, starter: 5})[previewSelect.value] || 1;
    const components = demoComponents.map((item, index) => ({...item, name: art.categories[index].names[level - 1], highest_level: level, active_level: level,
      daily_income: (item.number <= 5 ? [0,1,2,3,5,8,10,15,20,25] : [0,2,5,10,15,20,25,30,35,40])[level - 1]}));
    const scene = {revision: art.revision, width: 1536, height: 1024, layers: art.order.map(key => ({key, level,
      filename: `growth-${art.revision}-${key}-lv${String(level).padStart(2, "0")}.png`}))};
    const income = components.reduce((sum, item) => sum + item.daily_income, 0);
    return {
      display_name: number === 2 ? "同事预览" : "预览", employee_number: number === 2 ? "#0002" : "#0001", equipped: [],
      daily_income: income,
      currency_name: "摸鱼币", income_settlement_enabled: false,
      progression: {components, equipped_count: 9, daily_income: income, scene,
        art_notice: "素材演示：画面按九类装备等级组合展示。"},
    };
  }

  function requestError(error) {
    return error.name === "TimeoutError"
      ? new Error("加载超时，请检查网络后重试；完整工位原图较大，请耐心等待。") : error;
  }

  let identityToken = null;
  let identityValidUntil = 0;
  let identityPending = null;
  let identityRetryAfter = 0;
  let identityFailure = null;

  async function platformToken() {
    if (identityToken && Date.now() < identityValidUntil) return identityToken;
    if (identityPending) return identityPending;
    if (Date.now() < identityRetryAfter) throw identityFailure;
    identityPending = (async () => {
      let timer;
      try {
        const identity = await Promise.race([
          window.dzmm.user.info(),
          new Promise((resolve, reject) => {
            timer = setTimeout(() => reject(new Error("登录信息读取超时，请稍后刷新游戏重试。")), 15000);
          }),
        ]);
        if (!identity?.token) {
          throw new Error(identity?.id
            ? "平台暂未提供登录凭证，可能已达请求上限，请稍后重新打开游戏。"
            : "请先登录 DZMM，再打开工位游戏。");
        }
        identityToken = identity.token;
        identityValidUntil = Date.now() + 5 * 60 * 1000;
        identityFailure = null;
        return identityToken;
      } catch (error) {
        identityFailure = error instanceof Error ? error : new Error("暂时无法读取登录信息，请稍后刷新游戏重试。");
        identityRetryAfter = Date.now() + 30000;
        throw identityFailure;
      } finally {
        clearTimeout(timer);
      }
    })();
    try { return await identityPending; }
    finally { identityPending = null; }
  }

  async function workstationRequest(path, options = {}, timeoutMs = 20000) {
    let endpoint;
    try {
      endpoint = new URL(config.apiBaseUrl);
      if (endpoint.protocol !== "https:" || endpoint.username || endpoint.password || endpoint.search || endpoint.hash) {
        throw new Error();
      }
    } catch {
      throw new Error("工位服务地址配置有误，请联系管理员。");
    }
    if (typeof window.dzmm?.user?.info !== "function") {
      throw new Error("请从 DZMM 平台打开工位游戏，以读取你的真实装备。");
    }
    const token = await platformToken();
    const controller = new AbortController();
    let timer;
    // Bound the full response, including JSON body transfer, even in sandboxes
    // whose fetch bridge does not reliably honor an AbortSignal.
    const deadline = new Promise((resolve, reject) => {
      timer = setTimeout(() => {
        reject(requestError({name: "TimeoutError"}));
        controller.abort();
      }, timeoutMs);
    });
    const request = async () => {
      const response = await fetch(`${endpoint.href.replace(/\/$/, "")}/api/gamefy/workstation${path}`, {
        ...options,
        headers: {Authorization: `Bearer ${token}`, ...(options.body ? {"Content-Type": "application/json"} : {})},
        credentials: "omit", cache: "no-store", signal: controller.signal,
      }).catch(error => { throw requestError(error); });
      if (!response.ok) {
        if (response.status === 401) {
          identityToken = null;
          identityValidUntil = 0;
        }
        const messages = {
          401: "登录信息已失效，请刷新游戏重新登录。",
          403: "请先在目标群发送 /工位游戏，再刷新本页（24小时内有效）。",
          404: "未找到员工档案或工位，请返回大厅刷新；尚未入职请回群里发送 /入职 名字。",
          409: "这次发送已选择其他群，请刷新后重试。",
          429: "发送过于频繁，请在一分钟后再试。",
          503: "工位服务暂时不可用，请稍后刷新重试。",
        };
        const detail = await response.json().catch(() => ({}));
        const actionError = ['/quote', '/actions', '/action-preview'].includes(path.split('?')[0]) && typeof detail.detail === 'string' && detail.detail.length <= 300;
        const error = new Error(actionError ? detail.detail : messages[response.status] || "服务暂不可用，请稍后重试。");
        error.status = response.status;
        throw error;
      }
      return response.json().catch(error => { throw requestError(error); });
    };
    try { return await Promise.race([request(), deadline]); }
    finally { clearTimeout(timer); }
  }

  async function readRealWorkstation(number) {
    const workstation = await workstationRequest(number ? `/employees/${number}` : "");
    banner.textContent = "已连接账号 · 小游戏与群聊共用余额和装备";
    return workstation;
  }

  const previewMode = config.apiBaseUrl === "";
  banner.textContent = previewMode
    ? "素材预览 · 尚未连接真实工位，以下是演示装备和预计收入"
    : "工位大厅 · 浏览同事的布置，也可以进入我的工位";
  previewControls.hidden = !previewMode;
  document.getElementById("page-note").textContent = previewMode
    ? "本页为素材预览，切换装备不会购买、扣币或改变真实工位。"
    : "在“我的养成”中升级和装卸；群内指令同步生效。发送图片到群里仅限自己的工位。";
  previewSelect.addEventListener("change", () => document.getElementById("refresh").click());
  window.workstationSource = Object.freeze({
    assetBase: previewMode ? "./assets/" : `${config.apiBaseUrl.replace(/\/$/, "")}/static/workstation/`,
    load: previewMode ? async number => ({...preview(number), is_owner: !number || number === 1}) : readRealWorkstation,
    lobby: previewMode ? async ({query, page}) => {
      const items = [
        {number: 1, display_name: "预览", employee_number: "#0001", asset_keys: [],
          equipped_count: 9, daily_income: 0},
        {number: 2, display_name: "同事预览", employee_number: "#0002", asset_keys: [], equipped_count: 9, daily_income: 85},
      ].filter(item => !query || item.display_name.includes(query) || item.employee_number.includes(query));
      return {items: page === 1 ? items : [], total: items.length, page, page_size: 24, my_number: 1};
    } : ({query, page}) => workstationRequest(`/lobby?${new URLSearchParams({query, page})}`),
    downloadRestricted: window.parent !== window,
    shop: previewMode ? async () => ({rank_name: "正式员工（演示）", level_cap: 2, balance: 30, upgrade_credit: 0,
      currency_name: "摸鱼币", items: demoComponents.map(item => ({...item, status: "available", next_level: 2,
        next_name: `基础${item.category}`, price: 20, credit_used: 0, cash_required: 20,
        next_daily_income: item.number <= 5 ? 1 : 2, income_delta: item.number <= 5 ? 1 : 2,
        next_description: "此处展示 Excel 中对应部件下一档的外观说明。", upgrade_command: `/升级 ${item.category}`}))})
      : () => workstationRequest("/shop"),
    ...(!previewMode ? {
      quote: action => workstationRequest('/quote?include_images=false', {method: 'POST', body: JSON.stringify(action)}),
      actionPreview: payload => workstationRequest('/action-preview', {method: 'POST', body: JSON.stringify(payload)}, 30000),
      apply: payload => workstationRequest('/actions', {method: 'POST', body: JSON.stringify(payload)}),
      share: payload => workstationRequest("/share", {method: "POST", body: JSON.stringify(payload)}),
      shareStatus: requestId => workstationRequest(`/shares/${encodeURIComponent(requestId)}`),
      image: number => workstationRequest(`/employees/${number}/image`, {}, 90000),
      preview: number => workstationRequest(`/employees/${number}/image?preview=true`, {}, 30000),
    } : {}),
    setLoading: loading => { previewSelect.disabled = loading; },
  });
})();
