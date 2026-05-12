import test from "node:test";
import assert from "node:assert/strict";

import { WakePolicy, signalOf } from "../dist/social/wake-policy.js";

test("wake policy uses default muted presence signals", () => {
  const policy = new WakePolicy();

  assert.equal(policy.shouldWakeSignal("room.message"), true);
  assert.equal(policy.shouldWakeSignal("msgbox.notify"), true);
  assert.equal(policy.shouldWakeSignal("room.member_joined"), false);
  assert.equal(policy.shouldWakeSignal("room.member_left_notify"), false);

  const status = policy.status();
  assert.equal(status.mode, "default");
  assert.equal(status.wake_signals, null);
  assert.ok(status.default_muted_signals.includes("room.member_joined"));
});

test("wake policy allowlist and reset are runtime mutable", () => {
  const policy = new WakePolicy();

  let status = policy.setAllowlist(["room.member_joined_notify", "room.message"]);
  assert.equal(status.mode, "allowlist");
  assert.deepEqual(status.wake_signals, ["room.member_joined_notify", "room.message"]);
  assert.equal(status.updated_by, "mcp");
  assert.equal(policy.shouldWakeSignal("room.member_joined_notify"), true);
  assert.equal(policy.shouldWakeSignal("msgbox.notify"), false);

  status = policy.reset();
  assert.equal(status.mode, "default");
  assert.equal(policy.shouldWakeSignal("msgbox.notify"), true);
  assert.equal(policy.shouldWakeSignal("room.member_joined_notify"), false);
});

test("wake policy classifies inbound frames into normalized signals", () => {
  assert.equal(signalOf({ type: "message" }), "room.message");
  assert.equal(signalOf({ type: "social_notify", kind: "message" }), "room.message_notify");
  assert.equal(signalOf({ type: "social_notify", kind: "room_dissolved" }), "room.dissolved");
  assert.equal(signalOf({ type: "custom_event" }), "frame.custom_event");
});
