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

test("self social_notify message preview is dropped before FIFO and wake", async () => {
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
      type: "social_notify",
      kind: "message",
      id: "msg-self",
      room_id: "room-1",
      sender_agent_id: "agent-a",
      sender_agent_name: "Agent A",
      text_preview: "收到 21 -> 22",
      payload_authority: "notify_preview",
    });

    assert.equal(requests.length, 0);
    assert.equal(session.inboundStats().depth, 0);
    assert.equal(session.status().self_echo_dropped_total, 1);
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

test("topic suggestion snapshots replace stale pending queue entries", async () => {
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
      type: "topic_suggestions_pending",
      room_id: "room-1",
      topics: [{ id: "topic-1", text: "old topic", created_at: "2026-05-12T00:00:00Z" }],
    });
    session.injectInboundForTest({
      type: "topic_suggestions_pending",
      room_id: "room-1",
      topics: [],
    });

    assert.equal(session.inboundStats().depth, 1);
    const result = session.inboundPoll(4, ["topic_suggestions_pending"]);
    assert.equal(result.frames.length, 1);
    assert.deepEqual(result.frames[0].topics, []);
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
      reply_to_message_id: "00000000-0000-4000-8000-000000000001",
      expected_last_message_id: "00000000-0000-4000-8000-000000000001",
    });
    const echo = JSON.parse(result.content[0].text);
    assert.equal(echo.room_id, "room-b");
    assert.deepEqual(sent.map((frame) => frame.type), ["join_room", "send_message"]);
    assert.equal(sent[1].reply_to_message_id, "00000000-0000-4000-8000-000000000001");
    assert.equal(sent[1].expected_last_message_id, "00000000-0000-4000-8000-000000000001");
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
  const previousFetch = globalThis.fetch;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  globalThis.fetch = async (url) => {
    const href = String(url);
    if (href.endsWith("/v2/protocol/agent-native-site-world/v0.1")) {
      return new Response(JSON.stringify({
        protocol: "agent-native-site-world/v0.1",
        drafter: "www.zenheart.net",
        bindings: {},
        artifacts: {},
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return previousFetch(url);
  };
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
    assert.match(report.agent_next_action, /Call zenlink_wake_drain/);
    assert.match(report.agent_next_action, /remaining_inbound_queue_depth is 0/);
    assert.ok(report.findings.some((finding) => finding.id === "inbound_waiting_for_drain"));
    assert.equal(report.status_evidence.inbound_queue_depth, 1);
    assert.equal(report.status_evidence.openclaw_push.delivery_mode, "agent");
    assert.equal(report.status_evidence.wake_policy.mode, "default");
    assert.equal(report.config.wake_policy.mode, "default");
    assert.equal(report.status_evidence.agent_native_protocol.available, true);
  } finally {
    globalThis.fetch = previousFetch;
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("wake_policy facade controls runtime policy and status", async () => {
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
    const session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    const setResult = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "wake_policy",
      payload: {
        action: "set",
        wake_signals: ["room.message", "msgbox.notify"],
      },
    });
    const setPayload = JSON.parse(setResult.content[0].text);
    assert.equal(setPayload.policy.mode, "allowlist");
    assert.deepEqual(setPayload.policy.wake_signals, ["msgbox.notify", "room.message"]);
    assert.equal(setPayload.policy.updated_by, "mcp");
    assert.equal(session.status().wake_policy.mode, "allowlist");

    const getResult = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "wake_policy",
      payload: { action: "get" },
    });
    const getPayload = JSON.parse(getResult.content[0].text);
    assert.deepEqual(getPayload.policy.wake_signals, ["msgbox.notify", "room.message"]);

    const resetResult = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "wake_policy",
      payload: { action: "reset" },
    });
    const resetPayload = JSON.parse(resetResult.content[0].text);
    assert.equal(resetPayload.policy.mode, "default");
    assert.equal(resetPayload.policy.wake_signals, null);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("wake_drain remains controlled by per-call tool arguments", async () => {
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
      room_id: "room-1",
      agent_id: "peer-agent",
      text: "first",
    });
    session.injectInboundForTest({
      type: "social_notify",
      kind: "message",
      room_id: "room-1",
      agent_id: "peer-agent",
      text: "preview",
    });

    const result = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "wake_drain",
      payload: {
        timeout_ms: 0,
        limit: 1,
        types: ["message"],
        include_inbox: false,
      },
    });
    const payload = JSON.parse(result.content[0].text);
    assert.equal(payload.inbound.frames.length, 1);
    assert.equal(payload.inbound.frames[0].type, "message");
    assert.equal(payload.inbox_summary, null);
    assert.equal(payload.inbox, null);
    assert.equal(payload.remaining_inbound_queue_depth, 0);
    assert.equal(payload.remaining_matching_inbound_queue_depth, 0);
    assert.equal(payload.remaining_raw_inbound_queue_depth, 1);
    assert.equal(payload.continue_drain, false);
  } finally {
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("zenlink_self facade calls agent space-self HTTP endpoints", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  const previousFetch = globalThis.fetch;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  const requests = [];
  globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    const request = {
      method: init.method ?? "GET",
      href,
      body: init.body ? JSON.parse(String(init.body)) : null,
      agentId: init.headers?.["X-Agent-Id"],
    };
    requests.push(request);
    if (request.method === "DELETE") {
      return new Response(null, { status: 204 });
    }
    return new Response(JSON.stringify({ ok: true, href, method: request.method }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
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

    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "snapshot",
      payload: { limit: 5 },
    });
    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "list_relationships",
      payload: { relation_type: "trusted", limit: 20 },
    });
    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "upsert_relationship",
      payload: {
        target_agent_id: "agent-b",
        relation_type: "trusted",
        visibility: "private",
        note: "Good collaborator.",
      },
    });
    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "delete_relationship",
      payload: { target_agent_id: "agent-b" },
    });
    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "list_resources",
      payload: { resource_type: "room", relation_type: "pinned", limit: 10 },
    });
    await dispatchZenlinkTool(session, "zenlink_self", {
      action: "upsert_resource",
      payload: {
        resource_type: "topic",
        resource_id: "protocol-garden",
        relation_type: "featured",
        visibility: "public",
        title: "Protocol Garden",
        note: "Representative topic.",
      },
    });
    const deleteResult = await dispatchZenlinkTool(session, "zenlink_self", {
      action: "delete_resource",
      payload: { resource_pin_id: "pin-1" },
    });
    const deletePayload = JSON.parse(deleteResult.content[0].text);
    assert.deepEqual(deletePayload, { ok: true });

    assert.deepEqual(
      requests.map((request) => [request.method, new URL(request.href).pathname]),
      [
        ["GET", "/v2/agent/space-self"],
        ["GET", "/v2/agent/space-self/relationships"],
        ["PUT", "/v2/agent/space-self/relationships/agent-b"],
        ["DELETE", "/v2/agent/space-self/relationships/agent-b"],
        ["GET", "/v2/agent/space-self/resources"],
        ["PUT", "/v2/agent/space-self/resources"],
        ["DELETE", "/v2/agent/space-self/resources/pin-1"],
      ],
    );
    assert.equal(new URL(requests[0].href).searchParams.get("limit"), "5");
    assert.equal(new URL(requests[1].href).searchParams.get("relation_type"), "trusted");
    assert.equal(new URL(requests[4].href).searchParams.get("resource_type"), "room");
    assert.equal(requests[2].body.relation_type, "trusted");
    assert.equal(requests[5].body.resource_id, "protocol-garden");
    assert.equal(requests[0].agentId, "agent-a");
  } finally {
    globalThis.fetch = previousFetch;
    if (previous === undefined) {
      delete process.env.ZENLINK_MCP_LONG_LIVED;
    } else {
      process.env.ZENLINK_MCP_LONG_LIVED = previous;
    }
  }
});

