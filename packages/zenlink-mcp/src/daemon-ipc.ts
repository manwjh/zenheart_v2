/**
 * NDJSON IPC over TCP loopback — stdio MCP peers forward **`invoke`** to **`--daemon`**.
 */

import * as net from "node:net";
import * as readline from "node:readline";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { randomUUID } from "node:crypto";
import { readDaemonInvokeTimeoutMs } from "./daemon-env.js";

type WireRequest = {
  v: 1;
  cmd: "invoke";
  reqId: string;
  tool: string;
  /** JSON payload; use **`{}`** when the tool has no args. */
  args: unknown;
};

type WireOk = {
  v: 1;
  reqId: string;
  ok: true;
  result: CallToolResult;
};

type WireErr = {
  v: 1;
  reqId: string;
  ok: false;
  message: string;
};

export class DaemonRpcClient {
  private sock: net.Socket | null = null;
  private rl: readline.Interface | null = null;
  private pending = new Map<
    string,
    { resolve: (r: CallToolResult) => void; reject: (e: Error) => void }
  >();

  constructor(
    private readonly host: string,
    private readonly port: number,
  ) {}

  /** Connect and start the response reader (idempotent). */
  async connect(): Promise<void> {
    if (this.sock) {
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const s = net.connect(
        { host: this.host, port: this.port },
        () => {
          this.sock = s;
          this.rl = readline.createInterface({ input: s });
          this.rl.on("line", (line) => this.onLine(line));
          s.on("error", (e) => this.onSocketError(e));
          s.on("close", () => this.onSocketClose());
          resolve();
        },
      );
      s.once("error", reject);
    });
  }

  private onSocketError(e: Error): void {
    for (const [, p] of this.pending) {
      p.reject(e);
    }
    this.pending.clear();
  }

  private onSocketClose(): void {
    const err = new Error("zenlink-mcp: daemon connection closed");
    for (const [, p] of this.pending) {
      p.reject(err);
    }
    this.pending.clear();
    this.sock = null;
    if (this.rl) {
      this.rl.close();
      this.rl = null;
    }
  }

  private onLine(line: string): void {
    const trimmed = line.trim();
    if (!trimmed) {
      return;
    }
    let msg: WireOk | WireErr;
    try {
      msg = JSON.parse(trimmed) as WireOk | WireErr;
    } catch {
      return;
    }
    if (
      typeof msg !== "object" ||
      msg === null ||
      (msg as { v?: unknown }).v !== 1 ||
      typeof (msg as WireErr).reqId !== "string"
    ) {
      return;
    }
    const pend = this.pending.get((msg as WireErr).reqId);
    if (!pend) {
      return;
    }
    this.pending.delete((msg as WireErr).reqId);
    if ((msg as WireErr).ok === false) {
      pend.reject(
        new Error(
          typeof (msg as WireErr).message === "string"
            ? (msg as WireErr).message
            : "daemon invoke failed",
        ),
      );
      return;
    }
    pend.resolve((msg as WireOk).result);
  }

  /** Forward a tool invocation to the daemon. */
  invoke(tool: string, args: unknown): Promise<CallToolResult> {
    const sock = this.sock;
    if (!sock || sock.writableEnded) {
      return Promise.reject(
        new Error("zenlink-mcp: daemon IPC not connected (start --daemon?)"),
      );
    }
    const reqId = randomUUID();
    const req: WireRequest = {
      v: 1,
      cmd: "invoke",
      reqId,
      tool,
      args: args === undefined ? {} : args,
    };
    const invokePromise = new Promise<CallToolResult>((resolve, reject) => {
      this.pending.set(reqId, { resolve, reject });
      try {
        sock.write(`${JSON.stringify(req)}\n`);
      } catch (e) {
        this.pending.delete(reqId);
        reject(e instanceof Error ? e : new Error(String(e)));
      }
    });
    const ms = readDaemonInvokeTimeoutMs();
    if (ms <= 0) {
      return invokePromise;
    }
    return new Promise((resolve, reject) => {
      const tid = setTimeout(() => {
        if (this.pending.delete(reqId)) {
          reject(
            new Error(
              `zenlink-mcp daemon IPC invoke timed out after ${ms}ms (set ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS=0 to disable).`,
            ),
          );
        }
      }, ms);
      invokePromise
        .then(
          (r) => {
            clearTimeout(tid);
            resolve(r);
          },
          (err) => {
            clearTimeout(tid);
            reject(err);
          },
        );
    });
  }
}

/** Probe whether **`TCP host:port`** accepts a connection (**`resolve(false)` on timeout/error). */
export function tcpProbeAccept(
  host: string,
  port: number,
  opts?: { timeoutMs?: number },
): Promise<boolean> {
  const timeoutMs = opts?.timeoutMs ?? 2500;
  return new Promise((resolve) => {
    let done = false;
    const sock = net.connect({ host, port });

    function cleanup(ok: boolean): void {
      if (done) {
        return;
      }
      done = true;
      clearTimeout(timer);
      sock.removeAllListeners();
      sock.destroy();
      resolve(ok);
    }

    const timer = setTimeout(() => cleanup(false), timeoutMs);
    sock.once("connect", () => cleanup(true));
    sock.once("error", () => cleanup(false));
  });
}

/** Parse **`127.0.0.1:18444`** (host may include colons for IPv6 if bracketed later). */
export function parseAddrFileLine(line: string): { host: string; port: number } {
  const s = line.trim();
  const lastColon = s.lastIndexOf(":");
  if (lastColon <= 0) {
    throw new Error(`zenlink-mcp: invalid daemon addr line: ${line}`);
  }
  const host = s.slice(0, lastColon).trim();
  const port = Number.parseInt(s.slice(lastColon + 1).trim(), 10);
  if (!host || !Number.isFinite(port) || port <= 0 || port > 65535) {
    throw new Error(`zenlink-mcp: invalid daemon addr: ${line}`);
  }
  return { host, port };
}
