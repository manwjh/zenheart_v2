import test from "node:test";
import assert from "node:assert/strict";

import {
  ZENLINK_ROUTER_CONTEXT_VERSION,
  ZENLINK_ROUTER_RESULT_VERSION,
  normalizeRouterResult,
  packRouterContext,
} from "../dist/router/router-runtime.js";

test("packRouterContext returns versioned context and prompt block", () => {
  const packed = packRouterContext({
    agent: { id: "a1" },
    history: [{ role: "user", text: "hello" }],
  });

  assert.equal(packed.schema_version, ZENLINK_ROUTER_CONTEXT_VERSION);
  assert.equal(packed.value.schema_version, ZENLINK_ROUTER_CONTEXT_VERSION);
  assert.match(
    packed.prompt_block,
    /<zenheart_router_context version="zenlink\.router_context\/1">/,
  );
  assert.match(packed.prompt_block, /"agent": \{/);
});

test("normalizeRouterResult validates and preserves dispatch payload", () => {
  const out = normalizeRouterResult({
    schema_version: ZENLINK_ROUTER_RESULT_VERSION,
    persist: { artifact: { trace_id: "t-1" } },
    dispatch: { kind: "agent_dm", to_agent_id: "agent_b", body: "ping" },
  });

  assert.equal(out.schema_version, ZENLINK_ROUTER_RESULT_VERSION);
  assert.equal(out.dispatch?.kind, "agent_dm");
  assert.equal(out.persist?.artifact.trace_id, "t-1");
});

test("normalizeRouterResult rejects invalid result payload", () => {
  assert.throws(
    () =>
      normalizeRouterResult({
        dispatch: { kind: "agent_dm", to_agent_id: "agent_b" },
      }),
    /body/i,
  );
});
