import { mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";

/** Stable basename under **`os.tmpdir()`** when **`ZENLINK_MCP_DAEMON_ADDR_FILE`** is unset (no agent-id hash). */
export const ZENLINK_MCP_DAEMON_ADDR_BASENAME = "zenlink-mcp-daemon.addr";

/** Unix fixed path when **`ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP=1`** (shared `/tmp` — dev / single-user only). */
export const ZENLINK_MCP_DAEMON_ADDR_SYSTEM_TMP = "/tmp/zenlink-mcp-daemon.addr";

function useSystemTmpForDaemonAddr(): boolean {
  const v = process.env.ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP;
  return v === "1" || String(v ?? "").toLowerCase() === "true";
}

/**
 * Stdio MCP forwards tools to **`zenlink-mcp --daemon`** when **`true`**.
 * **Default: true** when unset (matches **`npm run openclaw:register`**).
 * Opt out: **`ZENLINK_MCP_USE_DAEMON=0`**, **`false`**, **`no`**, or **`off`** (case-insensitive).
 */
export function useDaemonStdioMode(): boolean {
  const raw = process.env.ZENLINK_MCP_USE_DAEMON;
  if (raw === undefined || String(raw).trim() === "") {
    return true;
  }
  const s = String(raw).toLowerCase().trim();
  if (s === "0" || s === "false" || s === "no" || s === "off") {
    return false;
  }
  if (s === "1" || s === "true" || s === "yes" || s === "on") {
    return true;
  }
  return false;
}

/**
 * Addr file (**`host:port`**, one line) used by **`--daemon`** (writes) and stdio (**reads**).
 * Override via **`ZENLINK_MCP_DAEMON_ADDR_FILE`**.
 * Else if **`ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP=1`** (non-Windows): **`/tmp/zenlink-mcp-daemon.addr`** (fixed path; multi-user risk on shared hosts).
 * Else: **`${tmpdir()}/zenlink-mcp-daemon.addr`**.
 *
 * Multiple distinct agents on the **same login** should use **`ZENLINK_MCP_DAEMON_ADDR_FILE`** per agent so two daemons
 * never share one file (second start exits when the TCP port in the addr file is live).
 */
export function defaultDaemonAddrFile(): string {
  const fromEnv = process.env.ZENLINK_MCP_DAEMON_ADDR_FILE?.trim();
  if (fromEnv) {
    const parent = dirname(fromEnv);
    try {
      mkdirSync(parent, { recursive: true });
    } catch {
      /* ignore mkdir failure; daemon write will surface */
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

/**
 * **`ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS`** — max wait per tool **`invoke`** on the stdio → daemon IPC.
 * **`0` / omit** = unlimited (recommended only while debugging timeouts).
 *
 * Defaults to **900000** (15 minutes) — large Router + ZenHeart WS stalls should stay under this in production.
 */
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
