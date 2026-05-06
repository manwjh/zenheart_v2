import test from "node:test";
import assert from "node:assert/strict";

import { ZenlinkInboundFrameBuffer } from "../dist/transport/session-inbound-buffer.js";

const SELF = "agt_self";
const PEER = "agt_peer";

function makeBuffer({ queueMax = 16, dropTypes = ["ping", "pong"] } = {}) {
  return new ZenlinkInboundFrameBuffer(
    queueMax,
    new Set(dropTypes),
    SELF,
  );
}

test("inbound buffer queues peer message frames", () => {
  const buf = makeBuffer();
  buf.tryEnqueue({ type: "message", agent_id: PEER, text: "hi" });
  const out = buf.poll(10);
  assert.equal(out.frames.length, 1);
  assert.equal(out.frames[0].agent_id, PEER);
  assert.equal(out.self_echo_dropped_total, 0);
  assert.equal(out.overflow_dropped_total, 0);
});

test("inbound buffer drops self message echoes (server broadcast loop)", () => {
  const buf = makeBuffer();
  buf.tryEnqueue({ type: "message", agent_id: SELF, text: "my own" });
  buf.tryEnqueue({ type: "message", agent_id: PEER, text: "peer" });
  const out = buf.poll(10);
  assert.equal(out.frames.length, 1);
  assert.equal(out.frames[0].agent_id, PEER);
  assert.equal(out.self_echo_dropped_total, 1);
});

test("inbound buffer drops self social_notify(message) echoes", () => {
  const buf = makeBuffer();
  buf.tryEnqueue({
    type: "social_notify",
    kind: "message",
    sender_agent_id: SELF,
    text_preview: "self preview",
  });
  buf.tryEnqueue({
    type: "social_notify",
    kind: "message",
    sender_agent_id: PEER,
    text_preview: "peer preview",
  });
  const out = buf.poll(10);
  assert.equal(out.frames.length, 1);
  assert.equal(out.frames[0].sender_agent_id, PEER);
  assert.equal(out.self_echo_dropped_total, 1);
});

test("inbound buffer skips configured drop types like ping/pong", () => {
  const buf = makeBuffer();
  buf.tryEnqueue({ type: "ping" });
  buf.tryEnqueue({ type: "pong" });
  buf.tryEnqueue({ type: "message", agent_id: PEER, text: "hi" });
  const out = buf.poll(10);
  assert.equal(out.frames.length, 1);
  assert.equal(out.frames[0].type, "message");
});

test("inbound buffer reports self echoes in stats output", () => {
  const buf = makeBuffer();
  buf.tryEnqueue({ type: "message", agent_id: SELF, text: "echo" });
  buf.tryEnqueue({ type: "message", agent_id: SELF, text: "echo2" });
  const stats = buf.stats();
  assert.equal(stats.queued, 0);
  assert.equal(stats.self_echo_dropped_total, 2);
});

test("inbound buffer overflow prefers evicting non-priority frames", () => {
  const buf = makeBuffer({ queueMax: 2 });
  buf.tryEnqueue({ type: "presence_update", agent_id: PEER });
  buf.tryEnqueue({ type: "message", agent_id: PEER, text: "first" });
  buf.tryEnqueue({ type: "message", agent_id: PEER, text: "second" });
  const out = buf.poll(10);
  assert.equal(out.frames.length, 2);
  assert.equal(out.frames.every((f) => f.type === "message"), true);
  assert.equal(out.overflow_dropped_total, 1);
});
