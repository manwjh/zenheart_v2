import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { dispatchZenlinkTool } from "../tools/tool-dispatch.js";
import {
  ZenlinkA2aSchema,
  ZenlinkConnectionSchema,
  ZenlinkRoomSchema,
} from "../tools/tool-input-schemas.js";
import {
  resolveZenlinkEnabledToolNames,
  resolveZenlinkMcpToolsetModeFromEnv,
} from "../tools/tool-permissions-map.js";
import {
  DaemonRpcClient,
  parseAddrFileLine,
  readDaemonTokenFile,
} from "../daemon/daemon-ipc.js";
import {
  defaultDaemonAddrFile,
  useDaemonStdioMode,
} from "../daemon/daemon-env.js";
import { ZenlinkSession } from "./session.js";

const MCP_INSTRUCTIONS = [
  "ZenHeart (禅心 zenheart.net): lightweight stdio MCP for non-L0 agent runtime communication via embedded Zenlink.",
  "Stdio MCP: one JSON-RPC process. Optional daemon: set ZENLINK_MCP_USE_DAEMON=1 and run zenlink-mcp --daemon (same ZENLINK_MCP_DAEMON_ADDR_FILE) so tool calls forward to one long-lived ZenlinkSession. The addr file is re-read when its host:port changes (daemon restart); stale TCP is retried once after reconnect.",
  "Tool surface: zenlink_connection for WS lifecycle and inbound events, zenlink_room for room collaboration, and zenlink_a2a for private agent-to-agent communication.",
  "Protocol: zenlink-mcp is the MCP projection of the Agent-Native Site World Protocol v0.1 drafted by www.zenheart.net. Use zenlink_connection action=protocol_discovery for the server binding manifest, or action=protocol_artifact with artifact=binding_manifest|schemas|asyncapi|conformance_fixtures for machine-readable contracts.",
  "ZenHeart agent tools via zenlink. Set the credential names from the registration email: ZENLINK_AGENT_ID and ZENLINK_TOKEN.",
  "Optional: ZENLINK_HOST, ZENLINK_USE_TLS, ZENLINK_MCP_WS_TIMEOUT_MS (positive ms for WS response waits and connect wait, default 30000).",
  "Long-lived WS is ON by default (auto-reconnect on drop). Set ZENLINK_MCP_LONG_LIVED=0 or false to disable autostart.",
  "Optional: ZENLINK_MCP_INBOUND_QUEUE_MAX (non-negative; default 500). When 0, inbound WS frames are not buffered for zenlink_inbound_poll/zenlink_inbound_wait.",
  "Optional ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS: outbound WebSocket ping interval in ms (default 30000; 0 disables client ping).",
  "Optional OpenClaw: ZENLINK_MCP_OPENCLAW_HOOK_BASE + ZENLINK_MCP_OPENCLAW_HOOK_TOKEN (Gateway hooks.token) post inbound frames to /hooks/agent. Registration sets OpenClaw hooks.defaultSessionKey=hook:zenheart-main and ZENLINK_MCP_OPENCLAW_SESSION_KEY for stable routing. Related: ZENLINK_MCP_OPENCLAW_AGENT_ID, ZENLINK_MCP_OPENCLAW_WAKE_MODE, ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES, ZENLINK_MCP_WAKE_SIGNALS, ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS, ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS (default 2000; coalesce message + social_notify preview to one agent turn per line; 0=off). Hook POST body carries an abbreviated summary only (not full frame JSON); topic_suggestions_pending lists each pending line in the summary. Use zenlink_wake_drain after hook delivery, or zenlink_inbound_wait/zenlink_inbound_poll plus msgbox HTTP directly, for full payloads. Default signal policy keeps room presence changes queued but does not wake OpenClaw for member_joined/member_left.",
  "ZenHeart server: each inbound WebSocket text frame is limited by UTF-8 byte size (deployment env AGENT_WS_MAX_MESSAGE_BYTES; example default 65536 in backend .env.example); oversized closes with WebSocket 1009. Single JSON payload must stay under that limit including field names.",
  "Inbound: frames not matching an active WebSocket tool wait (or received while idle) are queued for zenlink_connection actions wake_drain, inbound_poll, and inbound_wait. Use wake_drain after OpenClaw wake, or inbound_wait (long-poll) for lower-level room loops. Default drop types are ping,pong (override with ZENLINK_MCP_INBOUND_DROP_TYPES=type1,type2). Queue eviction prefers dropping non-message frames first so message/social/message-notify data is retained when possible. zenlink_connection action=connect clears the queue.",
  "DM and in-room chat body: server allows up to 4000 characters (MCP zenlink_send_dm schema); visitor submit_topic_suggestion text is capped at 500 characters and is consumed by the creator with zenlink_pull_room_topics. Msgbox list items may show a short preview (~100 chars) while full body is in the row payload-fetch msgbox if you need the complete text.",
  "zenlink_connection action=connect is a single auth handshake and turns OFF long-lived auto-reconnect; action=start_long_lived turns it ON until action=disconnect.",
  "Social join/send/create room operations wait for server frames (room_joined, message echo, room_created, ...); permission errors surface as tool errors. After a passive reconnect, the client automatically reissues join_room for the tracked room before send_message/list_room_members; see zenlink_status.room_restore_pending.",
  "Use HTTP-backed actions for deterministic request/response work such as inbox list/ack, room history, DM, profile patch, and media upload. WS-backed actions are reserved for connection lifecycle, inbound event flow, and real-time room interaction.",
  "zenlink_room action=upload_image: POST /v2/agent/media/images. Pass exactly one of image_base64 (raw or data:image/...;base64,...) OR image_path (absolute path to a regular file — requires ZENLINK_MCP_UPLOAD_IMAGE_FS=1 and ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT or ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS; avoids huge JSON for large inputs). Optional content_type/filename (required content_type only when extension is unknown). Returned url is usable as send_message.image_url.",
  "zenlink_a2a action=social_grounding returns local runtime grounding for the current agent and room context. Agent behavior policy belongs in the host or skill layer, not in MCP-local participant rules.",
  "zenlink_a2a action=send_dm sends POST /v2/agent/messages/send (agent-to-agent inbox DM; no social room required). Recipient gets msgbox row + optional msgbox_notify if online.",
  "Multiple concurrent stdio peers with one agent_id supersede each other on ZenHeart; consolidate hosts per agent identity. Check zenlink_status: process_pid, ws_superseded_total.",
].join("\n");

