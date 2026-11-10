import assert from "node:assert/strict";
import test from "node:test";
import {ClubClient} from "../publish/client.js";

test("client sends UID authorization and stable action envelope", async () => {
  const requests = [];
  const client = new ClubClient({
    sdk: {user: {info: async () => ({id: "employee-1"})}},
    apiBase: "https://club.test",
    fetchImpl: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => ({version: 2})};
    },
  });
  await client.action("room-1", 1, "ready");
  const actionRequest = requests.find(request => request.url.endsWith("/rooms/room-1/actions"));
  const body = JSON.parse(actionRequest.options.body);
  assert.equal(actionRequest.options.headers.Authorization, "ClubUid employee-1");
  assert.equal(body.version, 1);
  assert.equal(body.action, "ready");
  assert.match(body.request_id, /^[0-9a-f-]+$/);
});

test("client posts the Club presence heartbeat", async () => {
  const requests = [];
  const client = new ClubClient({
    sdk: {user: {info: async () => ({id: "employee-1"})}},
    apiBase: "https://club.test",
    fetchImpl: async (url, options) => {
      requests.push({url, options});
      return {ok: true, json: async () => ({online: 3, playing: 2})};
    },
  });
  await client.presence();
  const heartbeat = requests.find(request => request.url.endsWith("/api/club/presence"));
  assert.equal(heartbeat.options.method, "POST");
  assert.equal(heartbeat.options.headers.Authorization, "ClubUid employee-1");
});

test("client follows Club social updates over SSE", async () => {
  const seen = [];
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('event: social\ndata: {"channel":"message-1","direct":"","friends":""}\n\n'));
    },
  });
  const client = new ClubClient({
    sdk: {user: {info: async () => ({id: "employee-1"})}},
    apiBase: "https://club.test",
    fetchImpl: async url => url.endsWith("/social/events")
      ? {ok: true, body}
      : {ok: true, json: async () => ({id: "player-1"})},
  });

  client.followSocial(value => seen.push(value), error => { throw error; });
  await new Promise(resolve => setTimeout(resolve, 0));
  client.dispose();

  assert.deepEqual(seen, [{channel: "message-1", direct: "", friends: ""}]);
});
