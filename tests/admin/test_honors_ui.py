from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "src/dzmm_bot/admin/static/honors.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for UI checks")
def test_honor_permissions_escaping_and_preview_invalidation():
    javascript = r'''
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const nodes = new Map();
function node(selector) {
  if (!nodes.has(selector)) nodes.set(selector, {
    value: "2026-10-05", innerHTML: "", disabled: false, listeners: {}, isConnected: true, dataset: {},
    elements: Object.fromEntries(["query", "employee_number", "mode", "roster"].map((name) => [name, {
      value: "", addEventListener(event, callback) { this[event] = callback; },
    }])),
    addEventListener(event, callback) { this.listeners[event] = callback; },
    replaceChildren() { this.innerHTML = ""; },
  });
  return nodes.get(selector);
}
const context = vm.createContext({
  Intl, Date, URLSearchParams, identity: {role: "admin"},
  document: {querySelector: node, querySelectorAll: () => []},
  employeeProfileModal: {dataset: {platformId: "one"}},
  escapeHtml: (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll('"', "&quot;"),
  setResult: () => {}, formatHeartbeat: String,
  formatEmployeeNumber: (number) => `#${number}`,
  runMutation: async (button, label, callback) => callback(),
});
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), context);
context.config = {
  version: 1, effective_week: "2026-10-12", first_week: "2099-01-05", current: {enabled: true},
  configuration: {enabled: true, announce: false, group_ids: ["group"], announcement_group_id: null,
    rules: [{key: "title", name: '<img src=x onerror="bad()">', enabled: true,
      minimum: 1, sort_order: 1, public_score: true, description: "<script>bad()</script>"}]},
  definitions: [{key: "title", supported: true}],
};
context.groups = [{id: "group", name: "<unsafe>"}];
vm.runInContext("renderHonorConfiguration(config, groups)", context);
assert.ok(node("#honors-panel").innerHTML.includes("<fieldset disabled>"));
assert.ok(!node("#honors-panel").innerHTML.includes("<img src=x"));
assert.ok(!node("#honors-panel").innerHTML.includes("<script>bad()"));
assert.ok(node("#honors-panel").innerHTML.includes('value="2099-01-05"'));
assert.ok(node("#honors-panel").innerHTML.includes('id="honor-announcement-time" type="time" value="09:00" required'));
assert.ok(node("#honors-panel").innerHTML.includes("补结算全部缺失周期"));
assert.ok(node("#honors-panel").innerHTML.includes("授予永久称号"));
assert.ok(!node("#honors-panel").innerHTML.includes("S1 赛季永久称号"));
context.config.configuration.announcement_time = "08:45";
vm.runInContext("renderHonorConfiguration(config, groups)", context);
assert.ok(node("#honors-panel").innerHTML.includes('id="honor-announcement-time" type="time" value="08:45" required'));
const report = {week_start: "2026-10-05", config_version: 1, can_settle: true,
  preview_digest: "a".repeat(64), entries: []};
(async () => {
  context.identity.role = "super_admin";
  vm.runInContext("renderHonorConfiguration(config, groups)", context);
  assert.ok(node("#honors-panel").innerHTML.includes("S1 赛季永久称号"));
  assert.ok(!node("#honors-panel").innerHTML.includes('value="current"'));
  assert.ok(node("#honors-panel").innerHTML.includes("已发放名单与修改状态"));
  context.seasonItems = [{winner_name: "糯糯", user_id: "one", name: "<unsafe-title>", season_info: {
    closing_department: "历史部门", closing_rank: "部门副总监", status: "available", qualification_note: "符合资格",
    customized: true, customized_at: "2026-10-05", original_name: "<unsafe-original>",
  }}, {winner_name: "新员工", name: "旧称号", season_info: {closing_rank: "实习生", status: "not_qualified", qualification_note: "结季职级未达到副总监", customized: false}}];
  const seasonHtml = vm.runInContext("renderSeasonHonorList(seasonItems)", context);
  assert.ok(seasonHtml.includes("已修改") && seasonHtml.includes("机会已用完") && seasonHtml.includes("修改前"));
  assert.ok(seasonHtml.includes("不可佩戴") && seasonHtml.includes("未修改") && seasonHtml.includes("当前不可修改"));
  assert.ok(!seasonHtml.includes("<unsafe-title>") && !seasonHtml.includes("<unsafe-original>"));
  assert.ok(!node("#honors-panel").innerHTML.includes("粘贴历史名单"));
  assert.ok(!node("#honors-panel").innerHTML.includes("预览名单"));
  assert.ok(!node("#honors-panel").innerHTML.includes("确认批量发放"));
  let refreshes = 0;
  context.loadSeasonHonors = async () => {refreshes++;};
  node("#honor-season-refresh").listeners.click();
  assert.equal(refreshes, 1);
  assert.ok(node("#honors-panel").innerHTML.includes("最低结季职级"));
  vm.runInContext('seasonHonorSettings = {version: 3, ranks: [{order: 9, name: "部门总监"}]}', context);
  node("#honor-season-minimum").value = "9";
  let savedThreshold;
  context.window = {confirm: () => true};
  context.loadHonors = async () => {};
  context.requestGame = async (path, options) => {
    assert.equal(path, "/api/game/honors/seasons/s1/settings");
    assert.equal(options.method, "PATCH");
    savedThreshold = JSON.parse(options.body);
  };
  await node("#honor-season-settings").listeners.submit({preventDefault() {}});
  assert.deepEqual(savedThreshold, {minimum_rank_order: 9, expected_version: 3});

  const requests = [];
  context.requestGame = async (path, options) => {
    requests.push(new Request(`https://admin.test${path}`, options));
    return {};
  };
  context.loadHonorHistory = async () => {};
  context.loadSeasonHonors = async () => {};
  context.window = {confirm: () => true};
  context.FormData = class {
    get(name) { return {employee_number: "12", name: "永久称号", reason: "授予原因"}[name]; }
  };
  const grant = node("#honor-permanent-grant");
  grant.elements.employee_number.selectedOptions = [{text: "#12 糯糯"}];
  grant.reset = () => {};
  await grant.listeners.submit({preventDefault() {}, submitter: {}});
  context.revokeForm = {elements: {reason: {value: "撤回原因"}}, dataset: {honorRevoke: "award-1"}};
  await vm.runInContext("revokePermanentHonor({preventDefault() {}, currentTarget: revokeForm, submitter: {}})", context);
  assert.deepEqual(requests.map((request) => new URL(request.url).pathname), [
    "/api/game/honors/permanent/grant", "/api/game/honors/permanent/award-1/revoke",
  ]);
  for (const request of requests) {
    assert.equal(request.headers.get("content-type"), "application/json", request.url);
  }

  const form = node("#honor-config-form");
  const fields = {
    "#honor-enabled": {checked: true}, "#honor-announce": {checked: true},
    "#honor-announcement-time": {value: "10:15"}, "#honor-announcement-group": {value: "group"},
  };
  form.querySelector = (selector) => fields[selector] || node(selector);
  form.querySelectorAll = () => [];
  vm.runInContext("honorConfiguration = config", context);
  context.loadHonors = async () => {};
  context.eventForm = form;
  let savedConfiguration;
  context.requestGame = async (path, options) => { savedConfiguration = JSON.parse(options.body); };
  await vm.runInContext("saveHonorConfiguration({preventDefault() {}, currentTarget: eventForm})", context);
  assert.equal(savedConfiguration.announcement_time, "10:15");
  context.identity.role = "admin";
  context.requestGame = async () => report;
  await vm.runInContext("previewHonorPeriod()", context);
  assert.equal(node("#honor-settle-button").disabled, true);
  context.identity.role = "super_admin";
  await vm.runInContext("previewHonorPeriod()", context);
  assert.equal(node("#honor-settle-button").disabled, false);
  node("#honor-week").listeners.change();
  assert.equal(node("#honor-settle-button").disabled, true);
  assert.equal(vm.runInContext("honorPreview", context), null);
  let resolve;
  context.requestGame = () => new Promise((done) => { resolve = done; });
  const pending = vm.runInContext("previewHonorPeriod()", context);
  node("#honor-week").value = "2026-10-12";
  resolve(report);
  await pending;
  assert.equal(vm.runInContext("honorPreview", context), null);
  assert.equal(node("#honor-settle-button").disabled, true);
  context.requestGame = async () => { throw new Error("统计数据改变"); };
  await vm.runInContext("previewHonorPeriod()", context);
  assert.equal(vm.runInContext("honorPreview", context), null);
  assert.equal(node("#honor-settle-button").disabled, true);
  context.employeeProfileModal.dataset.platformId = "one";
  context.requestGame = async (path) => path.includes("/users/") ? {
    name: "糯糯", user_id: "uuid-one", equipped: "公司最靓的仔", items: [], history_counts: {charm_m: 1},
  } : {items: [{source: "weekly", week_start: "2026-10-05", name: "<unsafe-title>", active: true}]};
  await vm.runInContext('loadEmployeeHonors("one")', context);
  assert.equal(node("#employee-profile-modal-title").textContent, "编辑档案：糯糯【荣誉称号：公司最靓的仔】");
  assert.ok(!node("#employee-honors-history").innerHTML.includes("<unsafe-title>"));
  let finishOld;
  context.requestGame = () => new Promise((done) => { finishOld = done; });
  const oldEmployee = vm.runInContext('loadEmployeeHonors("one")', context);
  context.employeeProfileModal.dataset.platformId = "two";
  node("#employee-profile-modal-title").textContent = "第二位员工";
  finishOld({name: "错误旧响应", user_id: "one", items: [], history_counts: {}});
  await oldEmployee;
  assert.equal(node("#employee-profile-modal-title").textContent, "第二位员工");
})().catch((error) => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run([shutil.which("node"), "-e", javascript, str(SCRIPT)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
