/**
 * Long-lived process: one **`ZenlinkSession`**, **`/v2/agent/ws`**, tools via TCP NDJSON (**`127.0.0.1:port`** in addr file).
 */

import * as fs from "node:fs";
import type { Socket as NetSocket } from "node:net";
import * as net from "node:net";
import * as readline from "node:readline";

import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { assertAgentEnvLoaded, defaultDaemonAddrFile } from "./daemon-env.js";
import { dispatchZenlinkTool } from "./tool-dispatch.js";
import {
  parseAddrFileLine,
  tcpProbeAccept,
} from "./daemon-ipc.js";
import { ZenlinkSession } from "./session.js";

type WireRequest = {
  v?: number;
  cmd?: string;
  reqId?: string;
  tool?: string;
  args?: unknown;
};

function writeOk(reqId: string, result: CallToolResult): string {
  return `${JSON.stringify({ v: 1, reqId, ok: true as const, result })}\n`;
}

function writeErr(reqId: string, message: string): string {
  return `${JSON.stringify({ v: 1, reqId, ok: false as const, message })}\n`;
}

function safeSockWrite(sock: NetSocket, chunk: string): void {
  try {
    sock.write(chunk);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`zenlink-mcp daemon: socket write failed: ${msg}`);
  }
}

/**
 * Refuses to start when **`addrFile`** points at an **already-live** daemon (**`exit(2)`**).
 * Drops stale files when **`127.0.0.1:port`** rejects.
 */
async function reconcileAddrFileBeforeListening(
  addrFile: string,
): Promise<void> {
  if (!fs.existsSync(addrFile)) {
    return;
  }
  try {
    const line =
      fs.readFileSync(addrFile, "utf8").split(/\r?\n/).find((l) => l.trim()) ??
      "";
    if (!line.trim()) {
      fs.unlinkSync(addrFile);
      return;
    }
    const { host, port } = parseAddrFileLine(line);
    const reachable = await tcpProbeAccept(host, port);
    if (reachable) {
      console.error(
        `zenlink-mcp daemon: endpoint ${host}:${port} is already reachable (${addrFile})`,
      );
      console.error(
        `zenlink-mcp daemon: refusing a second zenlink socket for this addr file (another --daemon?)`,
      );
      process.exit(2);
    }
    fs.unlinkSync(addrFile);
    console.warn(
      `zenlink-mcp daemon: removed unreachable stale addr file (${addrFile})`,
    );
  } catch (e) {
    const detail = e instanceof Error ? e.message : String(e);
    console.warn(
      `zenlink-mcp daemon: could not introspect addr file (${addrFile}) — ${detail}`,
    );
    try {
      fs.unlinkSync(addrFile);
    } catch {
      /* ignore */
    }
  }
}

export async function runZenlinkDaemon(): Promise<void> {
  assertAgentEnvLoaded();
  const addrFile = defaultDaemonAddrFile();
  await reconcileAddrFileBeforeListening(addrFile);

  /** Serialize all invokes — single **`ZenlinkSession`**, **`wsRpc`** cannot overlap. */
  let serialized = Promise.resolve();

  function pushSerialized<T>(fn: () => Promise<T>): Promise<T> {
    const next = serialized.then(fn, fn);
    serialized = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }

  const session = new ZenlinkSession();

  const server = net.createServer((sock) => {
    const rl = readline.createInterface({ input: sock });
    rl.on("line", (line) => {
      let req: WireRequest;
      try {
        req = JSON.parse(line) as WireRequest;
      } catch {
        safeSockWrite(sock, writeErr("?", "invalid JSON line"));
        return;
      }
      if (req.cmd !== "invoke" || typeof req.reqId !== "string") {
        safeSockWrite(
          sock,
          writeErr(req.reqId ?? "", "expected { cmd:invoke, reqId, tool }"),
        );
        return;
      }
      const toolRaw = req.tool;
      if (typeof toolRaw !== "string" || !toolRaw) {
        safeSockWrite(sock, writeErr(req.reqId, "missing tool name"));
        return;
      }

      void pushSerialized(async () => {
        try {
          const result = await dispatchZenlinkTool(
            session,
            toolRaw,
            req.args ?? {},
          );
          safeSockWrite(sock, writeOk(req.reqId!, result));
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          safeSockWrite(sock, writeErr(req.reqId!, msg));
        }
      });
    });
  });

  await new Promise<void>((resolve, reject) => {
    server.listen({ host: "127.0.0.1", port: 0 }, () => resolve());
    server.once("error", reject);
  });

  const a = server.address();
  const port =
    typeof a === "object" &&
    a !== null &&
    "port" in a &&
    typeof a.port === "number"
      ? a.port
      : 0;
  if (!port) {
    throw new Error("zenlink-mcp daemon: server address unavailable");
  }
  const bindLine = `127.0.0.1:${port}\n`;
  fs.writeFileSync(addrFile, bindLine, { mode: 0o600 });

  console.error(`zenlink-mcp daemon: listening tcp 127.0.0.1:${port}`);
  console.error(`zenlink-mcp daemon: addr file ${addrFile}`);
  console.error(`zenlink-mcp daemon: pid ${process.pid}`);

  const shutdown = (): void => {
    try {
      fs.unlinkSync(addrFile);
    } catch {
      /* ignore */
    }
    server.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  await new Promise<void>(() => {
    /* run until signal */
  });
}
