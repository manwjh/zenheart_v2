import test from "node:test";
import assert from "node:assert/strict";

import {
  ZENLINK_MCP_CORE_TOOL_NAMES,
  ZENLINK_MCP_TOOL_NAMES_SORTED,
  resolveZenlinkEnabledToolNames,
  resolveZenlinkMcpToolsetModeFromEnv,
} from "../dist/tools/tool-permissions-map.js";

test("toolset mode defaults to full", () => {
  assert.equal(resolveZenlinkMcpToolsetModeFromEnv({}), "full");
});

test("toolset mode accepts core", () => {
  assert.equal(
    resolveZenlinkMcpToolsetModeFromEnv({ ZENLINK_MCP_TOOLSET: "core" }),
    "core",
  );
});

test("core toolset names are subset of full list", () => {
  const fullSet = new Set(ZENLINK_MCP_TOOL_NAMES_SORTED);
  for (const name of ZENLINK_MCP_CORE_TOOL_NAMES) {
    assert.equal(fullSet.has(name), true, `core tool missing in full set: ${name}`);
  }
});

test("resolve enabled tools returns smaller set for core", () => {
  const core = resolveZenlinkEnabledToolNames("core");
  const full = resolveZenlinkEnabledToolNames("full");
  assert.equal(core.size < full.size, true);
  assert.equal(full.size, ZENLINK_MCP_TOOL_NAMES_SORTED.length);
});
