import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  DaemonRpcClient,
  parseAddrFileLine,
  readDaemonTokenFile,
} from "../dist/daemon/daemon-ipc.js";
import { canRunWithoutSessionMutation } from "../dist/daemon/daemon.js";

test("daemon addr parsing keeps host and port stable", () => {
  assert.deepEqual(parseAddrFileLine("127.0.0.1:54321\n"), {
    host: "127.0.0.1",
    port: 54321,
  });
  assert.throws(() => parseAddrFileLine("127.0.0.1:not-a-port"), /invalid/);
});

test("daemon token is read from addr sibling file", () => {
  const dir = mkdtempSync(join(tmpdir(), "zenlink-daemon-token-"));
  const addrFile = join(dir, "zenlink-mcp-daemon.addr");
  writeFileSync(`${addrFile}.token`, "secret-token\n", "utf8");
  assert.equal(readDaemonTokenFile(addrFile), "secret-token");
});

test("parseAddrFileLine parses valid host/port", () => {
  const out = parseAddrFileLine("127.0.0.1:18444");
  assert.deepEqual(out, { host: "127.0.0.1", port: 18444 });
});

test("parseAddrFileLine trims whitespace", () => {
  const out = parseAddrFileLine("  localhost:3000  ");
  assert.deepEqual(out, { host: "localhost", port: 3000 });
});

test("parseAddrFileLine rejects malformed lines", () => {
  assert.throws(() => parseAddrFileLine("noport"), /invalid daemon addr line/i);
  assert.throws(
    () => parseAddrFileLine("127.0.0.1:99999"),
    /invalid daemon addr/i,
  );
  assert.throws(() => parseAddrFileLine(":1234"), /invalid daemon addr line/i);
});

test("DaemonRpcClient rejects pending calls on malformed daemon JSON", async () => {
  const client = new DaemonRpcClient("127.0.0.1", 1, "token");
  const pending = new Promise((resolve, reject) => {
    client.pending.set(1, { resolve, reject, timer: null });
  });
  client.onData("{not-json}\n");
  await assert.rejects(pending, /invalid daemon response JSON/);
  assert.equal(client.pending.size, 0);
});

test("daemon serializes queue-draining tools", () => {
  for (const tool of [
    "zenlink_wake_drain",
    "zenlink_inbound_wait",
    "zenlink_inbound_poll",
  ]) {
    assert.equal(canRunWithoutSessionMutation(tool), false);
  }
  for (const tool of [
    "zenlink_status",
    "zenlink_doctor",
    "zenlink_inbound_stats",
  ]) {
    assert.equal(canRunWithoutSessionMutation(tool), true);
  }
});
