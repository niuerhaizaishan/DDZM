let honorConfiguration = null;
let honorPreview = null;
let honorPeriodData = null;
let honorHistoryPage = 1;
let honorPeriodsPage = 1;
let employeeHonorRequestId = 0;

function honorMonday(offset = 0) {
  const parts = new Intl.DateTimeFormat("sv-SE", {timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
  const day = new Date(`${parts}T00:00:00Z`);
  day.setUTCDate(day.getUTCDate() - (day.getUTCDay() + 6) % 7 + offset);
  return day.toISOString().slice(0, 10);
}

async function loadHonors() {
  const [config, groups] = await Promise.all([
    requestGame("/api/game/honors/config"), requestGame("/api/group-chats"),
  ]);
  honorConfiguration = config;
  honorPreview = null;
  honorPeriodData = null;
  honorPeriodsPage = 1;
  honorHistoryPage = 1;
  renderHonorConfiguration(config, groups.items);
  await Promise.all([loadHonorPeriods(), loadHonorHistory()]);
}

function renderHonorConfiguration(config, groups) {
  const editable = identity?.role === "super_admin";
  const disabled = editable ? "" : " disabled";
  const values = config.configuration;
  const definitions = new Map(config.definitions.map((item) => [item.key, item]));
  const rules = values.rules.map((rule) => {
    const supported = definitions.get(rule.key).supported;
    const definition = definitions.get(rule.key);
    return `<details class="honor-rule" data-honor-rule="${escapeHtml(rule.key)}"><summary><span class="honor-rule-name">${escapeHtml(rule.name)}</span><span class="honor-rule-kind">${definition.all_qualified ? "达标授予" : "排名评选"} / ${definition.valid_days ?? 7} 天</span><span class="status-badge"${supported && rule.enabled ? ' data-tone="success"' : ' data-tone="warning"'}>${supported ? rule.enabled ? "已启用" : "已停用" : "统计未开放"}</span></summary><p class="muted">统计口径：${escapeHtml(definition.metric_description || rule.description)}；${definition.all_qualified ? "所有达标者均获得" : "排名评选"}；有效期 ${definition.valid_days ?? 7} 天。</p><div class="event-input-grid">
      <label class="honor-check"><input data-honor-field="enabled" type="checkbox"${rule.enabled ? " checked" : ""}${supported ? disabled : " disabled"}>启用该称号</label>
      <label>名称<input data-honor-field="name" value="${escapeHtml(rule.name)}" maxlength="64" required${disabled}></label>
      <label>资格门槛<input data-honor-field="minimum" type="number" min="1" max="100000000" value="${rule.minimum}" required${disabled}></label>
      <label>排序<input data-honor-field="sort_order" type="number" min="1" max="999" value="${rule.sort_order}" required${disabled}></label>
      <label class="honor-check"><input data-honor-field="public_score" type="checkbox"${rule.public_score ? " checked" : ""}${disabled}>公开获奖成绩</label>
      <label>说明<textarea data-honor-field="description" maxlength="300"${disabled}>${escapeHtml(rule.description)}</textarea></label>
    </div></details>`;
    }).join("");
  const groupChecks = groups.filter((group) => !group.deleted_at).map((group) => `<label class="honor-check"><input data-honor-group="${escapeHtml(group.id)}" type="checkbox"${values.group_ids.includes(group.id) ? " checked" : ""}${disabled}>${escapeHtml(group.name)}</label>`).join("");
  const options = groups.filter((group) => !group.deleted_at).map((group) => `<option value="${escapeHtml(group.id)}"${values.announcement_group_id === group.id ? " selected" : ""}>${escapeHtml(group.name)}</option>`).join("");
  const previousWeek = honorMonday(-7);
  const initialWeek = config.first_week && config.first_week > previousWeek ? config.first_week : previousWeek;
  document.querySelector("#honors-panel").innerHTML = `
    <div class="panel-heading honor-intro"><div><h2>称号配置</h2><p class="muted">北京时间周一至周日统计。三项签到称号达标者均获得，分别有效 7、30、100 天；其他称号每项最多一人、有效一周。可获得多个、佩戴一个；排名同分随机抽签。</p>
    <p class="honor-version">本周评选：${config.current.enabled ? "已开启" : "关闭"}；编辑版本 ${config.version}，生效统计周 ${escapeHtml(config.effective_week)}。</p>
    <p class="muted honor-config-note">保存修改从下个统计周生效。签到与投稿按公司记录统计；其他称号按所选群统计。游戏按有效整局计数，德州扑克按周累计净额排名，AI 互动只计成功完成的请求。门槛：签到为天数、活跃为等级、其他为次数或金额；咸鱼取最高允许等级。</p></div></div>
    ${renderPermanentHonorTools(editable)}
    <form id="honor-config-form"><fieldset${disabled}><div class="event-input-grid">
      <label class="honor-check"><input id="honor-enabled" type="checkbox"${values.enabled ? " checked" : ""}>开启周荣誉评选</label>
      <label class="honor-check"><input id="honor-announce" type="checkbox"${values.announce ? " checked" : ""}>开启荣誉公告（结算后一次、周一定时一次）</label>
      <label>周一再次公布时间（北京时间）<input id="honor-announcement-time" type="time" value="${escapeHtml(values.announcement_time ?? "09:00")}" required></label>
      <label>公告群<select id="honor-announcement-group"><option value="">不选择</option>${options}</select></label>
    </div><h3>参与统计的群</h3><div class="event-input-grid">${groupChecks}</div><h3>候选称号（${values.rules.length} 项）</h3><div class="honor-rules">${rules}</div>
    <button class="primary" type="submit">保存，下个统计周生效</button></fieldset></form>
    <section class="panel"><h2>周期预览与补结算</h2><div class="command-actions"><label>统计周周一<input id="honor-week" type="date" value="${escapeHtml(initialWeek)}"></label><button id="honor-preview-button" class="secondary" type="button">预览</button><button id="honor-settle-button" class="primary" type="button" disabled>确认结算</button><button id="honor-backfill-button" class="secondary" type="button"${disabled}>补结算全部缺失周期</button></div><div id="honor-preview-results" aria-live="polite"></div></section>
    <section class="panel"><h2>结算与纠错</h2><div id="honor-periods"></div><nav id="honor-period-pagination" class="pagination"></nav><div id="honor-corrections"></div></section>
    <section class="panel"><h2>荣誉历史</h2><form id="honor-history-filters" class="event-input-grid"><label>员工 ID（可从员工档案复制）<input id="honor-history-user" placeholder="留空查全部"></label><label>来源<select id="honor-history-source"><option value="">全部</option><option value="weekly">周榜</option><option value="season">赛季</option><option value="manual">管理员授予</option></select></label><label>周榜称号<select id="honor-history-title"><option value="">全部</option>${values.rules.map((rule) => `<option value="${escapeHtml(rule.key)}">${escapeHtml(rule.name)}</option>`).join("")}</select></label><label>统计周周一<input id="honor-history-week" type="date"></label><button class="secondary" type="submit">查询</button></form><div id="honor-history"></div><nav id="honor-history-pagination" class="pagination"></nav></section>`;
  bindPermanentHonorGrant();
  if (editable) bindSeasonHonors();
  document.querySelector("#honor-config-form").addEventListener("submit", saveHonorConfiguration);
  document.querySelector("#honor-week").addEventListener("change", () => {
    honorPreview = null;
    document.querySelector("#honor-settle-button").disabled = true;
    document.querySelector("#honor-preview-results").replaceChildren();
  });
  document.querySelector("#honor-preview-button").addEventListener("click", previewHonorPeriod);
  document.querySelector("#honor-settle-button").addEventListener("click", settleHonorPeriod);
  document.querySelector("#honor-backfill-button").addEventListener("click", backfillHonorPeriods);
  document.querySelector("#honor-history-filters").addEventListener("submit", (event) => {
    event.preventDefault();
    loadHonorHistory(1).catch((error) => setResult(error.message, "error"));
  });
}

function renderPermanentHonorTools(canManageSeason) {
  return `<details class="panel honor-permanent-tools"><summary>授予永久称号</summary>
    <form id="honor-employee-search" class="command-actions">
      <label>员工名称或工号<input name="query" maxlength="64" required></label>
      <button class="secondary" type="submit">查找员工</button>
    </form>
    <form id="honor-permanent-grant"><div class="event-input-grid">
      <label>员工<select name="employee_number" required><option value="">请先查找员工</option></select></label>
      <label>称号<input name="name" maxlength="64" required></label>
      <label>授予原因<textarea name="reason" maxlength="300" required></textarea></label>
    </div><button class="primary" type="submit">确认授予</button></form>
  </details>${canManageSeason ? `<details class="panel honor-permanent-tools"><summary>S1 赛季永久称号</summary>
    <p class="muted">以结季时的部门和职位生成称号。请核对预览，整个赛季只发放一次。</p>
    <form id="honor-season-preview">
      <label>名单来源<select name="mode"><option value="historical">历史结季名单</option><option value="current">当前组织名单</option></select></label>
      <label id="honor-season-roster-label">粘贴历史名单，每行填工号、部门、职位，以制表符分隔，不含表头。
        <textarea name="roster" rows="6" placeholder="0001&#9;核心技术部&#9;部门总监"></textarea>
      </label>
      <div class="command-actions"><button class="secondary" type="submit">预览名单</button>
        <button id="honor-season-issue" class="primary" type="button" disabled>确认批量发放</button></div>
    </form><div id="honor-season-results" aria-live="polite"></div>
  </details>` : ""}`;
}

function bindPermanentHonorGrant() {
  const search = document.querySelector("#honor-employee-search");
  const grant = document.querySelector("#honor-permanent-grant");
  const employees = grant.elements.employee_number;
  let requestId = 0;
  const clearEmployees = () => {
    requestId++;
    employees.replaceChildren(new Option("请先查找员工", ""));
  };
  search.elements.query.addEventListener("input", clearEmployees);
  search.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearEmployees();
    const currentRequest = requestId;
    const query = search.elements.query.value.trim();
    if (!query) return;
    try {
      const data = await requestGame(`/api/game/honors/employees?${new URLSearchParams({query})}`);
      if (!search.isConnected || currentRequest !== requestId) return;
      const prompt = data.items.length ? "请选择员工" : "未找到员工";
      employees.replaceChildren(new Option(prompt, ""), ...data.items.map((item) =>
        new Option(`${formatEmployeeNumber(item.employee_number)} ${item.name}`, item.employee_number)));
    } catch (error) {
      setResult(error.message, "error");
    }
  });
  grant.addEventListener("submit", async (event) => {
    event.preventDefault();
    const fields = new FormData(grant);
    const name = fields.get("name").trim();
    const reason = fields.get("reason").trim();
    if (!name || !reason) return setResult("请填写称号和授予原因", "error");
    if (!window.confirm(`将永久称号「${name}」授予 ${employees.selectedOptions[0].text}？`)) return;
    try {
      await runMutation(event.submitter, "授予中…", async () => {
        await requestGame("/api/game/honors/permanent/grant", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({employee_number: Number(fields.get("employee_number")), name, reason}),
        });
        grant.reset();
        setResult("永久称号已授予");
        if (grant.isConnected) await loadHonorHistory(1);
      });
    } catch (error) {
      setResult(error.message, "error");
    }
  });
}

