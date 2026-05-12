/**
 * Canonical MCP tool surface for non-L0 agent runtime communication.
 * The public surface is intentionally small: connection, room, A2A, and space self.
 */

export type ZenlinkToolPlane = "connection" | "room" | "a2a" | "self";

export type ZenheartPermissionRef = {
  module: string;
  action: string;
};

export type ZenlinkToolPermissionRow = {
  tool: string;
  plane: ZenlinkToolPlane;
  sovereignOnly: boolean;
  /** Optional alignment with level_permissions (module, action) when stable in product docs. */
  permissionRef?: ZenheartPermissionRef;
};

const ZENLINK_TOOL_PERMISSION_ROWS_UNSORTED: readonly ZenlinkToolPermissionRow[] = [
  { tool: "zenlink_a2a", plane: "a2a", sovereignOnly: false },
  { tool: "zenlink_connection", plane: "connection", sovereignOnly: false },
  { tool: "zenlink_room", plane: "room", sovereignOnly: false },
  { tool: "zenlink_self", plane: "self", sovereignOnly: false },
];

function sortRows(
  rows: readonly ZenlinkToolPermissionRow[],
): ZenlinkToolPermissionRow[] {
  return [...rows].sort((a, b) => a.tool.localeCompare(b.tool));
}

/** All tools, sorted by name (canonical order for smoke / CI). */
export const ZENLINK_TOOL_PERMISSION_ROWS: readonly ZenlinkToolPermissionRow[] =
  Object.freeze(sortRows(ZENLINK_TOOL_PERMISSION_ROWS_UNSORTED));

const BY_NAME = new Map(
  ZENLINK_TOOL_PERMISSION_ROWS.map((r) => [r.tool, r] as const),
);

/** Sorted tool names; same set as MCP registration. */
export const ZENLINK_MCP_TOOL_NAMES_SORTED: readonly string[] = Object.freeze(
  ZENLINK_TOOL_PERMISSION_ROWS.map((r) => r.tool),
);

/** Full and core are intentionally identical for the lightweight runtime MCP. */
export const ZENLINK_MCP_CORE_TOOL_NAMES: readonly string[] = Object.freeze([
  "zenlink_a2a",
  "zenlink_connection",
  "zenlink_room",
  "zenlink_self",
]);

const CORE_SET = new Set(ZENLINK_MCP_CORE_TOOL_NAMES);

export type ZenlinkMcpToolsetMode = "core" | "full";

export function resolveZenlinkMcpToolsetModeFromEnv(
  env: NodeJS.ProcessEnv = process.env,
): ZenlinkMcpToolsetMode {
  const raw = (env["ZENLINK_MCP_TOOLSET"] ?? "full").trim().toLowerCase();
  if (raw === "core") {
    return "core";
  }
  return "full";
}

export function resolveZenlinkEnabledToolNames(
  mode: ZenlinkMcpToolsetMode,
): ReadonlySet<string> {
  if (mode === "core") {
    return CORE_SET;
  }
  return new Set(ZENLINK_MCP_TOOL_NAMES_SORTED);
}

export function getZenlinkToolPermissionRow(
  tool: string,
): ZenlinkToolPermissionRow | undefined {
  return BY_NAME.get(tool);
}
