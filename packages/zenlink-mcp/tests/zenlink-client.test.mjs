import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { WebSocketServer } from "ws";

import { ZenlinkClient } from "../dist/zenlink/client.js";
import {
  formatZenlinkErrorFrame,
  ZenlinkProtocolError,
} from "../dist/zenlink/errors.js";
import { fetchMsgbox } from "../dist/zenlink/http.js";

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

test("ZenlinkClient formats auth_fail message and hint", async () => {
  const server = await createServer();
  const port = server.address().port;
  server.on("connection", (socket) => {
    socket.once("message", () => {
      socket.send(JSON.stringify({
        type: "auth_fail",
        reason: "invalid_token",
        code: "invalid_token",
        message: "The agent token is invalid.",
        hint: "Use the current plaintext token for this agent_id.",
        retryable: false,
        category: "auth",
        action: "fix_credentials",
      }));
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
    await assert.rejects(
      () => client.connect(),
      /invalid_token: The agent token is invalid\. Hint: Use the current plaintext token/,
    );
  } finally {
    client.disconnect();
    await closeServer(server);
  }
});

test("ZenlinkClient emits protocol errors for runtime error frames", async () => {
  const server = await createServer();
  const port = server.address().port;
  server.on("connection", (socket) => {
    socket.once("message", () => {
      socket.send(JSON.stringify({ type: "auth_ok" }));
      socket.send(JSON.stringify({
        type: "error",
        reason: "invalid_create_room_payload",
        code: "invalid_create_room_payload",
        message: "The request payload is invalid.",
        hint: "name must be 1-80 chars",
        retryable: false,
        category: "validation",
        action: "fix_payload",
      }));
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
  const errorSeen = new Promise((resolve) => {
    client.onError((error) => resolve(error));
  });
  try {
    await client.connect();
    const error = await errorSeen;
    assert.equal(error instanceof ZenlinkProtocolError, true);
    assert.equal(error.code, "invalid_create_room_payload");
    assert.equal(error.hint, "name must be 1-80 chars");
    assert.equal(error.category, "validation");
    assert.equal(error.action, "fix_payload");
    assert.match(error.message, /invalid_create_room_payload: The request payload is invalid/);
  } finally {
    client.disconnect();
    await closeServer(server);
  }
});

test("formatZenlinkErrorFrame falls back to legacy reason", () => {
  assert.equal(
    formatZenlinkErrorFrame({ type: "error", reason: "not_in_room" }),
    "not_in_room: ZenHeart error",
  );
});

test("HTTP helpers format structured server error hints", async () => {
  const fetchImpl = async () => new Response(
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
  );

  await assert.rejects(
    () => fetchMsgbox({
      baseUrl: "https://example.invalid",
      agentId: "agent-a",
      token: "token-a",
      fetchImpl,
    }),
    /msgbox list failed: 429 rate_limit_exceeded: The request exceeded its rate limit\. Hint: Back off/,
  );
});
