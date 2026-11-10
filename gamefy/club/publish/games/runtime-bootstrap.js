(() => {
  const embedded = parent !== window;
  const clubNavigation = embedded || new URLSearchParams(location.search).get('club') === '1';
  if (clubNavigation) document.documentElement.classList.add('club-embedded');
  if (!embedded) {
    window.MoyuClubRuntime = {embedded: false, sdk: window.dzmm};
    return;
  }
  const pending = new Map();
  let roomContext = null;
  addEventListener('message', event => {
    const message = event.data;
    if (message?.type !== 'moyu-club-sdk-result' || !pending.has(message.id)) return;
    const {resolve, reject} = pending.get(message.id); pending.delete(message.id);
    if (message.error) reject(new Error(message.error)); else resolve(message.result);
  });
  const call = (method, args = []) => new Promise((resolve, reject) => {
    const id = crypto.randomUUID(); pending.set(id, {resolve, reject});
    parent.postMessage({type: 'moyu-club-sdk', id, method, args}, '*');
  });
  const proxy = {
    user: {info: () => call('user.info')},
    kv: {get: (...args) => call('kv.get', args), put: (...args) => call('kv.put', args)},
    loading: null,
    log: {info() {}, error() {}, warn() {}},
  };
  // The platform may expose a partial, non-configurable `window.dzmm` inside
  // nested frames. Keep the Club bridge under our own namespace instead of
  // trying to replace that object.
  window.MoyuClubRuntime = {
    embedded: true,
    sdk: proxy,
    openChannel: () => call('club.openChannel'),
    openProfile: player => call('club.openProfile', [player]),
    shareRoom: value => call('club.shareRoom', [value]),
    setRoomContext(value) {
      roomContext = value;
      const button = document.querySelector('#moyu-club-share-room');
      if (button) button.hidden = !roomContext;
    },
    clearRoomContext() {
      roomContext = null;
      const button = document.querySelector('#moyu-club-share-room');
      if (button) button.hidden = true;
    },
  };
  addEventListener('DOMContentLoaded', () => {
    if (document.documentElement.dataset.clubNativeTools === 'true') return;
    const style = document.createElement('style');
    style.textContent = '.moyu-club-tools{position:fixed!important;z-index:2147483646!important;top:max(8px,env(safe-area-inset-top))!important;right:8px!important;display:flex!important;gap:6px!important}.moyu-club-tools button{width:auto!important;min-width:48px!important;height:34px!important;min-height:34px!important;margin:0!important;padding:0 11px!important;border:1px solid rgba(234,204,133,.5)!important;border-radius:12px!important;color:#f6e2a9!important;background:rgba(7,42,34,.9)!important;box-shadow:0 8px 22px rgba(0,0,0,.22)!important;font:800 11px/1 "PingFang SC","Microsoft YaHei",sans-serif!important;letter-spacing:0!important;transform:none!important;backdrop-filter:blur(10px)!important}.moyu-club-tools button:disabled{opacity:.55!important}.moyu-club-tools button[hidden]{display:none!important}';
    document.head.append(style);
    const tools = document.createElement('div'); tools.className = 'moyu-club-tools'; tools.setAttribute('aria-label', 'Club 社交功能');
    const channel = document.createElement('button'); channel.id = 'moyu-club-public-channel'; channel.type = 'button'; channel.textContent = '公屏'; channel.addEventListener('click', () => window.MoyuClubRuntime.openChannel());
    const share = document.createElement('button'); share.id = 'moyu-club-share-room'; share.type = 'button'; share.textContent = '分享房间'; share.hidden = !roomContext;
    share.addEventListener('click', async () => { if (!roomContext) return; share.disabled = true; try { await window.MoyuClubRuntime.shareRoom(roomContext); } finally { share.disabled = false; } });
    tools.append(channel, share); document.body.append(tools);
    document.querySelectorAll('.club-link').forEach(link => link.addEventListener('click', event => {
      event.preventDefault();
      parent.postMessage({type: 'moyu-club-close'}, '*');
    }));
  });
})();
