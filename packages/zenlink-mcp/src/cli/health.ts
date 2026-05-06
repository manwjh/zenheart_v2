import { existsSync, readFileSync } from "node:fs";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { defaultDaemonAddrFile } from "../daemon/daemon-env.js";
import {
  DaemonRpcClient,
  parseAddrFileLine,
  tcpProbeAccept,
} from "../daemon/daemon-ipc.js";

function resolveAddrFilePath(argv: string[]): string {
  const withEq = argv.find((a) => a.startsWith("--addr-file="));
  if (withEq) {
    const p = withEq.slice("--addr-file=".length).trim();
    if (p) {
      return p;
    }
  }
  const idx = argv.indexOf("--addr-file");
  if (idx >= 0) {
    const next = argv[idx + 1];
    if (next && !next.startsWith("--")) {
      return next;
    }
  }
  return defaultDaemonAddrFile();
}

function parseStatusPayload(result: CallToolResult): unknown {
  const c = result.content?.[0];
  if (
    c &&
    typeof c === "object" &&
    "type" in c &&
    (c as { type?: string }).type === "text" &&
    "text" in c &&
    typeof (c as { text?: unknown }).text === "string"
  ) {
    try {
      return JSON.parse((c as { text: string }).text);
    } catch {
      return (c as { text: string }).text;
    }
  }
  return result;
}

function logErr(quiet: boolean, msg: string): void {
  if (quiet) {
    console.error(msg.split("\n")[0]);
    return;
  }
  console.error(msg);
}

/** Exit 0 = healthy, 1 = failure */
export async function runHealthCheck(argv: string[]): Promise<number> {
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(`zenlink-mcp health - verify daemon addr file, TCP, and zenlink_status over IPC.

Talks to an existing **zenlink-mcp --daemon** process. Agent credentials are not required in this shell.

Options:
  --addr-file=PATH   One line host:port. Default: ZENLINK_MCP_DAEMON_ADDR_FILE or TMPDIR.
  --json             Print zenlink_status JSON only (stdout).
  --quiet            Minimal stderr on failure.

Env:
  ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS  (health defaults to 8000ms if unset)
`);
    return 0;
  }

  const quiet = argv.includes("--quiet");
  const jsonOnly = argv.includes("--json");
  const addrPath = resolveAddrFilePath(argv);

  const hadInvokeTimeout = Object.prototype.hasOwnProperty.call(
    process.env,
    "ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS",
  );
  if (!hadInvokeTimeout) {
    process.env.ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS = "8000";
  }

  try {
    if (!existsSync(addrPath)) {
      logErr(
        quiet,
        `zenlink-mcp health: addr file missing: ${addrPath}\n` +
          "  Start: node dist/cli.js --daemon (same ZENLINK_MCP_DAEMON_ADDR_FILE).",
      );
      return 1;
    }

    let line: string;
    try {
      line =
        readFileSync(addrPath, "utf8")
          .split(/\r?\n/)
          .find((l) => l.trim()) ?? "";
    } catch (e) {
      logErr(
        quiet,
        `zenlink-mcp health: cannot read ${addrPath}: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      return 1;
    }

    let host: string;
    let port: number;
    try {
      ({ host, port } = parseAddrFileLine(line));
    } catch (e) {
      logErr(
        quiet,
        `zenlink-mcp health: invalid addr in ${addrPath}: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      return 1;
    }

    const tcpOk = await tcpProbeAccept(host, port, { timeoutMs: 3000 });
    if (!tcpOk) {
      logErr(
        quiet,
        `zenlink-mcp health: nothing listening at ${host}:${port}`,
      );
      return 1;
    }

    const client = new DaemonRpcClient(host, port);
    try {
      await client.connect();
    } catch (e) {
      logErr(
        quiet,
        `zenlink-mcp health: IPC connect failed: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      return 1;
    }

    let result: CallToolResult;
    try {
      result = await client.invoke("zenlink_status", {});
    } catch (e) {
      logErr(
        quiet,
        `zenlink-mcp health: zenlink_status failed: ${
          e instanceof Error ? e.message : String(e)
        }`,
      );
      return 1;
    }

    if (result.isError) {
      const msg =
        result.content?.[0] &&
        typeof result.content[0] === "object" &&
        "text" in result.content[0]
          ? String((result.content[0] as { text?: unknown }).text)
          : "zenlink_status isError";
      logErr(quiet, `zenlink-mcp health: ${msg}`);
      return 1;
    }

    const payload = parseStatusPayload(result);
    if (jsonOnly) {
      console.log(JSON.stringify(payload, null, 2));
    } else if (!quiet) {
      console.log(`zenlink-mcp health: ok (${addrPath} -> ${host}:${port})`);
      console.log(JSON.stringify(payload, null, 2));
    }
    return 0;
  } finally {
    if (!hadInvokeTimeout) {
      delete process.env.ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS;
    }
  }
}
