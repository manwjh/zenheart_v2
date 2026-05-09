import test from "node:test";
import assert from "node:assert/strict";

import { OpenClawWakeNotifier } from "../dist/social/openclaw-wake-notifier.js";
import { dispatchZenlinkTool } from "../dist/tools/tool-dispatch.js";
import { ZenlinkClient } from "../dist/zenlink/client.js";
import { ZenlinkSession } from "../dist/transport/session.js";

test("inbound frame is queued and mirrored to OpenClaw wake notifier", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
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
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    const session = new ZenlinkSession(client, notifier);

    session.injectInboundForTest({
      type: "message",
      room_id: "room-1",
      agent_id: "peer-agent",
      text: "question from ZenHeart",
    });
    await notifier.flush();

    assert.equal(requests.length, 1);
    const wait = await session.inboundWait(4, 0, ["message"]);
    assert.equal(wait.frames.length, 1);
    assert.equal(wait.frames[0].text, "question from ZenHeart");
    const status = session.status();
    assert.equal(status.openclaw_push.sent_total, 1);
    assert.ok(status.last_inbound_dequeue_at);
    assert.equal(status.last_inbound_dequeue_count, 1);
    assert.equal(status.last_inbound_dequeue_tool, "zenlink_inbound_wait");
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("inbound_wait wakes immediately when a matching frame arrives", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = { readyState: 1 };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    const start = Date.now();
    const waitPromise = session.inboundWait(4, 5_000, ["message"]);
    setTimeout(() => {
      session.injectInboundForTest({
        type: "message",
        room_id: "room-1",
        agent_id: "peer-agent",
        text: "event-driven",
      });
    }, 20);

    const result = await waitPromise;
    assert.equal(result.source, "inbound_fifo");
    assert.equal(result.frames.length, 1);
    assert.equal(result.frames[0].text, "event-driven");
    assert.ok(Date.now() - start < 1_000);
    assert.equal(session.status().wait_timeout_total, 0);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("inbound drain can filter by room_id without consuming other rooms", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = { readyState: 1 };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    session.injectInboundForTest({
      type: "message",
      room_id: "room-a",
      agent_id: "peer-agent",
      text: "for A",
    });
    session.injectInboundForTest({
      type: "message",
      room_id: "room-b",
      agent_id: "peer-agent",
      text: "for B",
    });

    const onlyB = await session.inboundWait(4, 0, ["message"], { roomId: "room-b" });
    assert.equal(onlyB.frames.length, 1);
    assert.equal(onlyB.frames[0].room_id, "room-b");
    assert.equal(onlyB.room_filter, "room-b");

    const remaining = session.inboundPoll(4, ["message"]);
    assert.equal(remaining.frames.length, 1);
    assert.equal(remaining.frames[0].room_id, "room-a");
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("send_message with room_id joins target room before sending", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const sent = [];
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = {
      readyState: 1,
      send: (payload) => {
        const frame = JSON.parse(payload);
        sent.push(frame);
        if (frame.type === "join_room") {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "room_joined",
              room_id: frame.room_id,
            });
          }, 0);
        }
        if (frame.type === "send_message") {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "message",
              room_id: "room-b",
              agent_id: "agent-a",
              text: frame.text,
            });
          }, 0);
        }
      },
    };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    const result = await dispatchZenlinkTool(session, "zenlink_send_message", {
      room_id: "room-b",
      text: "reply to B",
    });
    const echo = JSON.parse(result.content[0].text);
    assert.equal(echo.room_id, "room-b");
    assert.deepEqual(sent.map((frame) => frame.type), ["join_room", "send_message"]);
    assert.equal(session.status().current_room_id, "room-b");
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("send_message with trusted current room skips redundant join", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const sent = [];
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = {
      readyState: 1,
      send: (payload) => {
        const frame = JSON.parse(payload);
        sent.push(frame);
        if (frame.type === "join_room") {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "room_joined",
              room_id: frame.room_id,
            });
          }, 0);
        }
        if (frame.type === "send_message") {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "message",
              room_id: "room-b",
              agent_id: "agent-a",
              text: frame.text,
            });
          }, 0);
        }
      },
    };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    await session.joinRoomTool("room-b");
    sent.length = 0;

    const result = await dispatchZenlinkTool(session, "zenlink_send_message", {
      room_id: "room-b",
      text: "reply without redundant join",
    });
    const echo = JSON.parse(result.content[0].text);
    assert.equal(echo.room_id, "room-b");
    assert.deepEqual(sent.map((frame) => frame.type), ["send_message"]);
    assert.equal(session.status().room_online_assumption, "confirmed");
    assert.equal(session.status().room_join_skipped_total, 1);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("zenlink_doctor tells agent to drain queued inbound frames", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = { readyState: 1 };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({
        hookBase: "http://127.0.0.1:18789/hooks",
        hookToken: "secret",
        fetchImpl: async () => new Response("{}", { status: 200 }),
      }),
    );

    session.injectInboundForTest({
      type: "message",
      room_id: "room-1",
      agent_id: "peer-agent",
      text: "please handle me",
    });

    const result = await dispatchZenlinkTool(session, "zenlink_doctor", {});
    const report = JSON.parse(result.content[0].text);
    assert.equal(report.schema, "zenlink_doctor/v1");
    assert.equal(report.agent_next_action, "Call zenlink_wake_drain before replying.");
    assert.ok(report.findings.some((finding) => finding.id === "inbound_waiting_for_drain"));
    assert.equal(report.status_evidence.inbound_queue_depth, 1);
    assert.equal(report.status_evidence.openclaw_push.delivery_mode, "agent");
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("join_room treats already_in_room as idempotent success", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const sent = [];
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = {
      readyState: 1,
      send: (payload) => sent.push(JSON.parse(payload)),
    };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    const joinPromise = session.joinRoomTool("room-1");
    setTimeout(() => {
      session.injectInboundForTest({
        type: "error",
        reason: "already_in_room",
        room_id: "room-1",
      });
    }, 0);

    const result = await joinPromise;
    assert.deepEqual(sent, [{ type: "join_room", room_id: "room-1" }]);
    assert.equal(result.ok, true);
    assert.equal(result.type, "room_joined");
    assert.equal(result.room_id, "room-1");
    assert.equal(result.already_in_room, true);
    assert.equal(session.status().current_room_id, "room-1");
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("join_room ignores already_in_room for a different room", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 30,
    });
    client.socket = { readyState: 1, send: () => {} };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    const joinPromise = session.joinRoomTool("room-1");
    setTimeout(() => {
      session.injectInboundForTest({
        type: "error",
        reason: "already_in_room",
        room_id: "room-2",
      });
    }, 0);

    await assert.rejects(joinPromise, /timeout waiting for ZenHeart frame/);
    assert.equal(session.status().current_room_id, null);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("inbound_wait returns HTTP backfill diagnostics after WS timeout", async () => {
  const previousLongLived = process.env.ZENLINK_MCP_LONG_LIVED;
  const previousFetch = globalThis.fetch;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    client.socket = { readyState: 1 };
    client.markAuthenticatedForTest();
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );
    session.currentRoomId = "room-1";
    globalThis.fetch = async (url) => {
      assert.match(String(url), /\/v2\/social\/rooms\/room-1\/messages/);
      return new Response(
        JSON.stringify({
          room_id: "room-1",
          messages: [{ id: "m-1", text: "backfilled" }],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    };

    const result = await session.inboundWait(4, 5, ["message"]);
    assert.equal(result.source, "http_backfill");
    assert.equal(result.reason, "ws_wait_timeout");
    assert.equal(result.frames.length, 0);
    assert.equal(result.backfill.result.messages[0].text, "backfilled");
    const status = session.status();
    assert.equal(status.wait_timeout_total, 1);
    assert.equal(status.last_backfill_error, null);
    assert.ok(status.last_wait_timeout_at);
    assert.ok(status.last_backfill_at);
  } finally {
    globalThis.fetch = previousFetch;
    if (previousLongLived === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previousLongLived;
    }
  }
});

test("wsRpc rejects immediately when the WebSocket closes", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  let closeHandler = null;
  try {
    const client = {
      agentId: "agent-a",
      wsTimeoutMs: 5_000,
      httpBaseUrl: "http://example.invalid",
      onMessage: () => () => {},
      onClose: (handler) => {
        closeHandler = handler;
        return () => {};
      },
      onError: () => () => {},
      isOnline: () => true,
      connectionState: () => "authenticated",
      sendJson: () => {},
    };
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );
    const pending = session.wsRpc(["never"], () => {});
    await Promise.resolve();
    await Promise.resolve();
    closeHandler({ code: 1006, reason: "test close", at: new Date().toISOString() });
    await assert.rejects(pending, /WebSocket closed/);
    assert.equal(session.status().passive_disconnect_total, 1);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("wsRpc can observe self message echo before inbound self-echo drop", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  try {
    const client = {
      agentId: "agent-a",
      wsTimeoutMs: 5_000,
      httpBaseUrl: "http://example.invalid",
      onMessage: () => () => {},
      onClose: () => () => {},
      onError: () => () => {},
      isOnline: () => true,
      connectionState: () => "authenticated",
    };
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );
    const pending = session.wsRpc(
      (frame) => frame.type === "message" && frame.agent_id === "agent-a",
      () => {
        session.injectInboundForTest({
          type: "message",
          room_id: "room-1",
          agent_id: "agent-a",
          text: "self echo",
        });
      },
    );

    const echo = await pending;
    assert.equal(echo.text, "self echo");
    const poll = session.inboundPoll(4, ["message"]);
    assert.equal(poll.frames.length, 0);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("inbound queue drops ping and evicts non-message frames first", () => {
  const previousLongLived = process.env.ZENLINK_MCP_LONG_LIVED;
  const previousQueueMax = process.env.ZENLINK_MCP_INBOUND_QUEUE_MAX;
  const previousDropTypes = process.env.ZENLINK_MCP_INBOUND_DROP_TYPES;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  process.env.ZENLINK_MCP_INBOUND_QUEUE_MAX = "2";
  delete process.env.ZENLINK_MCP_INBOUND_DROP_TYPES;
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );
    session.injectInboundForTest({ type: "ping" });
    session.injectInboundForTest({ type: "typing", id: "drop-me" });
    session.injectInboundForTest({ type: "message", id: "keep-me" });
    session.injectInboundForTest({ type: "msgbox_notify", id: "new-message" });
    const poll = session.inboundPoll(10);
    assert.deepEqual(
      poll.frames.map((frame) => frame.id),
      ["keep-me", "new-message"],
    );
    assert.equal(poll.stats.overflow_dropped_total, 1);
  } finally {
    if (previousLongLived === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previousLongLived;
    }
    if (previousQueueMax === undefined) {
      delete process.env.ZENLINK_MCP_INBOUND_QUEUE_MAX;
    } else {
      process.env.ZENLINK_MCP_INBOUND_QUEUE_MAX = previousQueueMax;
    }
    if (previousDropTypes === undefined) {
      delete process.env.ZENLINK_MCP_INBOUND_DROP_TYPES;
    } else {
      process.env.ZENLINK_MCP_INBOUND_DROP_TYPES = previousDropTypes;
    }
  }
});
