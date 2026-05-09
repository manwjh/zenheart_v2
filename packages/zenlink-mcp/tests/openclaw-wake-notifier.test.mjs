import test from "node:test";
import assert from "node:assert/strict";

import { OpenClawWakeNotifier } from "../dist/social/openclaw-wake-notifier.js";

test("OpenClaw wake notifier posts agent turn and updates status", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    wakeMode: "now",
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  await notifier.enqueue({
    type: "message",
    room_id: "room-1",
    agent_id: "peer",
    text: "hello",
  });

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "http://127.0.0.1:18789/hooks/agent");
  const body = JSON.parse(requests[0].init.body);
  assert.equal(body.wakeMode, "now");
  assert.equal(body.agentId, "main");
  assert.equal(body.deliver, "none");
  assert.match(body.message, /^\[ZenHeart inbound\] Action required: call zenlink_wake_drain/);
  assert.match(body.message, /Summary: message room=room-1 from=peer:/);

  const status = notifier.status();
  assert.equal(status.enabled, true);
  assert.equal(status.delivery_mode, "agent");
  assert.equal(status.openclaw_agent_id, "main");
  assert.equal(status.pending_wake_count, 0);
  assert.equal(status.sent_total, 1);
  assert.equal(status.last_http_status, 200);
});

test("OpenClaw wake notifier retains failed wake for retry diagnostics", async () => {
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    retryBaseMs: 60_000,
    fetchImpl: async () => new Response("no", { status: 503 }),
  });

  await notifier.enqueue({
    type: "msgbox_notify",
    message_id: "m-1",
  });

  const status = notifier.status();
  assert.equal(status.pending_wake_count, 1);
  assert.equal(status.last_http_status, 503);
  assert.match(status.last_error, /HTTP 503/);
  assert.equal(status.retry_count, 1);
  notifier.stop();
});

test("OpenClaw wake notifier can target a fixed session key", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    sessionKey: "hook:zenheart-main",
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  await notifier.enqueue({
    type: "message",
    room_id: "room-1",
    agent_id: "peer",
    text: "hello",
  });

  const body = JSON.parse(requests[0].init.body);
  assert.equal(body.sessionKey, "hook:zenheart-main");
  assert.equal(notifier.status().session_key, "hook:zenheart-main");
});

