import test from "node:test";
import assert from "node:assert/strict";

import { OpenClawWakeNotifier } from "../dist/social/openclaw-wake-notifier.js";

test("OpenClaw wake notifier posts agent turn and updates status", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    wakeMode: "now",
    inboundQueueDepth: () => 7,
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
  assert.match(body.message, /Required tool call: zenlink_wake_drain/);
  assert.match(body.message, /Queued inbound frames now: 7\./);
  assert.match(body.message, /Summary: message room=room-1 from=peer:/);

  const status = notifier.status();
  assert.equal(status.enabled, true);
  assert.equal(status.delivery_mode, "agent");
  assert.equal(status.openclaw_agent_id, "main");
  assert.equal(status.pending_wake_count, 0);
  assert.equal(status.sent_total, 1);
  assert.equal(status.last_http_status, 200);
});

test("OpenClaw wake notifier summarizes topic suggestions with text", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    inboundQueueDepth: () => 1,
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  await notifier.enqueue({
    type: "topic_suggestions_pending",
    room_id: "room-1",
    topics: [
      {
        id: "topic-1",
        text: "Please discuss whether agents should introduce themselves before joining a room.",
        created_at: "2026-05-12T00:00:00Z",
      },
      {
        id: "topic-2",
        text: "Ask the room owner to compare public chat with visitor topic suggestions.",
        created_at: "2026-05-12T00:00:01Z",
      },
    ],
  });

  assert.equal(requests.length, 1);
  const body = JSON.parse(requests[0].init.body);
  assert.match(body.message, /Summary: topic_suggestions_pending room=room-1/);
  assert.match(body.message, /#1: Please discuss whether agents should introduce themselves/);
  assert.match(body.message, /#2: Ask the room owner to compare public chat/);

  const status = notifier.status();
  assert.equal(status.sent_total_by_signal["room.topic_suggestions_pending"], 1);
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

test("OpenClaw wake notifier formats structured failure hints", async () => {
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    retryBaseMs: 60_000,
    fetchImpl: async () => new Response(
      JSON.stringify({
        detail: "Too many requests. Please try again later.",
        error: {
          code: "rate_limit_exceeded",
          message: "The request exceeded its rate limit.",
          hint: "Back off before reconnecting or sending more frames.",
          retryable: true,
          category: "rate_limit",
          action: "backoff",
        },
      }),
      { status: 429, headers: { "content-type": "application/json" } },
    ),
  });

  await notifier.enqueue({
    type: "msgbox_notify",
    message_id: "m-2",
  });

  const status = notifier.status();
  assert.equal(status.pending_wake_count, 1);
  assert.equal(status.last_http_status, 429);
  assert.match(status.last_error, /rate_limit_exceeded: The request exceeded its rate limit/);
  assert.match(status.last_error, /Hint: Back off before reconnecting/);
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

test("OpenClaw wake notifier does not wake for room presence signals by default", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  await notifier.enqueue({
    type: "social_notify",
    kind: "member_joined",
    room_id: "room-1",
    agent_id: "peer",
  });
  await notifier.enqueue({
    type: "member_left",
    room_id: "room-1",
    agent_id: "peer",
  });

  const status = notifier.status();
  assert.equal(requests.length, 0);
  assert.equal(status.sent_total, 0);
  assert.equal(status.skipped_signal_policy_by_signal["room.member_joined_notify"], 1);
  assert.equal(status.skipped_signal_policy_by_signal["room.member_left"], 1);
});

test("OpenClaw wake notifier can explicitly wake selected signals", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    wakeSignals: ["room.member_joined_notify"],
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  await notifier.enqueue({
    type: "social_notify",
    kind: "member_joined",
    room_id: "room-1",
    agent_id: "peer",
  });
  await notifier.enqueue({
    type: "message",
    room_id: "room-1",
    agent_id: "peer",
    text: "hello",
  });

  const status = notifier.status();
  assert.equal(requests.length, 1);
  assert.equal(status.sent_total_by_signal["room.member_joined_notify"], 1);
  assert.equal(status.skipped_signal_policy_by_signal["room.message"], 1);
});

test("OpenClaw wake notifier bootstraps wake policy from env", async () => {
  const previous = process.env.ZENLINK_MCP_WAKE_SIGNALS;
  process.env.ZENLINK_MCP_WAKE_SIGNALS = "room.member_joined_notify";
  const requests = [];
  try {
    const notifier = new OpenClawWakeNotifier({
      hookBase: "http://127.0.0.1:18789/hooks",
      hookToken: "secret",
      fetchImpl: async (url, init) => {
        requests.push({ url: String(url), init });
        return new Response("{}", { status: 200 });
      },
    });

    await notifier.enqueue({
      type: "social_notify",
      kind: "member_joined",
      room_id: "room-1",
      agent_id: "peer",
    });
    await notifier.enqueue({
      type: "msgbox_notify",
      message_id: "m-1",
    });

    const status = notifier.status();
    assert.equal(requests.length, 1);
    assert.equal(status.wake_policy.mode, "allowlist");
    assert.deepEqual(status.wake_policy.wake_signals, ["room.member_joined_notify"]);
    assert.equal(status.wake_policy.updated_by, "startup_env");
    assert.equal(status.sent_total_by_signal["room.member_joined_notify"], 1);
    assert.equal(status.skipped_signal_policy_by_signal["msgbox.notify"], 1);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_WAKE_SIGNALS;
    } else {
      process.env.ZENLINK_MCP_WAKE_SIGNALS = previous;
    }
  }
});

test("OpenClaw wake notifier updates wake policy at runtime", async () => {
  const requests = [];
  const notifier = new OpenClawWakeNotifier({
    hookBase: "http://127.0.0.1:18789/hooks",
    hookToken: "secret",
    fetchImpl: async (url, init) => {
      requests.push({ url: String(url), init });
      return new Response("{}", { status: 200 });
    },
  });

  let policy = notifier.setWakePolicyAllowlist(["room.member_joined_notify"]);
  assert.equal(policy.mode, "allowlist");
  assert.equal(policy.updated_by, "mcp");

  await notifier.enqueue({
    type: "message",
    room_id: "room-1",
    agent_id: "peer",
    text: "hello",
  });
  assert.equal(requests.length, 0);
  assert.equal(notifier.status().skipped_signal_policy_by_signal["room.message"], 1);

  policy = notifier.resetWakePolicy();
  assert.equal(policy.mode, "default");

  await notifier.enqueue({
    type: "message",
    room_id: "room-1",
    agent_id: "peer",
    text: "hello after reset",
  });
  assert.equal(requests.length, 1);
});

