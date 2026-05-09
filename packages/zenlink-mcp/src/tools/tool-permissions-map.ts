/**
 * Single map: MCP tool name -> coarse plane + sovereign hint + optional ZenHeart permission ref.
 * ZenHeart remains authoritative for enforcement; this table drives docs, smoke tool lists, and future registration filters.
 */

export type ZenlinkToolPlane =
  | "transport"
  | "social_ws"
  | "social_http"
  | "agent_http"
  | "msgbox_private"
  | "msgbox_global_sovereign"
  | "news_public_http"
  | "news_agent_ws"
  | "admin_http"
  | "admin_ws"
  | "profile"
  | "router_runtime"
  | "mcp_local";

export type ZenheartPermissionRef = {
  module: string;
  action: string;
};

export type ZenlinkToolPermissionRow = {
  tool: string;
  plane: ZenlinkToolPlane;
  /**
   * True when ZenHeart restricts this path to sovereign (level 0), e.g. global msgbox.
   * Server still returns forbidden for non-L0; this flag is MCP-side intent for registration/docs.
   */
  sovereignOnly: boolean;
  /** Optional alignment with level_permissions (module, action) when stable in product docs. */
  permissionRef?: ZenheartPermissionRef;
};

const ZENLINK_TOOL_PERMISSION_ROWS_UNSORTED: readonly ZenlinkToolPermissionRow[] = [
  {
    tool: "zenlink_ack_messages",
    plane: "msgbox_private",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_ack_messages_global",
    plane: "msgbox_global_sovereign",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_http", plane: "admin_http", sovereignOnly: true },
  { tool: "zenlink_admin_ws", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_connect", plane: "transport", sovereignOnly: false },
  {
    tool: "zenlink_create_room",
    plane: "social_ws",
    sovereignOnly: false,
    permissionRef: { module: "social", action: "create_room" },
  },
  { tool: "zenlink_disconnect", plane: "transport", sovereignOnly: false },
  { tool: "zenlink_doctor", plane: "transport", sovereignOnly: false },
  {
    tool: "zenlink_get_inbox",
    plane: "msgbox_private",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_get_inbox_global",
    plane: "msgbox_global_sovereign",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_get_inbox_summary",
    plane: "msgbox_private",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_msgbox",
    plane: "msgbox_global_sovereign",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_get_room_messages",
    plane: "social_http",
    sovereignOnly: false,
  },
  { tool: "zenlink_inbound_poll", plane: "transport", sovereignOnly: false },
  { tool: "zenlink_inbound_wait", plane: "transport", sovereignOnly: false },
  { tool: "zenlink_inbound_stats", plane: "transport", sovereignOnly: false },
  { tool: "zenlink_wake_drain", plane: "transport", sovereignOnly: false },
  {
    tool: "zenlink_join_room",
    plane: "social_ws",
    sovereignOnly: false,
    permissionRef: { module: "social", action: "join_room" },
  },
  { tool: "zenlink_leave_room", plane: "social_ws", sovereignOnly: false },
  {
    tool: "zenlink_list_room_members",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_list_rooms_agent",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_list_rooms_history",
    plane: "social_http",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_list_rooms_lobby",
    plane: "social_http",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_news_delete",
    plane: "news_agent_ws",
    sovereignOnly: false,
    permissionRef: { module: "news", action: "delete" },
  },
  {
    tool: "zenlink_news_get",
    plane: "news_public_http",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_news_list",
    plane: "news_public_http",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_news_manage",
    plane: "news_agent_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_news_publish",
    plane: "news_agent_ws",
    sovereignOnly: false,
    permissionRef: { module: "news", action: "publish" },
  },
  {
    tool: "zenlink_news_update",
    plane: "news_agent_ws",
    sovereignOnly: false,
    permissionRef: { module: "news", action: "update" },
  },
  {
    tool: "zenlink_participant_rules_get",
    plane: "mcp_local",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_participant_rules_set",
    plane: "mcp_local",
    sovereignOnly: false,
  },
  { tool: "zenlink_patch_profile", plane: "profile", sovereignOnly: false },
  {
    tool: "zenlink_pull_room_topics",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_rooms",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_router_apply_result",
    plane: "router_runtime",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_router_pack_context",
    plane: "router_runtime",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_send_dm",
    plane: "msgbox_private",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_send_message",
    plane: "social_ws",
    sovereignOnly: false,
    permissionRef: { module: "social", action: "send_message" },
  },
  {
    tool: "zenlink_send_message_to_all",
    plane: "social_ws",
    sovereignOnly: false,
    permissionRef: { module: "social", action: "send_message" },
  },
  {
    tool: "zenlink_social_grounding",
    plane: "mcp_local",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_start_long_lived",
    plane: "transport",
    sovereignOnly: false,
  },
  { tool: "zenlink_status", plane: "transport", sovereignOnly: false },
  {
    tool: "zenlink_update_room_access_lists",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_update_room_metadata",
    plane: "social_ws",
    sovereignOnly: false,
  },
  {
    tool: "zenlink_upload_image",
    plane: "agent_http",
    sovereignOnly: false,
  },
  { tool: "zenlink_admin_create_agent", plane: "admin_http", sovereignOnly: true },
  {
    tool: "zenlink_admin_delete_news_article",
    plane: "admin_http",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_delete_permission", plane: "admin_http", sovereignOnly: true },
  {
    tool: "zenlink_admin_dispatch_agent_command",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_get_agent_connection",
    plane: "admin_http",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_get_agent", plane: "admin_http", sovereignOnly: true },
  {
    tool: "zenlink_admin_get_news_article",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_get_social_delivery_stats",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_list_agent_event_logs",
    plane: "admin_http",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_list_agents", plane: "admin_http", sovereignOnly: true },
  {
    tool: "zenlink_admin_list_news_articles",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_list_news_columns",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_add_news_column",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_order_news_columns",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_delete_news_column",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_list_permissions",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_list_wall_messages",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_patch_agent_social_webhook",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_patch_news_article",
    plane: "admin_http",
    sovereignOnly: true,
  },
  {
    tool: "zenlink_admin_patch_wall_message",
    plane: "admin_http",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_revoke_agent", plane: "admin_http", sovereignOnly: true },
  {
    tool: "zenlink_admin_rotate_agent_token",
    plane: "admin_http",
    sovereignOnly: true,
  },
  { tool: "zenlink_admin_upsert_permission", plane: "admin_http", sovereignOnly: true },
  { tool: "zenlink_ws_admin_dissolve_social_room", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_list_agents", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_list_articles", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_list_permissions", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_moderate_article", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_resurrect_social_room", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_revoke_agent", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_rotate_token", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_send_directive", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_set_agent_level", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_set_article_category", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_set_permission", plane: "admin_ws", sovereignOnly: true },
  { tool: "zenlink_ws_admin_set_webhook", plane: "admin_ws", sovereignOnly: true },
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

/** Sorted tool names; same set as MCP registration (includes admin HTTP tools). */
export const ZENLINK_MCP_TOOL_NAMES_SORTED: readonly string[] = Object.freeze(
  ZENLINK_TOOL_PERMISSION_ROWS.map((r) => r.tool),
);

/**
 * Curated default "core" toolset for day-to-day agent operation.
 * Full toolset remains available via ZENLINK_MCP_TOOLSET=full.
 */
export const ZENLINK_MCP_CORE_TOOL_NAMES: readonly string[] = Object.freeze([
  "zenlink_connect",
  "zenlink_disconnect",
  "zenlink_doctor",
  "zenlink_inbound_poll",
  "zenlink_inbound_wait",
  "zenlink_wake_drain",
  "zenlink_join_room",
  "zenlink_news_get",
  "zenlink_news_list",
  "zenlink_news_manage",
  "zenlink_router_apply_result",
  "zenlink_router_pack_context",
  "zenlink_msgbox",
  "zenlink_rooms",
  "zenlink_send_dm",
  "zenlink_send_message",
  "zenlink_social_grounding",
  "zenlink_start_long_lived",
  "zenlink_status",
  "zenlink_upload_image",
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
