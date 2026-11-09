from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is required")
def test_platform_identity_coalesces_requests_expires_and_recovers():
    script = Path(__file__).resolve().parents[2] / "gamefy-workstation/publish/game.js"
    javascript = r'''
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let clock = 0, calls = 0, nextStatus = 200, loggedIn = true, hasToken = true;
let hangFetch = false, hangBody = false, requestPaths = [];
const nodes = new Map();
const node = id => {
  if (!nodes.has(id)) nodes.set(id, {addEventListener(){}, value:''});
  return nodes.get(id);
};
const context = vm.createContext({
  URL, URLSearchParams, AbortSignal, AbortController, clearTimeout,
  setTimeout: (fn, ms) => setTimeout(fn, ms === 30000 ? 20 : ms),
  Date: {now: () => clock},
  document: {getElementById:node},
  fetch:async (url) => {
    requestPaths.push(new URL(url).pathname + new URL(url).search);
    if (hangFetch) return new Promise(()=>{});
    return {ok:nextStatus===200,status:nextStatus,json:async()=>hangBody?new Promise(()=>{}):({})};
  },
  window:{workstationConfig:{apiBaseUrl:'https://example.com'},
    workstationArt:{categories:[]},
    dzmm:{user:{info:async()=>{calls++;await Promise.resolve();return {id:loggedIn?'owner':null,token:hasToken?'test-token':null};}}}},
});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context);
const source = context.window.workstationSource;
(async () => {
  await Promise.all([source.load(), source.shop(), source.lobby({query:'',page:1})]);
  assert.equal(calls,1,'concurrent reads request one platform token');
  await source.load();
  assert.equal(calls,1,'reuse token across views');
  clock+=300001;
  await source.load();
  assert.equal(calls,2,'refresh cached token after five minutes');
  nextStatus=401;
  await assert.rejects(source.load());
  nextStatus=200;
  await source.load();
  assert.equal(calls,3,'401 invalidates the token');
  clock+=300001;
  hasToken=false;
  await assert.rejects(source.load(), /平台暂未提供登录凭证/);
  const before=calls;
  await assert.rejects(source.shop(), /平台暂未提供登录凭证/);
  assert.equal(calls,before,'failed identity has a cooldown');
  clock+=30001;
  hasToken=true;
  await source.load();
  assert.equal(calls,before+1,'retry recovers after cooldown');
  clock+=300001;
  hasToken=false;loggedIn=false;
  await assert.rejects(source.load(), /请先登录 DZMM/);
  clock+=30001;hasToken=true;loggedIn=true;
  hangFetch=true;
  await assert.rejects(source.preview(1), /加载超时/);
  hangFetch=false;hangBody=true;
  await assert.rejects(source.preview(1), /加载超时/);
  hangBody=false;
  await source.preview(1);
  assert.ok(requestPaths.at(-1).endsWith('/image?preview=true'));
  await source.image(1);
  assert.ok(requestPaths.at(-1).endsWith('/image'));
})().catch(error=>{console.error(error);process.exit(1);});
'''
    result = subprocess.run(
        [shutil.which("node"), "-e", javascript, str(script)],
        text=True, encoding="utf-8", capture_output=True,
    )
    assert result.returncode == 0, result.stderr
