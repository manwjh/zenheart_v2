import { randomUUID } from "node:crypto";
import * as net from "node:net";
import * as readline from "node:readline";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { readDaemonInvokeTimeoutMs } from "./daemon-env.js";

type Pending = {
  resolve: (value: CallToolResult) => void;
  reject: (reason?: unknown) => void;
};

type DaemonRpcResponse = {
  v: 1;
  reqId: string;
  ok: boolean;
  result?: CallToolResult;
  message?: string;
};

export class DaemonRpcClient {
  private readonly host: string;
  private readonly port: number;
  private sock: net.Socket | null = null;
  private rl: readline.Interface | null = null;
  private readonly pending = new Map<string, Pending>();

  constructor(host: string, port: number) {
    this.host = host;
    this.port = port;
  }

  /** Drop TCP + pending RPCs (e.g. daemon restarted with a new port in the addr file). */
  destroy(): void {
    if (this.rl) {
      this.rl.close();
      this.rl = null;
    }
    if (this.sock) {
      this.sock.destroy();
      this.sock = null;
    }
    const err = new Error("zenlink-mcp: daemon IPC client destroyed");
    for (const [, p] of this.pending) {
      p.reject(err);
    }
    this.pending.clear();
  }

  async connect(): Promise<void> {
    if (this.sock) {
      return;
    }
    await new Promise<void>((resolve, reject) => {
      const s = net.connect({ host: this.host, port: this.port }, () => {
        this.sock = s;
        this.rl = readline.createInterface({ input: s });
        this.rl.on("line", (line) => this.onLine(line));
        s.on("error", (e) => this.onSocketError(e));
        s.on("close", () => this.onSocketClose());
        resolve();
      });
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
    let msg: DaemonRpcResponse;
    try {
      msg = JSON.parse(trimmed) as DaemonRpcResponse;
    } catch {
      return;
    }
    if (
      typeof msg !== "object" ||
      msg === null ||
      msg.v !== 1 ||
      typeof msg.reqId !== "string"
    ) {
      return;
    }
    const pend = this.pending.get(msg.reqId);
    if (!pend) {
      return;
    }
    this.pending.delete(msg.reqId);
    if (msg.ok === false) {
      pend.reject(
        new Error(
          typeof msg.message === "string"
            ? msg.message
            : "daemon invoke failed",
        ),
      );
      return;
    }
    pend.resolve(msg.result as CallToolResult);
  }

  invoke(tool: string, args: unknown): Promise<CallToolResult> {
    const sock = this.sock;
    if (!sock || sock.writableEnded) {
      return Promise.reject(
        new Error("zenlink-mcp: daemon IPC not connected (start --daemon?)"),
      );
    }
    const reqId = randomUUID();
    const req = {
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
    return new Promise<CallToolResult>((resolve, reject) => {
      const tid = setTimeout(() => {
        if (this.pending.delete(reqId)) {
          reject(
            new Error(
              `zenlink-mcp daemon IPC invoke timed out after ${ms}ms (set ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS=0 to disable).`,
            ),
          );
        }
      }, ms);
      invokePromise.then(
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
