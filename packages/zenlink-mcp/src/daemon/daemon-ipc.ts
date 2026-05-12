import { Socket } from "node:net";
import { readFileSync } from "node:fs";
import {
  daemonInvokeTimeoutMs,
  defaultDaemonTokenFile,
} from "./daemon-env.js";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

export interface DaemonAddr {
  host: string;
  port: number;
}

interface PendingRequest {
  resolve: (value: CallToolResult) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout | null;
}

export function parseAddrFileLine(line: string): DaemonAddr {
  const trimmed = line.trim();
  const [host, portRaw] = trimmed.split(":");
  const port = Number(portRaw);
  if (!host || !Number.isInteger(port) || port <= 0 || port > 65535) {
    throw new Error(`invalid daemon addr line: ${trimmed}`);
  }
  return { host, port };
}

export function readDaemonTokenFile(addrFile: string): string {
  const tokenFile = defaultDaemonTokenFile(addrFile);
  const token = readFileSync(tokenFile, "utf8").trim();
  if (!token) {
    throw new Error(`empty daemon token file: ${tokenFile}`);
  }
  return token;
}

export class DaemonRpcClient {
  private socket: Socket | null = null;
  private nextId = 1;
  private buffer = "";
  private readonly pending = new Map<number, PendingRequest>();

  constructor(
    private readonly host: string,
    private readonly port: number,
    private readonly token: string,
  ) {}

  async connect(): Promise<void> {
    if (this.socket && !this.socket.destroyed) return;
    const socket = new Socket();
    this.socket = socket;
    socket.setEncoding("utf8");
    socket.on("data", (chunk) => this.onData(chunk.toString()));
    socket.on("error", (error) => this.rejectAll(error));
    socket.on("close", () => this.rejectAll(new Error("connection closed")));
    await new Promise<void>((resolve, reject) => {
      socket.once("connect", resolve);
      socket.once("error", reject);
      socket.connect(this.port, this.host);
    });
  }

  destroy(): void {
    this.rejectAll(new Error("connection destroyed"));
    this.socket?.destroy();
    this.socket = null;
  }

  async invoke(tool: string, rawArgs: unknown): Promise<CallToolResult> {
    if (!this.socket || this.socket.destroyed) {
      throw new Error("not connected");
    }
    const id = this.nextId++;
    const timeoutMs = daemonInvokeTimeoutMs();
    const payload =
      JSON.stringify({ id, token: this.token, tool, args: rawArgs }) + "\n";
    const promise = new Promise<CallToolResult>((resolve, reject) => {
      const timer =
        timeoutMs > 0
          ? setTimeout(() => {
              this.pending.delete(id);
              reject(new Error("daemon invoke timeout"));
            }, timeoutMs)
          : null;
      this.pending.set(id, { resolve, reject, timer });
    });
    try {
      this.socket.write(payload);
    } catch (error) {
      const pending = this.pending.get(id);
      this.pending.delete(id);
      if (pending?.timer) clearTimeout(pending.timer);
      throw error;
    }
    return promise;
  }

  private onData(chunk: string): void {
    this.buffer += chunk;
    for (;;) {
      const idx = this.buffer.indexOf("\n");
      if (idx < 0) return;
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line) continue;
      let msg: {
        id?: number;
        result?: CallToolResult;
        error?: string;
      };
      try {
        msg = JSON.parse(line) as typeof msg;
      } catch (error) {
        this.rejectAll(
          new Error(
            `invalid daemon response JSON: ${error instanceof Error ? error.message : String(error)}`,
          ),
        );
        continue;
      }
      if (typeof msg.id !== "number") {
        this.rejectAll(new Error("daemon response missing id"));
        continue;
      }
      const pending = this.pending.get(msg.id);
      if (!pending) continue;
      this.pending.delete(msg.id);
      if (pending.timer) clearTimeout(pending.timer);
      if (msg.error) {
        pending.reject(new Error(msg.error));
      } else if (msg.result) {
        pending.resolve(msg.result);
      } else {
        pending.reject(new Error("daemon response missing result"));
      }
    }
  }

  private rejectAll(error: Error): void {
    for (const [id, pending] of this.pending) {
      this.pending.delete(id);
      if (pending.timer) clearTimeout(pending.timer);
      pending.reject(error);
    }
  }
}
