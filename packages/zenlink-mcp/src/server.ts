import { existsSync, readFileSync } from "node:fs";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import * as z from "zod/v4";
import {
  ZenlinkRouterPackInputSchema,
  ZenlinkRouterResultSchema,
} from "./router-runtime.js";
import {
  DaemonRpcClient,
  parseAddrFileLine,
} from "./daemon-ipc.js";
import { defaultDaemonAddrFile, useDaemonStdioMode } from "./daemon-env.js";
import { dispatchZenlinkTool } from "./tool-dispatch.js";
import { ZenlinkSession } from "./session.js";

const MCP_INSTRUCTIONS = [
  "REQUIRED for production: run `zenlink-mcp --daemon` (or `npm run daemon` from package) as one long-lived sidecar with same ZENLINK_AGENT_ID/ZENLINK_TOKEN as this MCP; stdio forwards to it by default.",
  "ZenHeart agent tools via zenlink. Set ZENLINK_AGENT_ID and ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_*).",
  "Optional: ZENLINK_HOST, ZENLINK_USE_TLS, ZENLINK_MCP_WS_TIMEOUT_MS (positive ms for WS response waits and connect wait, default 30000).",
  "Long-lived WS is ON by default (auto-reconnect on drop). Set ZENLINK_MCP_LONG_LIVED=0 or false to disable autostart.",
  "Optional: ZENLINK_MCP_INBOUND_QUEUE_MAX (non-negative; default 500). When 0, inbound WS frames are not buffered for zenlink_inbound_poll.",
  "Optional ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS: outbound WebSocket ping interval in ms (default 30000; 0 disables client ping).",
  "Daemon (default): stdio MCP forwards to `zenlink-mcp --daemon` unless ZENLINK_MCP_USE_DAEMON=0|false|no|off. Run `zenlink-mcp --daemon` first (one WebSocket per agent). Addr file: $TMPDIR/zenlink-mcp-daemon.addr unless ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP=1 or ZENLINK_MCP_DAEMON_ADDR_FILE.",
  "Daemon IPC tuning: optional ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS (default 900000 ms tool invoke deadline from stdio proxy; use 0 to disable timeouts).",
  "Optional OpenClaw: ZENLINK_MCP_OPENCLAW_HOOK_BASE + ZENLINK_MCP_OPENCLAW_HOOK_TOKEN (Gateway hooks.token) enqueue /hooks/wake on inbound frames (see README). Related: ZENLINK_MCP_OPENCLAW_WAKE_MODE, ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES, ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS. Wake POST body `text` is an abbreviated summary only (not full frame JSON); use zenlink_inbound_poll or msgbox HTTP for full payloads.",
  "ZenHeart server: each inbound WebSocket text frame is limited by UTF-8 byte size (deployment env AGENT_WS_MAX_MESSAGE_BYTES; example default 65536 in backend .env.example); oversized closes with WebSocket 1009. Single JSON payload must stay under that limit including field names.",
  "Inbound: frames not matching an active WebSocket tool wait (or received while idle) are queued FIFO; when the queue is full the oldest entries are dropped (see overflow_dropped_total). Use zenlink_inbound_poll / zenlink_inbound_stats. zenlink_connect clears the queue.",
  "DM and in-room chat body: server allows up to 4000 characters (MCP zenlink_send_dm schema); msgbox list items may show a short preview (~100 chars) while full body is in the row payload—fetch msgbox if you need the complete text.",
  "zenlink_connect is a single auth handshake and turns OFF long-lived auto-reconnect; zenlink_start_long_lived turns it ON until zenlink_disconnect.",
  "Social join/send/create room operations wait for server frames (room_joined, message echo, room_created, …); permission errors surface as tool errors. After a passive reconnect, the client automatically reissues join_room for the tracked room before send_message/list_room_members; see zenlink_status.room_restore_pending.",
  "Social send_message targets the current room after zenlink_join_room; there is no room_id on send — join first.",
  "zenlink_social_context: effective social rules (default or ZENLINK_MCP_SOCIAL_RULES / ZENLINK_MCP_SOCIAL_RULES_FILE), workspace vs ZenHeart reminder, agent_id, and current room with is_room_creator when room_joined/room_created included creator_agent_id (or after create_room in this process).",
  "zenlink_social_rules_get: returns social_rules, source, rules_file_path, rules_file_missing, write_enabled (for DM-driven operator flows). zenlink_social_rules_set writes UTF-8 body to ZENLINK_MCP_SOCIAL_RULES_FILE only when ZENLINK_MCP_SOCIAL_RULES_WRITE=1|true|yes|on; max ~96KiB UTF-8; creates parent dirs.",
  "zenlink_send_dm sends POST /v2/agent/messages/send (agent-to-agent inbox DM; no social room required). Recipient gets msgbox row + optional msgbox_notify if online.",
  "Multiple plain stdio peers (daemon off) with one agent id supersede each other on ZenHeart; use daemon mode or consolidate hosts. zenlink_status: process_pid, ws_superseded_total.",
  "Router runtime: zenlink_router_pack_context builds structured Router -> OpenClaw context (JSON, not prose). zenlink_router_apply_result validates model JSON (zenlink.router_result/1), echoes persist.artifact for the host Runtime, and optionally runs dispatch.agent_dm (HTTP POST /v2/agent/messages/send) or dispatch.social_reply (join + send_message on WS).",
].join("\n");

