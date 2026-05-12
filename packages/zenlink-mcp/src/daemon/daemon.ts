import { randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { createConnection, createServer } from "node:net";
import { dirname } from "node:path";
import {
  defaultDaemonAddrFile,
  defaultDaemonTokenFile,
} from "./daemon-env.js";
import { dispatchZenlinkTool } from "../tools/tool-dispatch.js";
import { ZenlinkSession } from "../transport/session.js";

interface DaemonRequest {
  id?: number;
  token?: string;
  tool?: string;
  args?: unknown;
}

export async function runDaemon(): Promise<void> {
  let dispatchQueue: Promise<void> = Promise.resolve();
  const addrFile = defaultDaemonAddrFile();
  const tokenFile = defaultDaemonTokenFile(addrFile);
  const statusFile = `${addrFile}.status.json`;
  const lockFile = `${addrFile}.lock`;
  const token = randomBytes(32).toString("base64url");
  mkdirSync(dirname(addrFile), { recursive: true });
  if (!daemonForceStart()) {
    await assertNoReachableDaemon(addrFile);
  }
  const lockFd = acquireDaemonLock(lockFile);
  registerLockCleanup(lockFile, lockFd);

  const session = new ZenlinkSession();

  const server = createServer((socket) => {
    socket.setEncoding("utf8");
    let buffer = "";
    socket.on("error", (error) => {
      if (!isSocketDisconnectError(error)) {
        console.error(
          `zenlink-mcp daemon socket error: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    });
    socket.on("data", (chunk) => {
      buffer += chunk;
      for (;;) {
        const idx = buffer.indexOf("\n");
        if (idx < 0) return;
        const line = buffer.slice(0, idx).trim();
        buffer = buffer.slice(idx + 1);
        if (!line) continue;
        void handleLine(line, socket);
      }
    });
  });

  await new Promise<void>((resolve) => {
    server.listen(0, "127.0.0.1", resolve);
  });
  const addr = server.address();
  if (!addr || typeof addr === "string") {
    throw new Error("daemon did not bind to a TCP address");
  }
  writeFileSync(tokenFile, `${token}\n`, { encoding: "utf8", mode: 0o600 });
  chmodSync(tokenFile, 0o600);
  writeFileSync(addrFile, `127.0.0.1:${addr.port}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  chmodSync(addrFile, 0o600);
  writeFileSync(
    statusFile,
    `${JSON.stringify(
      {
        schema: "zenlink_mcp_daemon_status/v1",
        pid: process.pid,
        host: "127.0.0.1",
        port: addr.port,
        addr_file: addrFile,
        token_file: tokenFile,
        lock_file: lockFile,
        started_at: new Date().toISOString(),
      },
      null,
      2,
    )}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
  chmodSync(statusFile, 0o600);

  async function handleLine(line: string, socket: import("node:net").Socket): Promise<void> {
    let msg: DaemonRequest = {};
    try {
      msg = JSON.parse(line) as DaemonRequest;
      if (typeof msg.id !== "number") {
        throw new Error("daemon request missing id");
      }
      if (msg.token !== token) {
        throw new Error("daemon authentication failed");
      }
      if (!msg.tool) {
        throw new Error("daemon request missing tool");
      }
      const result = await dispatchWithSessionOrder(msg.tool, msg.args);
      writeDaemonResponse(socket, { id: msg.id, result });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      writeDaemonResponse(socket, { id: msg.id ?? null, error: message });
    }
  }

  async function dispatchWithSessionOrder(tool: string, args: unknown) {
    if (canRunWithoutSessionMutation(tool)) {
      return dispatchZenlinkTool(session, tool, args);
    }
    const previous = dispatchQueue;
    let release: () => void = () => {};
    dispatchQueue = new Promise<void>((resolve) => {
      release = resolve;
    });
    await previous;
    try {
      return await dispatchZenlinkTool(session, tool, args);
    } finally {
      release();
    }
  }
}

function daemonForceStart(): boolean {
  const raw = process.env.ZENLINK_MCP_DAEMON_FORCE_START?.trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

async function assertNoReachableDaemon(addrFile: string): Promise<void> {
  if (!existsSync(addrFile)) return;
  let addr: { host: string; port: number };
  try {
    addr = parseAddrFile(addrFile);
  } catch {
    return;
  }
  if (!(await probeTcp(addr.host, addr.port, 500))) return;
  throw new Error(
    `zenlink-mcp daemon already reachable at ${addr.host}:${addr.port} (${addrFile}); stop it before starting another daemon, or set ZENLINK_MCP_DAEMON_FORCE_START=1 after manual cleanup`,
  );
}

function acquireDaemonLock(lockFile: string): number {
  try {
    const fd = openSync(lockFile, "wx", 0o600);
    writeFileSync(fd, `${process.pid}\n`, { encoding: "utf8" });
    return fd;
  } catch (error) {
    const lockPid = readLockPid(lockFile);
    if (lockPid && isPidAlive(lockPid)) {
      throw new Error(
        `zenlink-mcp daemon lock is held by live pid ${lockPid} (${lockFile}); stop the old daemon before starting another`,
      );
    }
    try {
      unlinkSync(lockFile);
    } catch {
      /* ignore stale lock cleanup failure; retry open will report the real error */
    }
    const fd = openSync(lockFile, "wx", 0o600);
    writeFileSync(fd, `${process.pid}\n`, { encoding: "utf8" });
    return fd;
  }
}

function registerLockCleanup(lockFile: string, lockFd: number): void {
  let cleaned = false;
  const cleanup = () => {
    if (cleaned) return;
    cleaned = true;
    try {
      closeSync(lockFd);
    } catch {
      /* ignore */
    }
    try {
      if (readLockPid(lockFile) === process.pid) {
        unlinkSync(lockFile);
      }
    } catch {
      /* ignore */
    }
  };
  process.once("exit", cleanup);
  for (const signal of ["SIGINT", "SIGTERM"] as const) {
    process.once(signal, () => {
      cleanup();
      process.exit(0);
    });
  }
}

function readLockPid(lockFile: string): number | null {
  try {
    const raw = readFileSync(lockFile, "utf8").trim();
    const pid = Number.parseInt(raw, 10);
    return Number.isFinite(pid) && pid > 0 ? pid : null;
  } catch {
    return null;
  }
}

function isPidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function parseAddrFile(addrFile: string): { host: string; port: number } {
  const line =
    readFileSync(addrFile, "utf8")
      .split(/\r?\n/)
      .find((value) => value.trim())
      ?.trim() ?? "";
  const index = line.lastIndexOf(":");
  if (index <= 0) {
    throw new Error(`invalid daemon addr line in ${addrFile}`);
  }
  const host = line.slice(0, index).trim();
  const port = Number.parseInt(line.slice(index + 1).trim(), 10);
  if (!host || !Number.isFinite(port) || port < 1 || port > 65535) {
    throw new Error(`invalid daemon addr in ${addrFile}`);
  }
  return { host, port };
}

function probeTcp(host: string, port: number, timeoutMs: number): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const socket = createConnection({ host, port });
    const finish = (ok: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(ok);
    };
    const timer = setTimeout(() => finish(false), timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

export function writeDaemonResponse(
  socket: Pick<import("node:net").Socket, "destroyed" | "writableEnded" | "write">,
  payload: unknown,
): boolean {
  if (socket.destroyed || socket.writableEnded) return false;
  try {
    socket.write(`${JSON.stringify(payload)}\n`);
    return true;
  } catch (error) {
    if (isSocketDisconnectError(error)) return false;
    throw error;
  }
}

export function isSocketDisconnectError(error: unknown): boolean {
  const maybe = error as { code?: unknown; message?: unknown };
  const code = typeof maybe?.code === "string" ? maybe.code : "";
  const message = typeof maybe?.message === "string" ? maybe.message : String(error);
  return (
    code === "EPIPE" ||
    code === "ECONNRESET" ||
    code === "ERR_STREAM_DESTROYED" ||
    message.includes("EPIPE") ||
    message.includes("ECONNRESET") ||
    message.includes("write after end") ||
    message.includes("This socket has been ended")
  );
}

export function canRunWithoutSessionMutation(tool: string): boolean {
  return (
    tool === "zenlink_status" ||
    tool === "zenlink_doctor" ||
    tool === "zenlink_inbound_stats" ||
    tool === "zenlink_social_grounding"
  );
}
