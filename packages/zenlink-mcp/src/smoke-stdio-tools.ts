/**
 * Stdio tools/list smoke (no ZenHeart traffic) — runnable via **`dist/cli.js smoke`** or **`npm run smoke:tools`**.
 */
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

/** Canonical tool names — keep sorted; update when `./server.ts` tool registrations change. */
export const EXPECTED_TOOL_NAMES = Object.freeze(
  [
    "zenlink_ack_messages",
    "zenlink_connect",
    "zenlink_create_room",
    "zenlink_disconnect",
    "zenlink_get_inbox",
    "zenlink_get_inbox_global",
    "zenlink_get_inbox_summary",
    "zenlink_get_room_messages",
    "zenlink_inbound_poll",
    "zenlink_inbound_stats",
    "zenlink_join_room",
    "zenlink_leave_room",
    "zenlink_list_room_members",
    "zenlink_list_rooms_agent",
    "zenlink_list_rooms_history",
    "zenlink_list_rooms_lobby",
    "zenlink_patch_profile",
    "zenlink_pull_room_topics",
    "zenlink_router_apply_result",
    "zenlink_router_pack_context",
    "zenlink_send_dm",
    "zenlink_send_message",
    "zenlink_send_message_to_all",
    "zenlink_start_long_lived",
    "zenlink_status",
    "zenlink_update_room_allowlist",
  ].sort(),
);

function listsEqual(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((name, i) => name === b[i]);
}

export async function runSmokeStdioTools(): Promise<number> {
  const __dirname = dirname(fileURLToPath(import.meta.url));
  const cliJs = join(__dirname, "cli.js");

  const transport = new StdioClientTransport({
    command: process.execPath,
    args: [cliJs],
    env: {
      ...process.env,
      /** Self-contained smoke: no zenlink-mcp --daemon required (runtime defaults to daemon-on). */
      ZENLINK_MCP_USE_DAEMON: "0",
      ZENLINK_MCP_LONG_LIVED: "0",
      ZENLINK_AGENT_ID:
        process.env.ZENLINK_AGENT_ID ??
        process.env.ZENHEART_AGENT_ID ??
        process.env.ZENHEART_V2_AGENT_ID ??
        "smoke_test_agent",
      ZENLINK_TOKEN:
        process.env.ZENLINK_TOKEN ??
        process.env.ZENHEART_TOKEN ??
        process.env.ZENHEART_V2_TOKEN ??
        "smoke_test_token",
    },
    stderr: "inherit",
  });

  const client = new Client({
    name: "zenlink-mcp-smoke",
    version: "0.0.1",
  });

  await client.connect(transport);

  const { tools } = await client.listTools();
  const names = tools.map((t) => t.name).sort();

  if (!listsEqual(names, [...EXPECTED_TOOL_NAMES])) {
    console.error(
      "FAIL: tools/list must exactly match the canonical tool set (see EXPECTED_TOOL_NAMES in smoke-stdio-tools.ts).",
    );
    console.error("expected count:", EXPECTED_TOOL_NAMES.length, "got:", names.length);
    console.error("expected:", [...EXPECTED_TOOL_NAMES].join(", "));
    console.error("actual:  ", names.join(", "));
    await transport.close();
    return 1;
  }

  console.log("PASS: tools/list count =", names.length);
  console.log(names.join("\n"));

  await transport.close();
  return 0;
}
