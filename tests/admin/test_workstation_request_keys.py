"""Exercise browser UUID fallbacks and their actual admin API contract."""
import json
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

import pytest

from test_workstation_management import management


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required for UI checks")
def test_http_browser_keys_save_prices_and_retry_without_duplicate_changes(management):
    root = Path(__file__).resolve().parents[2]
    script = r'''
const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const crypto = require("node:crypto").webcrypto;
const admin = fs.readFileSync(process.argv[1], "utf8");
const helper = admin.slice(admin.indexOf("function idempotencyKey() {"), admin.indexOf("function ownsLoginLease()"));
const workstation = fs.readFileSync(process.argv[2], "utf8");
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
(async () => {
  const keys = [];
  for (const browserCrypto of [crypto, {getRandomValues: crypto.getRandomValues.bind(crypto)}, undefined]) {
    const requests = [];
    let fail = true;
    const context = {crypto: browserCrypto, requestGame: async (url, options) => {
      requests.push(options);
      if (fail) {fail = false; throw new Error("network interruption");}
      return {saved: true};
    }};
    vm.createContext(context);
    vm.runInContext(helper + workstation, context);
    const generated = new Set(Array.from({length: 100}, () => vm.runInContext("idempotencyKey()", context)));
    assert.equal(generated.size, 100);
    for (const key of generated) assert.match(key, uuid);
    await assert.rejects(vm.runInContext('workstationWrite("settings", {price: 123}, 7)', context));
    await vm.runInContext('workstationWrite("settings", {price: 123}, 7)', context);
    assert.equal(requests[0].headers["Idempotency-Key"], requests[1].headers["Idempotency-Key"]);
    assert.equal(requests[1].headers["If-Match"], "7");
    await vm.runInContext('workstationWrite("settings", {price: 456}, 7)', context);
    assert.notEqual(requests[1].headers["Idempotency-Key"], requests[2].headers["Idempotency-Key"]);
    keys.push(requests[0].headers["Idempotency-Key"]);
  }
  console.log(JSON.stringify(keys));
})().catch(error => {console.error(error); process.exitCode = 1;});
'''
    run = subprocess.run(
        [shutil.which("node"), "-e", script,
         str(root / "src/dzmm_bot/admin/static/admin.js"),
         str(root / "src/dzmm_bot/admin/static/workstation-admin.js")],
        capture_output=True, text=True, encoding="utf-8", check=True,
    )
    client, repo, _, factory, operator = management
    for price, key in enumerate(json.loads(run.stdout), start=123):
        assert UUID(key).version == 4
        settings = client.get('/api/game/workstation/settings', headers=operator).json()
        rules = settings['rules']
        rules['environment_upgrade_costs'][0] = price
        body = {'kind': 'rules', 'revision': settings['revision'], 'data': rules, 'reason': '浏览器兼容性验证'}
        headers = {**operator, 'Idempotency-Key': key, 'If-Match': str(settings['version'])}
        saved = client.post('/api/game/workstation/settings', headers=headers, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()['rules']['environment_upgrade_costs'][0] == price
        replay = client.post('/api/game/workstation/settings', headers=headers, json=body)
        assert replay.status_code == 200 and replay.json() == saved.json()