function readSeasonRoster(form) {
  if (form.elements.mode.value === "current") return null;
  const lines = form.elements.roster.value.split(/\r?\n/);
  const roster = [];
  for (const [index, line] of lines.entries()) {
    if (!line.trim()) continue;
    const fields = line.split("\t").map((field) => field.trim());
    if (fields.length !== 3 || !/^#?\d{1,10}$/.test(fields[0])) {
      throw new Error(`历史名单第 ${index + 1} 行格式有误，请填写工号、部门和职位三列`);
    }
    const [number, department, rank] = fields;
    roster.push({employee_number: Number(number.replace(/^#/, "")), department, rank});
  }
  if (!roster.length) throw new Error("请先粘贴历史名单");
  return roster;
}

function renderSeasonHonorPreview(report) {
  if (report.issued) {
    const batch = report.issued;
    return `<p>S1 已发放 ${batch.count} 人 · ${escapeHtml(formatHeartbeat(batch.issued_at))} · ${escapeHtml(batch.actor)}</p>`;
  }
  const rows = [...report.rows, ...report.skipped].map((row) => `<tr><td>${formatEmployeeNumber(row.employee_number)}</td>
    <td>${escapeHtml(row.name || "—")}</td><td>${escapeHtml(row.department || "—")}</td><td>${escapeHtml(row.rank || "—")}</td>
    <td>${escapeHtml(row.title || row.reason)}</td></tr>`).join("");
  return `<p>可发放 ${report.rows.length} 人 · 跳过 ${report.skipped.length} 人</p>
    ${rows ? `<div class="table-scroll honor-season-table" role="region" aria-label="S1 名单预览" tabindex="0"><table class="data-table"><thead><tr><th>工号</th><th>员工</th><th>部门</th><th>职位</th><th>称号或跳过原因</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}`;
}

function bindSeasonHonors() {
  const form = document.querySelector("#honor-season-preview");
  const results = document.querySelector("#honor-season-results");
  const issue = document.querySelector("#honor-season-issue");
  const rosterLabel = document.querySelector("#honor-season-roster-label");
  let confirmation = null;
  let requestId = 0;
  const invalidate = () => {
    requestId++;
    confirmation = null;
    issue.disabled = true;
    results.replaceChildren();
    const historical = form.elements.mode.value === "historical";
    rosterLabel.hidden = !historical;
    form.elements.roster.disabled = !historical;
  };
  form.addEventListener("input", invalidate);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    invalidate();
    const currentRequest = requestId;
    try {
      const roster = readSeasonRoster(form);
      const report = await runMutation(event.submitter, "预览中…", () => requestGame("/api/game/honors/seasons/s1/preview", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({roster}),
      }));
      if (!report || !form.isConnected || currentRequest !== requestId) return;
      results.innerHTML = renderSeasonHonorPreview(report);
      if (report.rows?.length) {
        confirmation = {roster, preview_digest: report.preview_digest, count: report.rows.length, skipped: report.skipped.length};
        issue.disabled = issue.dataset.busy === "true";
      }
    } catch (error) {
      setResult(error.message, "error");
    }
  });
  issue.addEventListener("click", async () => {
    if (!confirmation) return;
    const {roster, preview_digest, count, skipped} = confirmation;
    if (!window.confirm(`确认向 ${count} 名员工发放 S1 赛季永久称号，跳过 ${skipped} 人？S1 发放完成后将关闭该批次。`)) return;
    try {
      const issued = await runMutation(issue, "发放中…", () => requestGame("/api/game/honors/seasons/s1/issue", {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({roster, preview_digest}),
      }));
      if (!issued) return;
      invalidate();
      results.innerHTML = renderSeasonHonorPreview({issued});
      setResult("S1 赛季永久称号已发放");
      if (form.isConnected) await loadHonorHistory(1);
    } catch (error) {
      invalidate();
      setResult(error.message, "error");
    }
  });
}

async function saveHonorConfiguration(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const values = {...honorConfiguration.configuration};
  delete values.activity_rules;
  values.enabled = form.querySelector("#honor-enabled").checked;
  values.announce = form.querySelector("#honor-announce").checked;
  values.announcement_time = form.querySelector("#honor-announcement-time").value;
  values.announcement_group_id = form.querySelector("#honor-announcement-group").value || null;
  values.group_ids = [...form.querySelectorAll("[data-honor-group]:checked")].map((input) => input.dataset.honorGroup);
  values.expected_version = honorConfiguration.version;
  values.rules = [...form.querySelectorAll("[data-honor-rule]")].map((container) => {
    const rule = {key: container.dataset.honorRule};
    for (const input of container.querySelectorAll("[data-honor-field]")) {
      rule[input.dataset.honorField] = input.type === "checkbox" ? input.checked : input.type === "number" ? Number(input.value) : input.value;
    }
    return rule;
  });
  try {
    await runMutation(form.querySelector("button"), "保存中…", async () => {
      await requestGame("/api/game/honors/config", {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(values)});
      await loadHonors();
      setResult("已保存，将从下个统计周生效。", "success");
    });
  } catch (error) { setResult(error.message, "error"); }
}

async function previewHonorPeriod() {
  honorPreview = null;
  document.querySelector("#honor-settle-button").disabled = true;
  try {
    await runMutation(document.querySelector("#honor-preview-button"), "计算中…", async () => {
      const week = document.querySelector("#honor-week").value;
      const preview = await requestGame(`/api/game/honors/preview?week_start=${encodeURIComponent(week)}`);
      if (document.querySelector("#honor-week").value !== week) return;
      honorPreview = preview;
      renderHonorPreview(preview);
      document.querySelector("#honor-settle-button").disabled = !preview.can_settle || identity?.role !== "super_admin";
    });
  } catch (error) { setResult(error.message, "error"); }
}

function renderHonorPreview(preview) {
  document.querySelector("#honor-preview-results").innerHTML = `<p>${preview.settled ? "已结算，显示当时的统计快照" : preview.can_settle ? "该周期已结束，可确认结算" : "本周尚未结束，预览不会授予称号"} · 规则版本 ${preview.config_version}</p>` + preview.entries.filter((entry) => entry.enabled && entry.supported).map((entry) => `<details><summary>${escapeHtml(entry.name)} · 合格 ${entry.candidates.filter((candidate) => candidate.eligible).length} 人${entry.place === 2 ? " · 第二名" : ""}</summary><p>${escapeHtml(entry.description)}</p><p>${entry.all_qualified ? `所有达标者均获得，有效 ${entry.valid_days} 天。` : "同分候选人在正式结算时抽签。"}</p>${entry.candidates.map((candidate) => `<p>${escapeHtml(candidate.name)}：${candidate.score} · ${candidate.eligible ? "符合资格" : "不满足资格"}</p>`).join("") || '<p class="muted">暂无候选人，本期空缺。</p>'}</details>`).join("");
}

async function settleHonorPeriod() {
  const preview = honorPreview;
  if (!preview?.can_settle || !window.confirm(`确认结算 ${preview.week_start} 这一周？同分将抽签，当前有效周期会按配置发送公告。`)) return;
  try {
    await runMutation(document.querySelector("#honor-settle-button"), "结算中…", async () => {
      await requestGame("/api/game/honors/settle", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({week_start: preview.week_start, preview_digest: preview.preview_digest})});
      honorPreview = null;
      document.querySelector("#honor-settle-button").disabled = true;
      await loadHonorPeriods();
      await loadHonorHistory();
      setResult("周期结算完成。", "success");
    });
  } catch (error) {
    honorPreview = null;
    document.querySelector("#honor-settle-button").disabled = true;
    setResult(error.message, "error");
  }
}

async function backfillHonorPeriods() {
  if (identity?.role !== "super_admin" || !window.confirm("确认补结算所有真正缺失的已结束周期？已结算周期不会改写。")) return;
  try {
    await runMutation(document.querySelector("#honor-backfill-button"), "补结算中…", async () => {
      const result = await requestGame("/api/game/honors/backfill", {method: "POST"});
      await Promise.all([loadHonorPeriods(), loadHonorHistory()]);
      setResult(result.count ? `已补结算 ${result.count} 个周期：${result.settled_weeks.join("、")}` : "没有缺失的已结束周期。", "success");
    });
  } catch (error) { setResult(error.message, "error"); }
}

async function loadHonorPeriods(page = honorPeriodsPage) {
  const data = await requestGame(`/api/game/honors/periods?page=${page}&page_size=10`);
  honorPeriodsPage = data.page;
  honorPeriodData = data;
  document.querySelector("#honor-periods").innerHTML = data.items.map((period) => `<article class="data-row"><div><b>统计周 ${escapeHtml(period.week_start)}</b><small>结算 ${escapeHtml(formatHeartbeat(period.settled_at))} · 规则 ${period.config_version} · 修订 ${period.revision}</small><small>${period.awards.filter((award) => award.user_id).length} 项授予 · 结算公告${period.announced_at ? "已入队" : "未入队"} · 周一定时公告${period.scheduled_announced_at ? "已入队" : "未入队"}</small></div><button type="button" class="secondary" data-honor-period="${escapeHtml(period.id)}">查看与纠错</button></article>`).join("") || '<p class="muted">暂无结算记录。</p>';
  renderPagination(document.querySelector("#honor-period-pagination"), data, "个周期", (target) => loadHonorPeriods(target).catch((error) => setResult(error.message, "error")));
  for (const button of document.querySelectorAll("[data-honor-period]")) {
    button.addEventListener("click", () => openHonorCorrections(button.dataset.honorPeriod).catch((error) => setResult(error.message, "error")));
  }
}

async function openHonorCorrections(periodId) {
  const period = honorPeriodData.items.find((item) => item.id === periodId);
  const snapshot = await requestGame(`/api/game/honors/preview?week_start=${encodeURIComponent(period.week_start)}`);
  const disabled = identity?.role === "super_admin" ? "" : " disabled";
  document.querySelector("#honor-corrections").innerHTML = `<h3>${escapeHtml(period.week_start)} 纠错（修订 ${period.revision}）</h3><p class="muted">仅可选择结算快照中满足资格的员工或置为空缺。纠错须填写原因，历史记录和佩戴资格同步更新。</p>` + period.awards.filter((award) => snapshot.entries.find((entry) => entry.key === award.key)?.supported).map((award) => {
    const candidates = snapshot.entries.find((entry) => entry.key === award.key).candidates.filter((candidate) => candidate.eligible);
    return `<form data-honor-correction="${escapeHtml(award.id)}" class="event-input-grid"><b>${escapeHtml(award.name)}：${escapeHtml(award.winner_name || "空缺")}</b><label>获得者<select name="winner_id"${disabled}><option value="">空缺</option>${candidates.map((candidate) => `<option value="${escapeHtml(candidate.user_id)}"${candidate.user_id === award.user_id ? " selected" : ""}>${escapeHtml(candidate.name)}（${candidate.score}）</option>`).join("")}</select></label><label>纠错原因<input name="reason" maxlength="300" required${disabled}></label><button class="secondary" type="submit"${disabled}>保存纠错</button></form>`;
  }).join("");
  for (const form of document.querySelectorAll("[data-honor-correction]")) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!window.confirm("确认修改该周期获奖者？原获得者的佩戴资格可能被收回。")) return;
      try {
        await runMutation(form.querySelector("button"), "保存中…", async () => {
          await requestGame(`/api/game/honors/awards/${form.dataset.honorCorrection}/correct`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({winner_id: form.elements.winner_id.value || null, reason: form.elements.reason.value, expected_revision: period.revision})});
          await loadHonorPeriods();
          await loadHonorHistory();
          await openHonorCorrections(periodId);
          setResult("纠错已保存并记录原因。", "success");
        });
      } catch (error) { setResult(error.message, "error"); }
    });
  }
}

async function loadHonorHistory(page = honorHistoryPage) {
  const history = document.querySelector("#honor-history");
  const params = new URLSearchParams({page: String(page), page_size: "20"});
  for (const [field, selector] of [["user_id", "#honor-history-user"], ["title_key", "#honor-history-title"],
    ["week_start", "#honor-history-week"], ["source", "#honor-history-source"]]) {
    const value = document.querySelector(selector).value.trim();
    if (value) params.set(field, value);
  }
  const data = await requestGame(`/api/game/honors/history?${params}`);
  if (!history.isConnected) return;
  honorHistoryPage = data.page;
  const canRevoke = identity?.role === "super_admin";
  history.innerHTML = data.items.map((item) => `<article class="data-row"><div>
    <b>${escapeHtml(item.winner_name)} · ${escapeHtml(item.name)}</b>
    <small>${escapeHtml(honorHistoryContext(item))}</small>
    <small>员工 ID：${escapeHtml(item.user_id || "—")}</small>
    ${canRevoke && item.source !== "weekly" && item.active ? `<details><summary>撤回</summary>
      <form data-honor-revoke="${escapeHtml(item.id)}"><label>撤回原因<textarea name="reason" maxlength="300" required></textarea></label>
      <button class="secondary" type="submit">确认撤回</button></form></details>` : ""}
  </div></article>`).join("") || '<p class="muted">没有符合条件的获奖记录。</p>';
  for (const form of history.querySelectorAll("form[data-honor-revoke]")) {
    form.addEventListener("submit", revokePermanentHonor);
  }
  renderPagination(document.querySelector("#honor-history-pagination"), data, "条荣誉", (target) => loadHonorHistory(target).catch((error) => setResult(error.message, "error")));
}

function honorHistoryContext(item) {
  if (item.source === "weekly") {
    return `统计周 ${item.week_start} · 成绩 ${item.score} · ${item.active ? "当前有效" : "历史荣誉"}`;
  }
  const details = item.source_details || {};
  const source = item.source === "season" ? `${item.season_code} 赛季` : "管理员授予";
  const context = [source, item.revoked_at ? "已撤回" : "永久", `授予于 ${formatHeartbeat(item.valid_from)}`];
  if (details.actor) context.push(`授予人 ${details.actor}`);
  if (details.reason) context.push(`授予原因 ${details.reason}`);
  if (item.revoked_at) context.push(`撤回于 ${formatHeartbeat(item.revoked_at)}`, `撤回人 ${details.revoked_by}`, `撤回原因 ${details.revoke_reason}`);
  return context.join(" · ");
}

async function revokePermanentHonor(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const reason = form.elements.reason.value.trim();
  if (!reason) return setResult("请填写撤回原因", "error");
  if (!window.confirm("确认撤回该永久称号？正在佩戴的称号将同步卸下。")) return;
  try {
    await runMutation(event.submitter, "撤回中…", async () => {
      await requestGame(`/api/game/honors/permanent/${form.dataset.honorRevoke}/revoke`, {
        method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({reason}),
      });
      setResult("永久称号已撤回");
      if (form.isConnected) await loadHonorHistory();
    });
  } catch (error) {
    setResult(error.message, "error");
  }
}

async function loadEmployeeHonors(platformId) {
  const requestId = ++employeeHonorRequestId;
  const data = await requestGame(`/api/game/users/${encodeURIComponent(platformId)}/honors`);
  if (employeeProfileModal.dataset.platformId !== platformId || requestId !== employeeHonorRequestId) return;
  document.querySelector("#employee-profile-modal-title").textContent = `编辑档案：${data.name}${data.equipped ? `【荣誉称号：${data.equipped}】` : ""}`;
  document.querySelector("#employee-honors-summary").textContent = `当前佩戴：${data.equipped || "未佩戴"}；历史累计获得 ${Object.values(data.history_counts).reduce((total, count) => total + count, 0)} 次；员工 ID：${data.user_id}。当前可佩戴：${data.items.map((item) => item.expires_at ? `${item.name}（累计 ${item.total_wins} 次）` : `${item.name}（永久）`).join("、") || "无"}`;
  const history = await requestGame(`/api/game/honors/history?user_id=${encodeURIComponent(data.user_id)}&page_size=20`);
  if (employeeProfileModal.dataset.platformId !== platformId || requestId !== employeeHonorRequestId) return;
  document.querySelector("#employee-honors-history").innerHTML = '<h3>最近 20 条荣誉</h3>' + (history.items.map((item) => `<p>${escapeHtml(item.name)}｜${escapeHtml(honorHistoryContext(item))}</p>`).join("") || '<p class="muted">暂无获奖记录。</p>');
}

document.querySelector("#employee-honors-button").addEventListener("click", () => {
  loadEmployeeHonors(employeeProfileModal.dataset.platformId).catch((error) => setResult(error.message, "error"));
});