test("zenlink_connection exposes agent-native protocol discovery and artifacts", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  const previousFetch = globalThis.fetch;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  const requests = [];
  globalThis.fetch = async (url) => {
    const href = String(url);
    requests.push(href);
    if (href.endsWith("/v2/protocol/agent-native-site-world/v0.1")) {
      return new Response(JSON.stringify({
        protocol: "agent-native-site-world/v0.1",
        drafter: "www.zenheart.net",
        artifacts: {
          schemas: "/v2/protocol/agent-native-site-world/v0.1/schemas",
        },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (href.endsWith("/v2/protocol/agent-native-site-world/v0.1/schemas")) {
      return new Response(JSON.stringify({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": { AuthFrame: {} },
      }), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response("not found", { status: 404 });
  };
  try {
    const client = new ZenlinkClient({
      agentId: "agent-a",
      token: "token-a",
      host: "example.invalid",
      useTls: false,
      wsTimeoutMs: 100,
    });
    const session = new ZenlinkSession(client);

    const discoveryResult = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "protocol_discovery",
    });
    const discovery = JSON.parse(discoveryResult.content[0].text);
    assert.equal(discovery.protocol, "agent-native-site-world/v0.1");
    assert.equal(discovery.drafter, "www.zenheart.net");

    const artifactResult = await dispatchZenlinkTool(session, "zenlink_connection", {
      action: "protocol_artifact",
      payload: { artifact: "schemas" },
    });
    const artifact = JSON.parse(artifactResult.content[0].text);
    assert.equal(artifact.$schema, "https://json-schema.org/draft/2020-12/schema");
    assert.deepEqual(requests, [
      "http://example.invalid/v2/protocol/agent-native-site-world/v0.1",
      "http://example.invalid/v2/protocol/agent-native-site-world/v0.1/schemas",
    ]);
  } finally {
    globalThis.fetch = previousFetch;
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

test("room restore rejects when joined roster does not include self", async () => {
  const previous = process.env.ZENLINK_MCP_LONG_LIVED;
  process.env.ZENLINK_MCP_LONG_LIVED = "0";
  let closeHandler = null;
  let session;
  try {
    const sent = [];
    let restoring = false;
    const client = {
      agentId: "agent-a",
      wsTimeoutMs: 100,
      httpBaseUrl: "http://example.invalid",
      onMessage: () => () => {},
      onClose: (handler) => {
        closeHandler = handler;
        return () => {};
      },
      onError: () => () => {},
      isOnline: () => true,
      connectionState: () => "authenticated",
      sendJson: (frame) => {
        sent.push(frame);
        if (frame.type === "join_room" && !restoring) {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "room_joined",
              room_id: frame.room_id,
              members: [{ agent_id: "agent-a", agent_name: "Agent A" }],
            });
          }, 0);
          return;
        }
        if (frame.type === "join_room" && restoring) {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "room_joined",
              room_id: frame.room_id,
              members: [{ agent_id: "agent-b", agent_name: "Agent B" }],
            });
          }, 0);
          return;
        }
        if (frame.type === "send_message") {
          setTimeout(() => {
            session.injectInboundForTest({
              type: "message",
              room_id: "room-1",
              agent_id: "agent-a",
              text: frame.text,
            });
          }, 0);
        }
      },
    };
    session = new ZenlinkSession(
      client,
      new OpenClawWakeNotifier({ hookBase: "", hookToken: "" }),
    );

    await session.joinRoomTool("room-1");
    restoring = true;
    sent.length = 0;
    closeHandler({ code: 1006, reason: "test close", at: new Date().toISOString() });

    await assert.rejects(
      () => session.sendMessageTool("after restore"),
      /restore join_room members did not include agent_id agent-a/,
    );
    assert.deepEqual(sent, [{ type: "join_room", room_id: "room-1" }]);
    const status = session.status();
    assert.equal(status.current_room_id, "room-1");
    assert.equal(status.room_online_assumption, "restore_pending");
    assert.equal(status.room_restore_pending, false);
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
    let backfillAgentId = null;
    let backfillAgentToken = null;
    globalThis.fetch = async (url, init) => {
      assert.match(String(url), /\/v2\/social\/rooms\/room-1\/messages/);
      const headers = new Headers(init?.headers);
      backfillAgentId = headers.get("X-Agent-Id");
      backfillAgentToken = headers.get("X-Agent-Token");
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
    assert.equal(backfillAgentId, "agent-a");
    assert.equal(backfillAgentToken, "token-a");
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
