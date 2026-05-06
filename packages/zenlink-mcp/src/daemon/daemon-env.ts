import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

export const ZENLINK_MCP_DAEMON_ADDR_BASENAME = "zenlink-mcp-daemon.addr";
export const ZENLINK_MCP_DAEMON_ADDR_SYSTEM_TMP = "/tmp/zenlink-mcp-daemon.addr";

function useSystemTmpForDaemonAddr(): boolean {
  const v = process.env.ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP;
  return v === "1" || String(v ?? "").toLowerCase() === "true";
}

/** When true, stdio MCP forwards tool calls to a local TCP daemon (see `zenlink-mcp --daemon`). */
export function useDaemonStdioMode(): boolean {
  const raw = process.env.ZENLINK_MCP_USE_DAEMON;
  if (raw === undefined || String(raw).trim() === "") {
    return false;
  }
  const s = String(raw).toLowerCase().trim();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

export function defaultDaemonAddrFile(): string {
  const fromEnv = process.env.ZENLINK_MCP_DAEMON_ADDR_FILE?.trim();
  if (fromEnv) {
    const parent = dirname(fromEnv);
    try {
      mkdirSync(parent, { recursive: true });
    } catch {
      // Ignore; daemon write will surface errors.
    }
    return fromEnv;
  }
  if (useSystemTmpForDaemonAddr() && process.platform !== "win32") {
    return ZENLINK_MCP_DAEMON_ADDR_SYSTEM_TMP;
  }
  return join(tmpdir(), ZENLINK_MCP_DAEMON_ADDR_BASENAME);
}

export function assertAgentEnvLoaded(): void {
  const aid =
    process.env.ZENLINK_AGENT_ID ??
    process.env.ZENHEART_AGENT_ID ??
    process.env.ZENHEART_V2_AGENT_ID;
  const tok =
    process.env.ZENLINK_TOKEN ??
    process.env.ZENHEART_TOKEN ??
    process.env.ZENHEART_V2_TOKEN;
  if (!aid?.trim() || !tok?.trim()) {
    throw new Error(
      "zenlink-mcp daemon: missing ZENLINK_AGENT_ID / ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_*)",
    );
  }
}

export function readDaemonInvokeTimeoutMs(): number {
  const raw = process.env["ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS"];
  if (raw === undefined || raw === "") {
    return 900_000;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(
      `ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS must be non-negative (${raw})`,
    );
  }
  return Math.floor(n);
}
