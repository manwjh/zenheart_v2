import { homedir } from "node:os";
import { join } from "node:path";

export function useDaemonStdioMode(): boolean {
  const value = process.env.ZENLINK_MCP_USE_DAEMON?.trim().toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

export function defaultDaemonAddrFile(): string {
  return (
    process.env.ZENLINK_MCP_DAEMON_ADDR_FILE?.trim() ||
    join(homedir(), ".openclaw", "tmp", "zenlink-mcp-daemon.addr")
  );
}

export function defaultDaemonTokenFile(addrFile = defaultDaemonAddrFile()): string {
  return `${addrFile}.token`;
}

export function daemonInvokeTimeoutMs(): number {
  const raw = process.env.ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS?.trim();
  if (!raw) return 900_000;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS must be a non-negative number");
  }
  return Math.floor(value);
}
