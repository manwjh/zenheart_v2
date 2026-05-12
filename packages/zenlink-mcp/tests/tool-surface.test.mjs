import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import {
  ZENLINK_MCP_CORE_TOOL_NAMES,
  ZENLINK_MCP_TOOL_NAMES_SORTED,
  resolveZenlinkEnabledToolNames,
  resolveZenlinkMcpToolsetModeFromEnv,
} from "../dist/tools/tool-permissions-map.js";

const facadeTools = [
  "zenlink_a2a",
  "zenlink_connection",
  "zenlink_room",
];

function readSource(relativePath) {
  return readFileSync(join(process.cwd(), relativePath), "utf8");
}

function sortedUnique(values) {
  return [...new Set(values)].sort();
}

test("tool permission map has stable full and core surfaces", () => {
  assert.equal(ZENLINK_MCP_TOOL_NAMES_SORTED.length, 3);
  assert.equal(new Set(ZENLINK_MCP_TOOL_NAMES_SORTED).size, 3);
  assert.equal(ZENLINK_MCP_CORE_TOOL_NAMES.length, 3);

  for (const tool of ZENLINK_MCP_CORE_TOOL_NAMES) {
    assert.ok(
      ZENLINK_MCP_TOOL_NAMES_SORTED.includes(tool),
      `${tool} must be part of the full tool surface`,
    );
  }

  for (const tool of facadeTools) {
    assert.ok(
      ZENLINK_MCP_TOOL_NAMES_SORTED.includes(tool),
      `${tool} must be exposed in the full tool surface`,
    );
  }

  for (const tool of facadeTools) {
    assert.ok(
      ZENLINK_MCP_CORE_TOOL_NAMES.includes(tool),
      `${tool} should be visible in the curated core toolset`,
    );
  }
});

test("toolset mode resolves full by default and core by env", () => {
  assert.equal(resolveZenlinkMcpToolsetModeFromEnv({}), "full");
  assert.equal(resolveZenlinkMcpToolsetModeFromEnv({ ZENLINK_MCP_TOOLSET: "core" }), "core");
  assert.equal(
    resolveZenlinkEnabledToolNames("full").size,
    ZENLINK_MCP_TOOL_NAMES_SORTED.length,
  );
  assert.equal(
    resolveZenlinkEnabledToolNames("core").size,
    ZENLINK_MCP_CORE_TOOL_NAMES.length,
  );
});

test("registered tool names match the permission map", () => {
  const serverSource = readSource("src/transport/server.ts");
  const registered = sortedUnique(
    [...serverSource.matchAll(/registerTool\(\s*"([^"]+)"/g)].map((m) => m[1]),
  );
  assert.deepEqual(registered, [...ZENLINK_MCP_TOOL_NAMES_SORTED].sort());
});

test("permission-map tool names have dispatch cases", () => {
  const dispatchSource = readSource("src/tools/tool-dispatch.ts");
  const dispatched = new Set(
    [...dispatchSource.matchAll(/case\s+"([^"]+)":/g)].map((m) => m[1]),
  );

  for (const tool of ZENLINK_MCP_TOOL_NAMES_SORTED) {
    assert.ok(dispatched.has(tool), `${tool} must have a dispatch case`);
  }
});
