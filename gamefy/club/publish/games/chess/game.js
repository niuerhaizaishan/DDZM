import {isClubNavigation,platformLoading} from '../runtime.js';
import {moduleEnvironment} from '../module-document.js';

const environment = moduleEnvironment();
const document = environment.document;
const location = environment.location;
let activeController = null, clockTimer = null;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function resolveRoomId(gp, hash) {
  if (gp != null) {
    try {
      const data = JSON.parse(gp);
      return data && typeof data.roomId === 'string' && UUID.test(data.roomId) ? data.roomId.toLowerCase() : null;
    } catch { return null; }
  }
  const match = /^#room=([0-9a-f-]+)$/i.exec(hash || '');
  return match && UUID.test(match[1]) ? match[1].toLowerCase() : null;
}

export function canMove(state) {
  return !!state && state.game.status === 'playing' && state.role === state.game.position?.turn;
}

export function canChat(state) { return !!state && ['waiting', 'playing', 'finished'].includes(state.game.status); }

export class ChessClient {
  constructor({ sdk, fetchImpl, apiBase, roomId }) {
    this.sdk = sdk;
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.root = `${apiBase.replace(/\/$/, '')}/api/chess`;
    this.base = roomId ? `${this.root}/${roomId}` : this.root;
    this.playerId = null;
    this.identityPending = null;
    this.state = null;
  }
  rooms() { return this.request('/rooms'); }
  create(roomType, stake) { return this.request('/rooms', { method: 'POST', body: JSON.stringify({ room_type: roomType, stake }) }); }
  selectRoom(roomId) { this.base = `${this.root}/${roomId}`; }
  async identity() {
    if (this.playerId) return this.playerId;
    if (!this.identityPending) {
      this.identityPending = (async () => {
        const info = await this.sdk.user.info();
        if (typeof info?.id !== 'string' || !info.id.trim()) throw new Error('无法读取玩家身份，请重新打开游戏。');
        this.playerId = info.id;
        return this.playerId;
      })();
    }
    try { return await this.identityPending; }
    finally { this.identityPending = null; }
  }
  async request(suffix = '', options = {}) {
    const response = await this.fetchImpl(this.base + suffix, {
      ...options,
      headers: { Authorization: `ChessUid ${await this.identity()}`, ...(options.body ? { 'Content-Type': 'application/json' } : {}) },
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      const error = new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请刷新棋局。');
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  async snapshot() { this.state = await this.request(); return this.state; }
  async post(suffix, body) {
    try {
      this.state = await this.request(suffix, { method: 'POST', body: JSON.stringify(body) });
      return this.state;
    } catch (error) { await this.snapshot().catch(() => {}); throw error; }
  }
  move(from_xy, to_xy, version) { return this.post('/moves', { from_xy, to_xy, version }); }
  claim() { return this.post('/claim', {}); }
  action(action, version) { return this.post('/actions', { action, version }); }
  async chat(text) {
    await this.request('/chat', { method: 'POST', body: JSON.stringify({ text }) });
    return this.snapshot();
  }
  async follow(onState, signal) {
    while (!signal.aborted) {
      try {
        onState(await this.snapshot());
        if (signal.aborted) break;
        const playerId = await this.identity();
        let response = await this.fetchImpl(`${this.base}/events`, {
          headers: { Authorization: `ChessUid ${playerId}` }, signal,
        });
        if (!response.ok || !response.body) throw new Error('棋局连接中断');
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let boundary;
          while ((boundary = buffer.indexOf('\n\n')) >= 0) {
            const packet = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const data = packet.split('\n').find(line => line.startsWith('data: '));
            if (data) { this.state = JSON.parse(data.slice(6)); onState(this.state); }
          }
        }
      } catch (error) { if (!signal.aborted) onState(this.state, error); }
      if (!signal.aborted) await new Promise(resolve => setTimeout(resolve, 1000));
    }
  }
}

const PIECE = { R: '車', H: '馬', E: '相', A: '仕', K: '帥', C: '炮', P: '兵', r: '車', h: '馬', e: '象', a: '士', k: '將', c: '砲', p: '卒' };

export function resultNotice(result, role) {
  const [winner, reason] = (result || '').split(':');
  const reasons = { checkmate: '绝杀 · 将死', stalemate: '困毙 · 无合法着法', step_timeout: '单步超时', total_timeout: '总用时耗尽', resign: '认输', agreement: '双方同意和棋', long_check: '长将判负', long_chase: '长捉判负' };
  const title = winner === 'draw' ? '和棋' : role === 'spectator' || role === 'creator' ? `${winner === 'red' ? '红方' : '黑方'}胜` : role === winner ? '胜利' : '落败';
  return { title, reason: reasons[reason] || '对局结束' };
}

export function eventText(event) {
  const side = event.color === 'red' ? '红方' : event.color === 'black' ? '黑方' : '';
  if (event.kind === 'move') {
    return `第 ${event.ply} 手 · ${side} ${PIECE[event.piece] || ''} ${event.from_xy.map(n => n + 1).join(',')} → ${event.to_xy.map(n => n + 1).join(',')}${event.captured && event.captured !== '.' ? ` · 吃${PIECE[event.captured]}` : ''}${event.check ? ' · 将军' : ''}`;
  }
  if (event.kind === 'finish') {
    const result = resultNotice(event.result, 'spectator');
    return `${result.title} · ${result.reason}`;
  }
  const labels = { offer_draw: '请求和棋', accept_draw: '同意和棋', decline_draw: '拒绝和棋', offer_undo: '请求悔棋', accept_undo: '同意悔棋', decline_undo: '拒绝悔棋', resign: '认输', rematch_ready: '已准备下一局', rematch_unready: '取消准备' };
  return `${side} · ${labels[event.kind] || event.kind}`;
}

export function moveNotice(previousSeq, events) {
  if (previousSeq === null) return '';
  const fresh = events.filter(event => event.seq > previousSeq);
  if (fresh.some(event => event.kind === 'finish')) return '';
  const move = fresh.at(-1);
  return move?.kind === 'move' ? [move.captured && move.captured !== '.' ? '吃' : '', move.check ? '将军' : ''].filter(Boolean).join(' · ') : '';
}

async function boot() {
  const status = document.querySelector('#status');
  const sdk = window.MoyuClubRuntime?.sdk ?? window.dzmm;
  const loading = platformLoading(sdk);
  loading?.progress({ phase: 'start', message: '正在进入棋局' });
  let ready = false;
  const showReady = () => {
    if (!ready) { ready = true; loading?.ready(); }
  };
  const launch = isClubNavigation() ? {} : await sdk.getLaunchParams();
  const linkedRoom = new URLSearchParams(location.search).get('room');
  let roomId = location.hash === '#lobby' ? null : (UUID.test(linkedRoom || '') ? linkedRoom.toLowerCase() : resolveRoomId(launch?.gp, location.hash));
  if (!/^https:\/\//.test(window.CHESS_API_BASE || '')) { status.textContent = '棋局 API 尚未配置 HTTPS 地址。'; showReady(); return; }
  const client = new ChessClient({ sdk, fetchImpl: fetch, apiBase: window.CHESS_API_BASE, roomId });
  let lastRoomKey;
  try { lastRoomKey = `chess:last-room:${await client.identity()}`; }
  catch (error) { status.textContent = error.message; showReady(); return; }
  if (!roomId && location.hash !== '#lobby') {
    try {
      const saved = (await sdk.kv.get(lastRoomKey))?.value;
      if (typeof saved === 'string' && UUID.test(saved)) {
        const rooms = await client.rooms();
        if (rooms.some(room => room.id === saved)) {
          roomId = saved;
          client.selectRoom(roomId);
        }
      }
    } catch { /* A missing platform save must not block the room list. */ }
  }
  if (!roomId) {
    window.MoyuClubRuntime?.clearRoomContext?.();
    document.body.classList.remove('room-open');
    const lobby = document.querySelector('#lobby');
    lobby.hidden = false;
    document.querySelector('.layout').hidden = true;
    showReady();
    roomId = await new Promise(resolve => {
      const refresh = async () => {
        const list = document.querySelector('#rooms');
        try {
          const rooms = await client.rooms();
          list.replaceChildren();
          status.textContent = rooms.length ? '选择棋局直接入座，也可以进入观战。' : '暂无棋局，可以先开一桌。';
          for (const room of rooms) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'room-card';
            const copy = document.createElement('span');
            const title = document.createElement('strong');
            const meta = document.createElement('small');
            const action = document.createElement('b');
            title.textContent = `${room.creator_name}的棋局`;
            meta.textContent = `${room.room_type === 'coin' ? `${room.stake} 币场` : '休闲场'} · ${room.status === 'waiting' ? '等待入座' : '正在对局'}`;
            action.textContent = room.status === 'waiting' ? '加入棋局' : '进入观战';
            copy.append(title, meta); button.append(copy, action);
            button.addEventListener('click', () => resolve(room.id));
            list.append(button);
          }
        } catch (error) { status.textContent = error.message; }
      };
      document.querySelector('#refresh-rooms').addEventListener('click', refresh);
      document.querySelectorAll('[data-create-room]').forEach(button => button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          const next = await client.create(button.dataset.createRoom, Number(button.dataset.stake));
          resolve(next.game.id);
        } catch (error) { status.textContent = error.message; }
        finally { button.disabled = false; }
      }));
      refresh();
    });
    client.selectRoom(roomId);
    lobby.hidden = true;
    document.querySelector('.layout').hidden = false;
  }
  document.body.classList.add('room-open');
  window.MoyuClubRuntime?.setRoomContext?.({ game: 'chess', roomId, host: '玩家' });
  location.hash = `room=${roomId}`;
  try { await sdk.kv.put(lastRoomKey, roomId, { flush: true }); }
  catch { document.querySelector('#feedback').textContent = '未能保存最近棋局，下次请从列表进入。'; }
  document.querySelector('#back-to-rooms').addEventListener('click', () => {
    if (state?.game?.status === 'playing' && !confirm('棋局尚未结束。返回后棋钟继续，超时会判负；重新进入 Club 会回到本局。确定返回吗？')) return;
    location.hash = 'lobby';
    location.reload();
  });
  const controller = new AbortController(); activeController = controller;
  let state = null;
  let selected = null;
  let serverOffset = 0;
  let lastEventSeq = null;
  let noticeTimer;
  const board = document.querySelector('#board');

  function clockText(color) {
    if (!state) return '15:00';
    const game = state.game;
    let ms = game[`${color}_remaining_ms`];
    if (game.status === 'playing' && game.position?.turn === color) {
      ms -= Math.max(0, Date.now() - serverOffset - Date.parse(game.turn_started_at));
    }
    const seconds = Math.max(0, Math.ceil(ms / 1000));
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }
  function clocks() {
    document.querySelector('#red-clock').textContent = clockText('red');
    document.querySelector('#black-clock').textContent = clockText('black');
    const game = state?.game;
    const elapsed = game?.status === 'playing' ? Math.max(0, Date.now() - serverOffset - Date.parse(game.turn_started_at)) : 0;
    document.querySelector('#move-clock').textContent = String(Math.max(0, Math.ceil((60000 - elapsed) / 1000)));
  }
  function renderBoard() {
    board.replaceChildren();
    const rows = state.game.position?.board || ['rheakaehr', '.........', '.c.....c.', 'p.p.p.p.p', '.........', '.........', 'P.P.P.P.P', '.C.....C.', '.........', 'RHEAKAEHR'];
    const flip = state.role === 'black';
    for (let row = 0; row < 10; row++) for (let col = 0; col < 9; col++) {
      const x = flip ? 8 - col : col;
      const y = flip ? 9 - row : row;
      const piece = rows[y][x];
      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = `cell${row === 4 ? ' river' : ''}${selected?.[0] === x && selected?.[1] === y ? ' selected' : ''}`;
      cell.setAttribute('aria-label', `${x},${y}${PIECE[piece] || ''}`);
      cell.setAttribute('aria-pressed', String(selected?.[0] === x && selected?.[1] === y));
      if (state.game.check_square?.[0] === x && state.game.check_square?.[1] === y) cell.classList.add('in-check');
      if (piece !== '.') {
        const disk = document.createElement('span');
        disk.className = `piece ${piece === piece.toUpperCase() ? 'red' : 'black'}`;
        disk.textContent = PIECE[piece];
        cell.append(disk);
      }
      cell.addEventListener('click', async () => {
        if (!canMove(state)) return;
        const own = piece !== '.' && (piece === piece.toUpperCase()) === (state.role === 'red');
        if (own) { selected = [x, y]; renderBoard(); return; }
        if (!selected) return;
        const from = selected;
        selected = null;
        try { render(await client.move(from, [x, y], state.game.version)); }
        catch (error) { render(client.state); status.textContent = error.message; }
      });
      board.append(cell);
    }
  }
  function render(next, error) {
    if (!next) { status.textContent = error?.message || '连接中…'; showReady(); return; }
    state = next;
    serverOffset = Date.now() - Date.parse(next.server_time || new Date().toISOString());
    const game = next.game;
    window.MoyuClubRuntime?.setRoomContext?.({ game: 'chess', roomId, host: game.red_name || '玩家' });
    const events = game.events || [];
    const notice = document.querySelector('#move-notice');
    const message = moveNotice(lastEventSeq, events);
    lastEventSeq = Math.max(lastEventSeq || 0, ...events.map(event => event.seq));
    if (message) {
      clearTimeout(noticeTimer);
      notice.textContent = message;
      notice.hidden = false;
      noticeTimer = setTimeout(() => { notice.hidden = true; }, 1800);
    }
    const result = document.querySelector('#result');
    result.hidden = game.status !== 'finished';
    if (!result.hidden) {
      const outcome = resultNotice(game.result, next.role);
      document.querySelector('#result-title').textContent = outcome.title;
      document.querySelector('#result-reason').textContent = outcome.reason;
      const payouts = game.settlement?.payouts || {}; const color = next.role;
      document.querySelector('#result-economy').textContent = game.room_type === 'coin' && ['red', 'black'].includes(color) ? `摸鱼币 ${(payouts[color] || 0) - game.stake >= 0 ? '+' : ''}${(payouts[color] || 0) - game.stake}` : '最终局面保留在棋盘，可查看完整着法记录';
      const ready = new Set(game.rematch_ready || []); document.querySelector('#result-ready').textContent = `红方 ${ready.has('red') ? '已准备' : '未准备'} · 黑方 ${ready.has('black') ? '已准备' : '未准备'}`;
      const readyButton = document.querySelector('#result-ready-action'); const seated = ['red', 'black'].includes(next.role); readyButton.hidden = !seated; readyButton.textContent = ready.has(next.role) ? '取消准备' : '准备下一局'; readyButton.dataset.action = ready.has(next.role) ? 'unready' : 'ready';
      const start = document.querySelector('#result-start'); start.hidden = !next.is_host; start.disabled = ready.size !== 2; start.textContent = start.disabled ? `等待准备 ${ready.size}/2` : '开始下一局';
      notice.hidden = true;
    }
    document.querySelector('#players').textContent = `红方 ${game.red_name || '待定'} · 黑方 ${game.black_name || '待定'}`;
    for (const color of ['red', 'black']) {
      const player = document.querySelector(`#${color}-player`);
      player.classList.toggle('active', game.status === 'playing' && game.position?.turn === color);
      document.querySelector(`#${color}-name`).textContent = game[`${color}_name`] || '等待入座';
      document.querySelector(`#${color}-side`).textContent = `${color === 'red' ? '红方' : '黑方'}${next.role === color ? ' · 你' : ''}`;
    }
    board.before(document.querySelector(next.role === 'black' ? '#red-player' : '#black-player'));
    board.after(document.querySelector(next.role === 'black' ? '#black-player' : '#red-player'));
    status.textContent = error ? '正在重新连接…' : game.status === 'waiting' ? '等待第二位棋手入座' : game.status === 'cancelled' ? '棋局已取消' : game.status === 'finished' ? resultNotice(game.result, next.role).title : `${game.check_square ? '将军！' : '进行中'} · 你是${next.role === 'spectator' ? '观众' : next.role === 'red' ? '红方' : '黑方'}`;
    document.querySelector('#claim-panel').hidden = game.status !== 'waiting' || next.role !== 'spectator';
    document.querySelector('#actions').hidden = !['red', 'black'].includes(next.role) || game.status !== 'playing';
    document.querySelector('#respond').hidden = !game.pending_offer || next.offer_mine || !['red', 'black'].includes(next.role);
    for (const button of document.querySelectorAll('#respond [data-action]')) {
      button.hidden = !button.dataset.action.endsWith(game.pending_offer || '');
    }
    document.querySelector('#offer-label').textContent = game.pending_offer ? `对手请求${game.pending_offer === 'undo' ? '悔棋' : '和棋'}` : '';
    document.querySelector('#chat-input').disabled = !canChat(next);
    document.querySelector('#chat-send').disabled = !canChat(next);
    document.querySelector('#chat-input').placeholder = canChat(next) ? (game.status === 'finished' ? '赛后聊聊，准备好再开一局…' : '聊聊这盘棋…') : '当前不能发言';
    const list = document.querySelector('#chat-list');
    list.replaceChildren();
    for (const message of next.messages || []) {
      const item = document.createElement('p');
      item.textContent = `${message.sender}：${message.text}`;
      list.append(item);
    }
    const moves = document.querySelector('#moves-list');
    moves.replaceChildren();
    const undone = new Set(events.filter(event => event.kind === 'accept_undo').map(event => event.undone_seq));
    for (const event of events.length ? events : (next.moves || []).map(move => ({ ...move, kind: 'move' }))) {
      const item = document.createElement('p');
      const revoked = undone.has(event.seq);
      item.className = revoked ? 'revoked' : event.kind === 'move' ? 'move-entry' : 'action-entry';
      item.textContent = `${eventText(event)}${revoked ? ' · 已撤回' : ''}`;
      moves.append(item);
    }
    clocks(); renderBoard(); showReady();
  }
  const feedback = document.querySelector('#feedback');
  const claimButton = document.querySelector('#claim-seat');
  claimButton.addEventListener('click', async () => {
    claimButton.disabled = true;
    feedback.textContent = '正在申请入座…';
    try { render(await client.claim()); feedback.textContent = '入座成功。'; }
    catch (error) {
      feedback.textContent = ({ expired: '棋局已过期，请重新创建。', occupied: '席位已被抢占或棋局已结束。', same_player: '你已是创建者，不能抢第二席。', not_found: '棋局不存在，请返回列表。' })[error.message] || error.message;
    }
    finally { claimButton.disabled = false; }
  });
  document.querySelector('#chat-send').addEventListener('click', async () => {
    const input = document.querySelector('#chat-input');
    try { render(await client.chat(input.value)); input.value = ''; }
    catch (error) { feedback.textContent = error.message; }
  });
  document.querySelector('#chat-input').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); document.querySelector('#chat-send').click(); }
  });
  document.querySelector('#result-exit').addEventListener('click', () => document.querySelector('#back-to-rooms').click());
  for (const button of document.querySelectorAll('[data-action]')) button.addEventListener('click', async () => {
    const action = button.dataset.action;
    if (action === 'resign' && !confirm('确定认输吗？')) return;
    try { render(await client.action(action, state.game.version)); }
    catch (error) { render(client.state); status.textContent = error.message; }
  });
  clockTimer = setInterval(clocks, 250);
  await client.follow(render, controller.signal);
}

export function unmount() {
  activeController?.abort(); activeController = null;
  clearInterval(clockTimer); clockTimer = null;
  window.MoyuClubRuntime?.clearRoomContext?.();
}

if (typeof document !== 'undefined') {
  const panel = document.querySelector('#chess-social');
  const toggle = document.querySelector('#chess-social-toggle');
  const setSocialOpen = open => {
    panel.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', String(open));
  };
  toggle.addEventListener('click', () => setSocialOpen(!panel.classList.contains('open')));
  document.querySelector('#chess-social-close').addEventListener('click', () => setSocialOpen(false));
}

if (typeof document !== 'undefined') boot().catch(error => {
  document.querySelector('#status').textContent = error.message;
  platformLoading(window.MoyuClubRuntime?.sdk ?? window.dzmm)?.error?.('CHESS_BOOT_FAILED', error.message);
});