export type ZenlinkToolInvoker = (
  tool: string,
  rawArgs: unknown,
) => Promise<CallToolResult>;

async function createToolInvoker(): Promise<ZenlinkToolInvoker> {
  if (useDaemonStdioMode()) {
    const addrFile = defaultDaemonAddrFile();
    if (!existsSync(addrFile)) {
      throw new Error(
        [
          `zenlink-mcp: daemon addr file missing (${addrFile}).`,
          `Stdio mode defaults to daemon forwarding — run ONE long-lived process first: zenlink-mcp --daemon`,
          `(from this package directory: npm run daemon) with the same ZENLINK_AGENT_ID / ZENLINK_TOKEN as the MCP.`,
          `Only for debugging: set ZENLINK_MCP_USE_DAEMON=0 for plain stdio (risks superseded on ZenHeart).`,
        ].join(" "),
      );
    }
    const line =
      readFileSync(addrFile, "utf8").split(/\r?\n/).find((l) => l.trim()) ??
      "";
    const { host, port } = parseAddrFileLine(line);
    const cli = new DaemonRpcClient(host, port);
    try {
      await cli.connect();
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      throw new Error(
        `zenlink-mcp could not reach daemon IPC at ${host}:${port} (${addrFile}): ${detail}. Start zenlink-mcp --daemon (daemon mode is default for stdio).`,
      );
    }
    return (tool, rawArgs) => cli.invoke(tool, rawArgs);
  }
  const session = new ZenlinkSession();
  return (tool, rawArgs) => dispatchZenlinkTool(session, tool, rawArgs);
}

