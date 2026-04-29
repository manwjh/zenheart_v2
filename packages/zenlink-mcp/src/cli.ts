import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { runSmokeStdioTools } from "./smoke-stdio-tools.js";

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
  const req = createRequire(join(pkgRoot, "package.json"));
  try {
    const zPath = req.resolve("zenlink/package.json");
    const z = JSON.parse(readFileSync(zPath, "utf8")) as { version?: string };
    lines.push(`peer zenlink ${String(z.version ?? "unknown")}`);
  } catch {
    try {
      const alt = join(pkgRoot, "..", "zenlink", "package.json");
      const z = JSON.parse(readFileSync(alt, "utf8")) as { version?: string };
      lines.push(`peer zenlink ${String(z.version ?? "unknown")} (workspace path)`);
    } catch {
      lines.push("peer zenlink (not resolved — run npm ci in zenlink-mcp)");
    }
  }
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
  zenlink-mcp --daemon        Long-lived: one ZenHeart WebSocket; writes addr file + TCP localhost
  zenlink-mcp smoke           Run tools/list smoke (no ZenHeart; needs built dist/ + npm ci)
  zenlink-mcp --help          Show this text
  zenlink-mcp --version       Print zenlink-mcp, peer zenlink, and @modelcontextprotocol/sdk versions

Environment (required): ZENLINK_AGENT_ID and ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_* aliases).
Optional transport: ZENLINK_HOST, ZENLINK_USE_TLS, ZENLINK_MCP_WS_TIMEOUT_MS,
  ZENLINK_MCP_LONG_LIVED (=0|false to disable default long-lived reconnect), ZENLINK_MCP_INBOUND_QUEUE_MAX (default 500; 0 disables inbound FIFO),
  ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS (ms; default 30000 outbound WS ping; 0 disables client ping).
Optional addr: ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP=1 → use /tmp/zenlink-mcp-daemon.addr (Unix; single-user dev).
Daemon forwarding (DEFAULT ON): stdio expects a running zenlink-mcp --daemon sidecar unless ZENLINK_MCP_USE_DAEMON=0|false|no|off. From package root: npm run daemon (same as --daemon). ZENLINK_MCP_DAEMON_ADDR_FILE must match. OpenClaw minimal plain stdio: ZENLINK_MCP_REGISTER_PLAIN_STDIO=1 when running openclaw:register.
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
  const { runZenlinkDaemon } = await import("./daemon.js");
  await runZenlinkDaemon();
} else {
  const { runStdioServer } = await import("./server.js");
  try {
    await runStdioServer();
  } catch (e) {
    console.error(e instanceof Error ? e.message : e);
    process.exit(1);
  }
}
