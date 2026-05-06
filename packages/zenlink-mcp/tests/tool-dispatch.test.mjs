import test from "node:test";
import assert from "node:assert/strict";

import {
  dispatchZenlinkTool,
  okJson,
  toolTry,
} from "../dist/tools/tool-dispatch.js";

test("okJson serializes payload as text content", () => {
  const result = okJson({ ok: true, value: 1 });
  assert.equal(result.isError, undefined);
  assert.equal(result.content.length, 1);
  assert.equal(result.content[0].type, "text");
  const parsed = JSON.parse(result.content[0].text);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.value, 1);
});

test("okJson uses compact JSON when ZENLINK_MCP_COMPACT_TOOL_JSON is set", () => {
  process.env.ZENLINK_MCP_COMPACT_TOOL_JSON = "1";
  try {
    const result = okJson({ a: 1, b: 2 });
    assert.ok(!result.content[0].text.includes("\n"));
    assert.deepEqual(JSON.parse(result.content[0].text), { a: 1, b: 2 });
  } finally {
    delete process.env.ZENLINK_MCP_COMPACT_TOOL_JSON;
  }
});

test("toolTry captures thrown errors as tool errors", async () => {
  const result = await toolTry(async () => {
    throw new Error("boom");
  });
  assert.equal(result.isError, true);
  assert.equal(result.content[0].type, "text");
  assert.equal(result.content[0].text, "boom");
});

test("dispatchZenlinkTool returns unknown-tool error", async () => {
  const result = await dispatchZenlinkTool({}, "zenlink_not_exist", {});
  assert.equal(result.isError, true);
  assert.match(result.content[0].text, /unknown tool: zenlink_not_exist/);
});

test("dispatchZenlinkTool routes zenlink_inbound_wait to session", async () => {
  const calls = [];
  const session = {
    client: {},
    inboundWait: async (limit, timeoutMs, types) => {
      calls.push({ limit, timeoutMs, types });
      return {
        frames: [{ type: "message", text: "ok" }],
        remaining: 0,
        overflow_dropped_total: 0,
        type_filter_applied: types ?? null,
      };
    },
  };
  const result = await dispatchZenlinkTool(session, "zenlink_inbound_wait", {
    timeout_ms: 1000,
    limit: 5,
    types: ["message"],
  });
  assert.equal(result.isError, undefined);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0], {
    limit: 5,
    timeoutMs: 1000,
    types: ["message"],
  });
});
