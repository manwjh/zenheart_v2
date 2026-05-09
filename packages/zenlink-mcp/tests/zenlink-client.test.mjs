import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { WebSocketServer } from "ws";

import { ZenlinkClient } from "../dist/zenlink/client.js";

async function createServer() {
  const server = new WebSocketServer({ host: "127.0.0.1", port: 0 });
  await once(server, "listening");
  return server;
}

async function closeServer(server) {
  for (const client of server.clients) {
    client.terminate();
  }
  await new Promise((resolve) => server.close(resolve));
}

test("ZenlinkClient is online only after auth_ok", async () => {
  const server = await createServer();
  const port = server.address().port;
  server.on("connection", (socket) => {
    socket.once("message", () => {
      socket.send(JSON.stringify({ type: "auth_ok" }));
    });
  });
  const client = new ZenlinkClient({
    agentId: "agent-a",
    token: "token-a",
    host: `127.0.0.1:${port}`,
    useTls: false,
    wsTimeoutMs: 200,
    wsPingIntervalMs: 0,
  });
  try {
    assert.equal(client.isOnline(), false);
    await client.connect();
    assert.equal(client.connectionState(), "authenticated");
    assert.equal(client.isOnline(), true);
  } finally {
    client.disconnect();
    await closeServer(server);
  }
});

test("ZenlinkClient closes stale socket after auth timeout", async () => {
  const server = await createServer();
  const port = server.address().port;
  server.on("connection", () => {});
  const client = new ZenlinkClient({
    agentId: "agent-a",
    token: "token-a",
    host: `127.0.0.1:${port}`,
    useTls: false,
    wsTimeoutMs: 20,
    wsPingIntervalMs: 0,
  });
  try {
    await assert.rejects(() => client.connect(), /timeout waiting for auth_ok/);
    assert.equal(client.connectionState(), "offline");
    assert.equal(client.isOnline(), false);
  } finally {
    client.disconnect();
    await closeServer(server);
  }
});

test("ZenlinkClient answers server JSON ping with JSON pong", async () => {
  const server = await createServer();
  const port = server.address().port;
  const pongSeen = new Promise((resolve) => {
    server.on("connection", (socket) => {
      socket.on("message", (data) => {
        const frame = JSON.parse(data.toString());
        if (frame.type === "auth") {
          socket.send(JSON.stringify({ type: "auth_ok" }));
          socket.send(JSON.stringify({ type: "ping" }));
        } else if (frame.type === "pong") {
          resolve(frame);
        }
      });
    });
  });
  const client = new ZenlinkClient({
    agentId: "agent-a",
    token: "token-a",
    host: `127.0.0.1:${port}`,
    useTls: false,
    wsTimeoutMs: 200,
    wsPingIntervalMs: 0,
  });
  try {
    await client.connect();
    assert.deepEqual(await pongSeen, { type: "pong" });
  } finally {
    client.disconnect();
    await closeServer(server);
  }
});