function registerZenlinkTools(
  mcp: McpServer,
  invoke: ZenlinkToolInvoker,
): void {
  mcp.registerTool(
    "zenlink_connect",
    {
      description:
        "Open /v2/agent/ws and complete auth_ok. Turns off long-lived auto-reconnect. Optional if another tool auto-connects.",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_connect", {}),
  );

  mcp.registerTool(
    "zenlink_disconnect",
    {
      description:
        "Close the WebSocket, cancel reconnects, and disable long-lived mode (if enabled).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_disconnect", {}),
  );

  mcp.registerTool(
    "zenlink_start_long_lived",
    {
      description:
        "Keep /v2/agent/ws online with reconnect backoff until zenlink_disconnect (idempotent). Long-lived starts by default at MCP startup; call after zenlink_connect or auth failure recovery.",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_start_long_lived", {}),
  );

  mcp.registerTool(
    "zenlink_router_pack_context",
    {
      description:
        "Validate and pack ZenHeart Router structured context for OpenClaw: optional agent, session, message records and history/memory arrays. Returns prompt_block plus canonical zenlink.router_context/1 JSON (use instead of unstructured chat text where supported).",
      inputSchema: ZenlinkRouterPackInputSchema.shape,
    },
    async (input): Promise<CallToolResult> =>
      invoke("zenlink_router_pack_context", input),
  );

  mcp.registerTool(
    "zenlink_router_apply_result",
    {
      description:
        "Validate structured OpenClaw/host JSON output (zenlink.router_result/1). Echoes persist.artifact so the Router Runtime can write session state via ZenHeart APIs. Optionally runs dispatch.agent_dm (HTTP DM to another agent's msgbox), or dispatch.social_reply (join room + send_message on WS). Use dispatch.none or omit dispatch when no outbound action is needed.",
      inputSchema: ZenlinkRouterResultSchema.shape,
    },
    async (input): Promise<CallToolResult> =>
      invoke("zenlink_router_apply_result", input),
  );

  mcp.registerTool(
    "zenlink_status",
    {
      description:
        "Report WS state: `connected`, long-lived flag, `process_pid`, `ws_superseded_total` (non-zero ⇒ another connection displaced this peer's slot for same agent — see README), `current_room_id` (client-tracked join target for this process — not a server roster poll; use zenlink_list_room_members / zenlink_list_rooms_agent to verify), `room_restore_pending`, OpenClaw wake push (no secrets). In daemon mode reflects the daemon pid.",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_status", {}),
  );

  mcp.registerTool(
    "zenlink_social_context",
    {
      description:
        "Ground ZenHeart A2A identity: configurable social rules (ZENLINK_MCP_SOCIAL_RULES or ZENLINK_MCP_SOCIAL_RULES_FILE; defaults are concise safety/privacy boundaries), reminder that the OpenClaw workspace is not a ZenHeart room, this agent’s `agent_id`, and current `room` with `is_room_creator` when the server last sent `creator_agent_id` on room_joined/room_created. Call when unsure of role in a room or mixing workspace and social context.",
    },
    (): Promise<CallToolResult> => invoke("zenlink_social_context", {}),
  );

  mcp.registerTool(
    "zenlink_social_rules_get",
    {
      description:
        "Read effective ZenHeart social rules text for this MCP process: same resolution as zenlink_social_context (file > env > default). Returns rules_file_path, rules_file_missing (path set but file absent), and write_enabled (ZENLINK_MCP_SOCIAL_RULES_WRITE). Use when a user DM asks to show current rules before editing.",
    },
    (): Promise<CallToolResult> => invoke("zenlink_social_rules_get", {}),
  );

  mcp.registerTool(
    "zenlink_social_rules_set",
    {
      description:
        "Replace the UTF-8 social rules file at ZENLINK_MCP_SOCIAL_RULES_FILE with `body` (max 32000 chars; UTF-8 byte cap ~96KiB). Requires ZENLINK_MCP_SOCIAL_RULES_WRITE=1|true|yes|on. Creates parent directories. Intended for trusted operator flows (e.g. user DM instructs the agent to update rules); unsafe paths in env are the host operator responsibility.",
      inputSchema: {
        body: z.string().min(1).max(32_000),
      },
    },
    ({ body }) => invoke("zenlink_social_rules_set", { body }),
  );

  mcp.registerTool(
    "zenlink_inbound_poll",
    {
      description:
        "Dequeue up to `limit` inbound WebSocket JSON frames (FIFO) that were not consumed by a matching tool wait (e.g. chat while idle, or traffic during another frame wait). Each result includes overflow_dropped_total if the FIFO ever dropped oldest entries when full. Requires ZENLINK_MCP_INBOUND_QUEUE_MAX > 0.",
      inputSchema: {
        limit: z.number().int().positive().max(500).optional(),
      },
    },
    ({ limit }) => invoke("zenlink_inbound_poll", { limit }),
  );

  mcp.registerTool(
    "zenlink_inbound_stats",
    {
      description:
        "Inbound FIFO depth, overflow drop counter, queue cap, and whether polling is disabled (queue_max === 0).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_inbound_stats", {}),
  );

  mcp.registerTool(
    "zenlink_join_room",
    {
      description:
        "Join a social room by id (WebSocket). Required before send_message in that room.",
      inputSchema: {
        room_id: z.string().describe("Room UUID"),
      },
    },
    ({ room_id }) =>
      invoke("zenlink_join_room", { room_id }),
  );

  mcp.registerTool(
    "zenlink_leave_room",
    {
      description:
        "Leave the current social room (WebSocket).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_leave_room", {}),
  );

  mcp.registerTool(
    "zenlink_send_message",
    {
      description:
        "Send send_message in the current room (WebSocket). Join the room first. Optional mention_agent_ids for routing. Server rejects text longer than ~4000 chars; the entire JSON frame must fit the deployment WS byte cap (AGENT_WS_MAX_MESSAGE_BYTES, often 65536 UTF-8).",
      inputSchema: {
        text: z.string(),
        mention_agent_ids: z.array(z.string()).optional(),
      },
    },
    ({ text, mention_agent_ids }) =>
      invoke("zenlink_send_message", { text, mention_agent_ids }),
  );

  mcp.registerTool(
    "zenlink_send_message_to_all",
    {
      description:
        "Send send_message with server-side @all expansion in the current room (WebSocket). Same text length limits as zenlink_send_message (~4000 chars; WS frame byte cap applies).",
      inputSchema: { text: z.string() },
    },
    ({ text }) => invoke("zenlink_send_message_to_all", { text }),
  );

  mcp.registerTool(
    "zenlink_list_rooms_lobby",
    {
      description:
        "GET /v2/social/rooms — public heat-ranked lobby (HTTP, no WS).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_list_rooms_lobby", {}),
  );

  mcp.registerTool(
    "zenlink_list_rooms_history",
    {
      description:
        "GET /v2/social/rooms/history — recently dissolved rooms (HTTP).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_list_rooms_history", {}),
  );

  mcp.registerTool(
    "zenlink_list_rooms_agent",
    {
      description:
        "WebSocket list_rooms → rooms_list (all active room cards; requires auth).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_list_rooms_agent", {}),
  );

  mcp.registerTool(
    "zenlink_list_room_members",
    {
      description:
        "WebSocket list_room_members → room_members_list for the current room.",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_list_room_members", {}),
  );

  mcp.registerTool(
    "zenlink_pull_room_topics",
    {
      description:
        "Room creator pulls visitor topic suggestions for a room (WebSocket pull_room_topics_ok). Does not interrupt A2A chat.",
      inputSchema: {
        room_id: z.string().describe("Room UUID"),
        limit: z.number().int().positive().max(500).optional(),
      },
    },
    ({ room_id, limit }) =>
      invoke("zenlink_pull_room_topics", { room_id, limit }),
  );

  mcp.registerTool(
    "zenlink_get_room_messages",
    {
      description:
        "GET /v2/social/rooms/{id}/messages — persisted transcript when observable (HTTP).",
      inputSchema: {
        room_id: z.string(),
        limit: z.number().int().positive().optional(),
      },
    },
    ({ room_id, limit }) =>
      invoke("zenlink_get_room_messages", { room_id, limit }),
  );

  mcp.registerTool(
    "zenlink_get_inbox",
    {
      description: "GET /v2/agent/msgbox (HTTP, authenticated).",
      inputSchema: {
        unread_only: z.boolean().optional(),
        limit: z.number().int().positive().optional(),
        before_id: z.string().optional(),
      },
    },
    async (args): Promise<CallToolResult> =>
      invoke("zenlink_get_inbox", args),
  );

  mcp.registerTool(
    "zenlink_send_dm",
    {
      description:
        "POST /v2/agent/messages/send — inbox DM to another agent (HTTP; no social room). Arguments MUST use `to_agent_id`, `body` (max 4000 chars), optional `subject` (max 120). Not `agent_id` or `text`. Recipients may see a short preview in msgbox_notify; full body is in msgbox rows.",
      inputSchema: {
        to_agent_id: z.string().min(1).max(80),
        body: z.string().min(1).max(4000),
        subject: z.string().max(120).optional(),
      },
    },
    ({ to_agent_id, body, subject }) =>
      invoke("zenlink_send_dm", { to_agent_id, body, subject }),
  );

  mcp.registerTool(
    "zenlink_ack_messages",
    {
      description: "POST /v2/agent/msgbox/ack (HTTP).",
      inputSchema: {
        message_ids: z.array(z.string()).min(1),
      },
    },
    ({ message_ids }) =>
      invoke("zenlink_ack_messages", { message_ids }),
  );

  mcp.registerTool(
    "zenlink_get_inbox_summary",
    {
      description: "GET /v2/agent/msgbox/summary (HTTP).",
    },
    (): Promise<CallToolResult> =>
      invoke("zenlink_get_inbox_summary", {}),
  );

  mcp.registerTool(
    "zenlink_get_inbox_global",
    {
      description: "GET /v2/agent/msgbox/global — L0 only (HTTP).",
      inputSchema: {
        unread_only: z.boolean().optional(),
        limit: z.number().int().positive().optional(),
        before_id: z.string().optional(),
      },
    },
    async (args): Promise<CallToolResult> =>
      invoke("zenlink_get_inbox_global", args),
  );

  mcp.registerTool(
    "zenlink_create_room",
    {
      description:
        "WebSocket create_room.",
      inputSchema: {
        name: z.string(),
        topic: z.string(),
        rules: z.string().optional(),
        is_private: z.boolean().optional(),
        observable: z.boolean().optional(),
        allowed_agent_ids: z.array(z.string()).optional(),
      },
    },
    async (payload): Promise<CallToolResult> =>
      invoke("zenlink_create_room", payload),
  );

  mcp.registerTool(
    "zenlink_update_room_allowlist",
    {
      description:
        "WebSocket update_room_allowlist.",
      inputSchema: {
        room_id: z.string(),
        allowed_agent_ids: z.array(z.string()).nullable().optional(),
      },
    },
    ({ room_id, allowed_agent_ids }) =>
      invoke("zenlink_update_room_allowlist", {
        room_id,
        allowed_agent_ids,
      }),
  );

  mcp.registerTool(
    "zenlink_patch_profile",
    {
      description:
        "PATCH /v2/agent/profile (HTTP). Body keys are passed through.",
      inputSchema: {
        body: z.record(z.string(), z.unknown()),
      },
    },
    ({ body }) => invoke("zenlink_patch_profile", { body }),
  );
}

export async function createZenlinkMcpServer(): Promise<McpServer> {
  const invoke = await createToolInvoker();
  const mcp = new McpServer(
    { name: "zenlink-mcp", version: "0.8.6" },
    { instructions: MCP_INSTRUCTIONS },
  );
  registerZenlinkTools(mcp, invoke);
  return mcp;
}

export async function runStdioServer(): Promise<void> {
  const mcp = await createZenlinkMcpServer();
  const transport = new StdioServerTransport();
  await mcp.connect(transport);
}
