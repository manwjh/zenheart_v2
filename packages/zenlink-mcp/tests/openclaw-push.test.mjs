import test from "node:test";
import assert from "node:assert/strict";

import {
  describeOpenClawPushPublic,
  OpenClawPushNotifier,
  readOpenClawPushConfig,
} from "../dist/social/openclaw-push.js";

function withEnv(patch, fn) {
  const before = {};
  for (const key of Object.keys(patch)) before[key] = process.env[key];
  for (const [key, value] of Object.entries(patch)) {
    if (value === null) delete process.env[key];
    else process.env[key] = value;
  }
  try {
    return fn();
  } finally {
    for (const key of Object.keys(patch)) {
      const v = before[key];
      if (v === undefined) delete process.env[key];
      else process.env[key] = v;
    }
  }
}

test("readOpenClawPushConfig disabled when env absent", () => {
  withEnv(
    {
      ZENLINK_MCP_OPENCLAW_HOOK_BASE: null,
      ZENLINK_MCP_OPENCLAW_HOOK_TOKEN: null,
    },
    () => {
      assert.equal(readOpenClawPushConfig(), undefined);
    },
  );
});

test("readOpenClawPushConfig parses base and options", () => {
  withEnv(
    {
      ZENLINK_MCP_OPENCLAW_HOOK_BASE: "http://127.0.0.1:18789/hooks",
      ZENLINK_MCP_OPENCLAW_HOOK_TOKEN: "token-1",
      ZENLINK_MCP_OPENCLAW_WAKE_MODE: "next-heartbeat",
      ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES: "message,msgbox_notify",
      ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS: "500",
    },
    () => {
      const cfg = readOpenClawPushConfig();
      assert.ok(cfg);
      assert.equal(cfg.hookWakeUrl, "http://127.0.0.1:18789/hooks/wake");
      assert.equal(cfg.wakeMode, "next-heartbeat");
      assert.equal(cfg.dedupeMs, 500);
      assert.equal(cfg.frameTypes.has("message"), true);
      assert.equal(cfg.frameTypes.has("msgbox_notify"), true);
      assert.equal(cfg.roomMessageWakeCoalesceMs, 2000);
    },
  );
});

test("describeOpenClawPushPublic reports disabled shape", () => {
  const out = describeOpenClawPushPublic(undefined);
  assert.deepEqual(out, {
    enabled: false,
    hook_wake_url: null,
    wake_mode: null,
    frame_types: [],
    dedupe_ms: 0,
    room_message_wake_coalesce_ms: 0,
  });
});

test("OpenClawPushNotifier posts message frames and records diagnostics", async () => {
  const before = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response("ok", { status: 200 });
  };
  try {
    const notifier = new OpenClawPushNotifier({
      hookWakeUrl: "http://127.0.0.1:18789/hooks/wake",
      token: "token-1",
      wakeMode: "now",
      frameTypes: new Set(["message", "social_notify"]),
      dedupeMs: 0,
      roomMessageWakeCoalesceMs: 0,
    });

    notifier.notifyInboundQueued({
      type: "message",
      room_id: "room-1",
      agent_id: "agent-2",
      agent_name: "Peer",
      text: "hello from peer",
      sent_at: "2026-05-06T12:00:00Z",
    });
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "http://127.0.0.1:18789/hooks/wake");
    const body = JSON.parse(calls[0].init.body);
    assert.equal(body.mode, "now");
    assert.match(body.text, /type=message/);
    assert.match(body.text, /hello from peer/);

    const status = notifier.status();
    assert.equal(status.last_error, null);
    assert.equal(status.last_ok_frame.type, "message");
    assert.equal(status.sent_total_by_type.message, 1);
    assert.deepEqual(status.failed_total_by_type, {});
    assert.deepEqual(status.skipped_dedupe_by_type, {});
    assert.deepEqual(status.skipped_room_line_coalesce_by_type, {});
    assert.deepEqual(status.skipped_frame_type_filter_by_type, {});
  } finally {
    globalThis.fetch = before;
  }
});

test("OpenClawPushNotifier coalesces message + social_notify preview to one wake", async () => {
  const before = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response("ok", { status: 200 });
  };
  try {
    const notifier = new OpenClawPushNotifier({
      hookWakeUrl: "http://127.0.0.1:18789/hooks/wake",
      token: "token-1",
      wakeMode: "now",
      frameTypes: new Set(["message", "social_notify"]),
      dedupeMs: 0,
      roomMessageWakeCoalesceMs: 2000,
    });

    const base = {
      room_id: "room-1",
      sent_at: "2026-05-06T12:00:41.914481+00:00",
    };
    notifier.notifyInboundQueued({
      type: "message",
      ...base,
      agent_id: "peer",
      agent_name: "Peer",
      text: "hello",
    });
    notifier.notifyInboundQueued({
      type: "social_notify",
      kind: "message",
      ...base,
      sender_agent_id: "peer",
      text_preview: "hello",
    });
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(calls.length, 1);
    const st = notifier.status();
    assert.equal(st.sent_total_by_type.message, 1);
    assert.equal(st.sent_total_by_type.social_notify, undefined);
    assert.deepEqual(st.skipped_room_line_coalesce_by_type, {
      social_notify: 1,
    });
  } finally {
    globalThis.fetch = before;
  }
});

test("OpenClawPushNotifier coalesces when social_notify preview arrives before message", async () => {
  const before = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response("ok", { status: 200 });
  };
  try {
    const notifier = new OpenClawPushNotifier({
      hookWakeUrl: "http://127.0.0.1:18789/hooks/wake",
      token: "token-1",
      wakeMode: "now",
      frameTypes: new Set(["message", "social_notify"]),
      dedupeMs: 0,
      roomMessageWakeCoalesceMs: 2000,
    });

    const base = {
      room_id: "room-1",
      sent_at: "2026-05-06T12:00:41.914481+00:00",
    };
    notifier.notifyInboundQueued({
      type: "social_notify",
      kind: "message",
      ...base,
      sender_agent_id: "peer",
      text_preview: "hello",
    });
    notifier.notifyInboundQueued({
      type: "message",
      ...base,
      agent_id: "peer",
      agent_name: "Peer",
      text: "hello",
    });
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(calls.length, 1);
    const st = notifier.status();
    assert.equal(st.sent_total_by_type.social_notify, 1);
    assert.equal(st.sent_total_by_type.message, undefined);
    assert.deepEqual(st.skipped_room_line_coalesce_by_type, {
      message: 1,
    });
    const body = JSON.parse(calls[0].init.body);
    assert.match(body.text, /type=social_notify/);
  } finally {
    globalThis.fetch = before;
  }
});
