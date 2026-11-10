export async function withTimeout(promise, label, timeoutMs = 8000) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label}超时，请重试`)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export function requestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  globalThis.crypto?.getRandomValues?.(bytes);
  return [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
}

export class ClubClient {
  constructor({sdk, fetchImpl = fetch, apiBase, sleepImpl = ms => new Promise(resolve => setTimeout(resolve, ms))}) {
    this.sdk = sdk;
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.apiRoot = `${apiBase.replace(/\/$/, "")}/api/club`;
    this.root = `${this.apiRoot}/mahjong`;
    this.sleepImpl = sleepImpl;
    this.uid = null;
    this.userInfo = null;
    this.clubPlayer = null;
    this.identityPromise = null;
    this.stop = null;
    this.socialStop = null;
  }

  async identity(refresh = false) {
    if (refresh) {
      this.stop?.();
      this.uid = null;
      this.userInfo = null;
      this.clubPlayer = null;
      this.identityPromise = null;
    }
    if (this.uid) return this.uid;
    if (!this.identityPromise) {
      this.identityPromise = withTimeout(this.sdk.user.info(), "读取玩家身份")
        .then(async info => {
          if (typeof info?.id !== "string" || !info.id.trim()) throw new Error("无法读取玩家身份，请重试");
          this.uid = info.id;
          this.userInfo = info;
          this.clubPlayer = await this.clubRequest("/session", {
            method: "POST",
            body: JSON.stringify({
              name: info.name || info.displayName || info.nickname || null,
              avatar_url: info.avatar_url || info.avatarUrl || info.avatar || null,
            }),
          });
          return this.uid;
        });
    }
    try {
      return await this.identityPromise;
    } finally {
      this.identityPromise = null;
    }
  }

  async request(path, options = {}) {
    const uid = await this.identity();
    const controller = new AbortController();
    try {
      return await withTimeout((async () => {
        const response = await this.fetchImpl(this.root + path, {
          ...options,
          signal: controller.signal,
          headers: {
            Authorization: `ClubUid ${uid}`,
            ...(options.body ? {"Content-Type": "application/json"} : {}),
          },
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(typeof body.detail === "string" ? body.detail : "请求失败，请重试");
        }
        return response.json();
      })(), "连接 Club 服务器");
    } finally {
      controller.abort();
    }
  }

  async clubRequest(path, options = {}) {
    const uid = this.uid || await this.identity();
    const controller = new AbortController();
    try {
      return await withTimeout((async () => {
        const response = await this.fetchImpl(this.apiRoot + path, {
          ...options,
          signal: controller.signal,
          headers: {
            Authorization: `ClubUid ${uid}`,
            ...(options.body ? {"Content-Type": "application/json"} : {}),
          },
        });
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(typeof body.detail === "string" ? body.detail : "请求失败，请重试");
        }
        return response.json();
      })(), "连接 Club 服务器");
    } finally {
      controller.abort();
    }
  }

  rooms() { return this.request("/rooms"); }
  create(roomType, stake, matchMode) {
    return this.request("/rooms", {method: "POST", body: JSON.stringify({request_id: requestId(), room_type: roomType, stake, match_mode: matchMode})});
  }
  snapshot(roomId) { return this.request(`/rooms/${roomId}`); }
  action(roomId, version, action, payload = {}) {
    return this.request(`/rooms/${roomId}/actions`, {method: "POST", body: JSON.stringify({version, request_id: requestId(), action, payload})});
  }
  chat(roomId, text) {
    return this.request(`/rooms/${roomId}/chat`, {method: "POST", body: JSON.stringify({request_id: requestId(), text})});
  }
  profile() { return this.clubRequest("/profile"); }
  activeRoom() { return this.clubRequest("/active-room"); }
  playerProfile(playerId) { return this.clubRequest(`/players/${playerId}`); }
  channel() { return this.clubRequest("/channel"); }
  sendChannel(text) { return this.clubRequest("/channel", {method: "POST", body: JSON.stringify({request_id: requestId(), text})}); }
  roomStatus(game, roomId) { return this.clubRequest(`/room-status/${encodeURIComponent(game)}/${encodeURIComponent(roomId)}`); }
  friends() { return this.clubRequest("/friends"); }
  requestFriend(playerId) { return this.clubRequest("/friends", {method: "POST", body: JSON.stringify({player_id: playerId})}); }
  acceptFriend(requestIdValue) { return this.clubRequest(`/friends/${requestIdValue}/accept`, {method: "POST"}); }
  directMessages(playerId) { return this.clubRequest(`/friends/${playerId}/messages`); }
  sendDirectMessage(playerId, text) { return this.clubRequest(`/friends/${playerId}/messages`, {method: "POST", body: JSON.stringify({request_id: requestId(), text})}); }
  tasks() { return this.clubRequest("/tasks"); }
  claimTask(taskKey) { return this.clubRequest("/tasks/claim", {method: "POST", body: JSON.stringify({task_key: taskKey})}); }
  presence() { return this.clubRequest("/presence", {method: "POST"}); }
  follow(roomId, onUpdate, onError) {
    this.stop?.();
    const controller = new AbortController();
    this.stop = () => controller.abort();
    (async () => {
      while (!controller.signal.aborted) {
        try {
          const snapshot = await this.snapshot(roomId);
          if (!controller.signal.aborted) onUpdate(snapshot);
        } catch (error) {
          if (!controller.signal.aborted) onError(error);
        }
        if (!controller.signal.aborted) await this.sleepImpl(1000);
      }
    })();
    return this.stop;
  }
  followSocial(onUpdate, onError) {
    this.socialStop?.();
    const controller = new AbortController();
    this.socialStop = () => controller.abort();
    (async () => {
      while (!controller.signal.aborted) {
        try {
          const uid = await this.identity();
          const response = await this.fetchImpl(`${this.apiRoot}/social/events`, {
            signal: controller.signal,
            headers: {Authorization: `ClubUid ${uid}`},
          });
          if (!response.ok || !response.body) throw new Error("公共频道实时连接失败");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!controller.signal.aborted) {
            const {done, value} = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, {stream: true}).replaceAll("\r\n", "\n");
            let boundary;
            while ((boundary = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, boundary);
              buffer = buffer.slice(boundary + 2);
              const data = frame.split("\n").filter(line => line.startsWith("data:"))
                .map(line => line.slice(5).trimStart()).join("\n");
              if (data) onUpdate(JSON.parse(data));
            }
          }
        } catch (error) {
          if (!controller.signal.aborted) onError(error);
        }
        if (!controller.signal.aborted) await this.sleepImpl(1000);
      }
    })();
    return this.socialStop;
  }
  dispose() {
    this.stop?.();
    this.socialStop?.();
    this.stop = null;
    this.socialStop = null;
  }
}