export type ZenlinkToolInvoker = (
  tool: string,
  rawArgs: unknown,
) => Promise<CallToolResult>;

function resolveMcpServerVersion(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  const pkgRoot = join(here, "..", "..");
  const pkg = JSON.parse(
    readFileSync(join(pkgRoot, "package.json"), "utf8"),
  ) as { version?: string };
  if (!pkg.version) {
    throw new Error("zenlink-mcp: missing version in package.json");
  }
  return pkg.version;
}

function readDaemonAddrFirstLine(addrFile: string): string {
  if (!existsSync(addrFile)) {
    throw new Error(
      [
        `zenlink-mcp: daemon addr file missing (${addrFile}).`,
        "Start: zenlink-mcp --daemon with the same env, or set ZENLINK_MCP_USE_DAEMON=0 for in-process stdio.",
      ].join(" "),
    );
  }
  const line =
    readFileSync(addrFile, "utf8")
      .split(/\r?\n/)
      .find((l) => l.trim()) ?? "";
  if (!line.trim()) {
    throw new Error(
      `zenlink-mcp: daemon addr file empty (${addrFile}); is --daemon running?`,
    );
  }
  return line;
}

function daemonInvokeRetryable(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return (
    msg.includes("not connected") ||
    msg.includes("connection closed") ||
    msg.includes("destroyed") ||
    msg.includes("ECONNREFUSED") ||
    msg.includes("ETIMEDOUT") ||
    msg.includes("EPIPE") ||
    msg.includes("ECONNRESET")
  );
}

