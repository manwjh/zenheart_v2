#!/usr/bin/env node
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runSmokeStdioTools } from "./cli/smoke-stdio-tools.js";
import { runHealthCheck } from "./cli/health.js";
import { ZENLINK_SDK_VERSION } from "./zenlink/sdk-version.js";

const argv = process.argv.slice(2);
const arg0 = argv[0];

function printVersionLines(): void {
  const here = dirname(fileURLToPath(import.meta.url));
  const pkgRoot = join(here, "..");
  const self = JSON.parse(
    readFileSync(join(pkgRoot, "package.json"), "utf8"),
  ) as { version?: string };
  const lines: string[] = [];
  lines.push(`zenlink-mcp ${String(self.version ?? "unknown")}`);
  lines.push(`embedded zenlink SDK ${ZENLINK_SDK_VERSION}`);
  const req = createRequire(join(pkgRoot, "package.json"));
  try {
    const mPath = req.resolve("@modelcontextprotocol/sdk/package.json");
    const m = JSON.parse(readFileSync(mPath, "utf8")) as { version?: string };
    lines.push(`@modelcontextprotocol/sdk ${String(m.version ?? "?")}`);
  } catch {
    /* optional */
  }
  console.log(lines.join("\n"));
}

if (arg0 === "--help" || arg0 === "-h") {
  console.log(`zenlink-mcp — ZenHeart MCP server (stdio JSON-RPC).

Usage:
  zenlink-mcp                 Run MCP over stdin/stdout
  zenlink-mcp --daemon        Long-lived tool worker (TCP IPC; writes ZENLINK_MCP_DAEMON_ADDR_FILE)
  zenlink-mcp health          Check daemon addr + zenlink_status over IPC
  zenlink-mcp smoke           Run tools/list smoke (no ZenHeart; needs built dist/ + npm ci)
  zenlink-mcp --help          Show this text
  zenlink-mcp --version       Print zenlink-mcp, embedded SDK, and @modelcontextprotocol/sdk versions

Environment (required): ZENLINK_AGENT_ID and ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_* aliases).
Optional transport: ZENLINK_HOST, ZENLINK_USE_TLS, ZENLINK_MCP_WS_TIMEOUT_MS,
  ZENLINK_MCP_COMPACT_TOOL_JSON (=1|true|yes|on for single-line JSON in tool results; smaller MCP/daemon payloads; default pretty-printed),
  ZENLINK_MCP_LONG_LIVED (=0|false to disable default long-lived reconnect), ZENLINK_MCP_INBOUND_QUEUE_MAX (default 500; 0 disables inbound FIFO),
  ZENLINK_MCP_INBOUND_DROP_TYPES (comma list; default ping,pong),
  ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS (ms; default 30000 outbound WS ping; 0 disables client ping),
  ZENLINK_MCP_USE_DAEMON (=1 forwards stdio tool calls to --daemon), ZENLINK_MCP_DAEMON_ADDR_FILE.
`);
  process.exit(0);
}

if (arg0 === "--version" || arg0 === "-v") {
  printVersionLines();
  process.exit(0);
}

if (arg0 === "smoke") {
  const code = await runSmokeStdioTools();
  process.exit(code);
}

if (arg0 === "--daemon") {
  const { runZenlinkDaemon } = await import("./daemon/daemon.js");
  try {
    await runZenlinkDaemon();
    process.exit(0);
  } catch (e) {
    console.error(e instanceof Error ? e.message : e);
    process.exit(1);
  }
}

if (arg0 === "health") {
  const code = await runHealthCheck(argv.slice(1));
  process.exit(code);
}

if (arg0 === "--reconnect" || arg0?.startsWith("--reconnect=")) {
  console.error("zenlink-mcp: unsupported argument. Use --help.");
  process.exit(2);
}

const { runStdioServer } = await import("./transport/server.js");
try {
  await runStdioServer();
} catch (e) {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
}
