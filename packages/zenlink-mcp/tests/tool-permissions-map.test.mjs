import test from "node:test";
import assert from "node:assert/strict";

import {
  ZENLINK_MCP_TOOL_NAMES_SORTED,
  ZENLINK_TOOL_PERMISSION_ROWS,
  getZenlinkToolPermissionRow,
} from "../dist/tools/tool-permissions-map.js";

test("permission map has 72 tools and unique names", () => {
  const names = ZENLINK_MCP_TOOL_NAMES_SORTED;
  assert.equal(names.length, 72);
  const set = new Set(names);
  assert.equal(set.size, 72);
});

test("permission map rows are sorted by tool name", () => {
  const sorted = [...ZENLINK_TOOL_PERMISSION_ROWS].sort((a, b) =>
    a.tool.localeCompare(b.tool),
  );
  assert.deepEqual(
    ZENLINK_TOOL_PERMISSION_ROWS.map((r) => r.tool),
    sorted.map((r) => r.tool),
  );
});

test("getZenlinkToolPermissionRow returns sovereign hint for global msgbox", () => {
  const row = getZenlinkToolPermissionRow("zenlink_get_inbox_global");
  assert.ok(row);
  assert.equal(row.sovereignOnly, true);
  assert.equal(row.plane, "msgbox_global_sovereign");
});

test("getZenlinkToolPermissionRow is undefined for unknown tool", () => {
  assert.equal(getZenlinkToolPermissionRow("zenlink_not_a_tool"), undefined);
});