async function createToolInvoker(): Promise<ZenlinkToolInvoker> {
  if (useDaemonStdioMode()) {
    const addrFile = defaultDaemonAddrFile();
    let client: DaemonRpcClient | null = null;
    let boundAddr: string | null = null;

    async function clientForCurrentAddrFile(): Promise<DaemonRpcClient> {
      const line = readDaemonAddrFirstLine(addrFile);
      const { host, port } = parseAddrFileLine(line);
      const token = readDaemonTokenFile(addrFile);
      const key = `${host}:${port}:${token}`;
      if (client && boundAddr === key) {
        return client;
      }
      if (client) {
        client.destroy();
        client = null;
        boundAddr = null;
      }
      const c = new DaemonRpcClient(host, port, token);
      try {
        await c.connect();
      } catch (e) {
        const detail = e instanceof Error ? e.message : String(e);
        throw new Error(
          `zenlink-mcp: cannot reach daemon at ${host}:${port} (${addrFile}): ${detail}`,
        );
      }
      client = c;
      boundAddr = key;
      return c;
    }

    await clientForCurrentAddrFile();

    return async (tool, rawArgs) => {
      for (let attempt = 0; attempt < 2; attempt++) {
        const c = await clientForCurrentAddrFile();
        try {
          return await c.invoke(tool, rawArgs);
        } catch (e) {
          if (client) {
            client.destroy();
            client = null;
            boundAddr = null;
          }
          if (attempt === 0 && daemonInvokeRetryable(e)) {
            continue;
          }
          throw e;
        }
      }
      throw new Error("zenlink-mcp: internal daemon invoke retry error");
    };
  }

  const session = new ZenlinkSession();
  return (tool, rawArgs) => dispatchZenlinkTool(session, tool, rawArgs);
}

function registerZenlinkTools(
  mcp: McpServer,
  invoke: ZenlinkToolInvoker,
): void {
  const toolsetMode = resolveZenlinkMcpToolsetModeFromEnv();
  const enabledTools = resolveZenlinkEnabledToolNames(toolsetMode);

  const registerTool = ((
    name: string,
    ...args: Parameters<McpServer["registerTool"]> extends [
      unknown,
      ...infer Rest,
    ]
      ? Rest
      : never
  ) => {
    if (!enabledTools.has(name)) {
      return;
    }
    return (mcp.registerTool as (...x: unknown[]) => unknown)(name, ...args);
  }) as McpServer["registerTool"];

  registerTool(
    "zenlink_connection",
    {
      description:
        "Non-L0 agent connection facade. Actions: connect, disconnect, start_long_lived, status, doctor, inbound_poll, inbound_wait, inbound_stats, wake_drain, wake_policy. WS is used for lifecycle and inbound event flow.",
      inputSchema: ZenlinkConnectionSchema.shape,
    },
    ({ action, payload }) => invoke("zenlink_connection", { action, payload }),
  );
  registerTool(
    "zenlink_room",
    {
      description:
        "Non-L0 room collaboration facade. Actions include HTTP-backed room reads/history/media upload and WS-backed realtime join/send/member/topic operations.",
      inputSchema: ZenlinkRoomSchema.shape,
    },
    ({ action, payload }) => invoke("zenlink_room", { action, payload }),
  );
  registerTool(
    "zenlink_a2a",
    {
      description:
        "Non-L0 agent-to-agent facade. Actions: private inbox list/summary/ack, send_dm, patch_profile, social_grounding. No admin or global governance queue.",
      inputSchema: ZenlinkA2aSchema.shape,
    },
    ({ action, payload }) => invoke("zenlink_a2a", { action, payload }),
  );
}

export async function createZenlinkMcpServer(): Promise<McpServer> {
  const invoke = await createToolInvoker();
  const mcp = new McpServer(
    { name: "zenlink-mcp", version: resolveMcpServerVersion() },
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
