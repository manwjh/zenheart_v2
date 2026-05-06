import * as fs from "node:fs";
import * as net from "node:net";
import * as os from "node:os";
import * as readline from "node:readline";
import { assertAgentEnvLoaded, defaultDaemonAddrFile } from "./daemon-env.js";
import { dispatchZenlinkTool } from "../tools/tool-dispatch.js";
import { parseAddrFileLine, tcpProbeAccept } from "./daemon-ipc.js";
import { ZenlinkSession } from "../transport/session.js";

function daemonLockFilePath(addrFile: string): string {
  return (
    process.env["ZENLINK_MCP_DAEMON_LOCK_FILE"]?.trim() || `${addrFile}.lock`
  );
}

function processAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function acquireDaemonLock(lockFile: string): { release: () => void } {
  const payload = JSON.stringify(
    { pid: process.pid, started_at: new Date().toISOString() },
    null,
    2,
  );
  for (;;) {
    try {
      const fd = fs.openSync(lockFile, "wx", 0o600);
      fs.writeFileSync(fd, `${payload}\n`, "utf8");
      fs.closeSync(fd);
      return {
        release: () => {
          try {
            fs.unlinkSync(lockFile);
          } catch {
            /* ignore */
          }
        },
      };
    } catch (e) {
      const err = e as NodeJS.ErrnoException;
      if (err.code !== "EEXIST") {
        throw e;
      }
      try {
        const raw = JSON.parse(fs.readFileSync(lockFile, "utf8")) as {
          pid?: number;
        };
        const existingPid =
          typeof raw.pid === "number" ? Math.floor(raw.pid) : -1;
        if (processAlive(existingPid)) {
          throw new Error(
            `zenlink-mcp daemon: another instance holds lock (${lockFile}, pid ${existingPid})`,
          );
        }
      } catch (inner) {
        if (
          inner instanceof Error &&
          inner.message.includes("another instance")
        ) {
          throw inner;
        }
      }
      try {
        fs.unlinkSync(lockFile);
      } catch {
        throw new Error(
          `zenlink-mcp daemon: lock file already exists (${lockFile}) and cannot be recovered`,
        );
      }
    }
  }
}

function readDaemonStatusFile(addrFile: string): string {
  return (
    process.env["ZENLINK_MCP_DAEMON_STATUS_FILE"]?.trim() ||
    `${addrFile}.status.json`
  );
}

function readDaemonStateFile(addrFile: string): string {
  return (
    process.env["ZENLINK_MCP_DAEMON_STATE_FILE"]?.trim() ||
    `${addrFile}.state.json`
  );
}

function logStructured(event: string, detail?: unknown): void {
  console.log(
    JSON.stringify({
      ts: new Date().toISOString(),
      level: "info",
      component: "zenlink-mcp-daemon",
      event,
      ...(detail ? { detail } : {}),
    }),
  );
}

function writeJsonFile(path: string, data: unknown): void {
  fs.writeFileSync(path, `${JSON.stringify(data, null, 2)}\n`, { mode: 0o600 });
}

function readPersistedTrackedRoomId(stateFile: string): string | null {
  if (!fs.existsSync(stateFile)) {
    return null;
  }
  try {
    const raw = JSON.parse(fs.readFileSync(stateFile, "utf8")) as {
      tracked_room_id?: unknown;
    };
    return typeof raw.tracked_room_id === "string" &&
      raw.tracked_room_id.length > 0
      ? raw.tracked_room_id
      : null;
  } catch {
    return null;
  }
}

function writeOk(reqId: string, result: unknown): string {
  return `${JSON.stringify({ v: 1, reqId, ok: true, result })}\n`;
}

function writeErr(reqId: string, message: string): string {
  return `${JSON.stringify({ v: 1, reqId, ok: false, message })}\n`;
}

function safeSockWrite(sock: net.Socket, chunk: string): void {
  try {
    sock.write(chunk);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`zenlink-mcp daemon: socket write failed: ${msg}`);
  }
}

async function reconcileAddrFileBeforeListening(
  addrFile: string,
): Promise<void> {
  if (!fs.existsSync(addrFile)) {
    return;
  }
  try {
    const line =
      fs
        .readFileSync(addrFile, "utf8")
        .split(/\r?\n/)
        .find((l) => l.trim()) ?? "";
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
        "zenlink-mcp daemon: refusing a second listener for this addr file",
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
      `zenlink-mcp daemon: could not introspect addr file (${addrFile}) - ${detail}`,
    );
    try {
      fs.unlinkSync(addrFile);
    } catch {
      /* ignore */
    }
  }
}

type DaemonRequest = {
  cmd?: unknown;
  reqId?: unknown;
  tool?: unknown;
  args?: unknown;
};

export async function runZenlinkDaemon(): Promise<void> {
  assertAgentEnvLoaded();

  const addrFile = defaultDaemonAddrFile();
  const lockFile = daemonLockFilePath(addrFile);
  const daemonLock = acquireDaemonLock(lockFile);
  const statusFile = readDaemonStatusFile(addrFile);
  const stateFile = readDaemonStateFile(addrFile);
  await reconcileAddrFileBeforeListening(addrFile);

  const status = {
    pid: process.pid,
    listening: false,
    addr_file: addrFile,
    daemon_addr: null as string | null,
    ws_superseded_total: 0,
    current_room_id: null as string | null,
    room_restore_pending: false,
    last_event: "booting",
    updated_at: new Date().toISOString(),
  };

  function flushStatus(event: string): void {
    status.last_event = event;
    status.updated_at = new Date().toISOString();
    writeJsonFile(statusFile, status);
  }

  function flushState(roomId: string | null): void {
    writeJsonFile(stateFile, {
      tracked_room_id: roomId,
      updated_at: new Date().toISOString(),
      host: os.hostname(),
      pid: process.pid,
    });
  }

  const session = new ZenlinkSession({
    onSuperseded: ({ total }) => {
      status.ws_superseded_total = total;
      flushStatus("ws_superseded");
      logStructured("ws_superseded", { total, status_file: statusFile });
    },
    onRoomStateChanged: ({ current_room_id, room_restore_pending }) => {
      status.current_room_id = current_room_id;
      status.room_restore_pending = room_restore_pending;
      flushStatus("room_state_changed");
      flushState(current_room_id);
    },
    onLifecycleLog: ({ event, detail }) => {
      flushStatus(event);
      logStructured(event, detail);
    },
  });

  const server = net.createServer((sock) => {
    const rl = readline.createInterface({ input: sock });
    rl.on("line", (line) => {
      let req: DaemonRequest;
      try {
        req = JSON.parse(line) as DaemonRequest;
      } catch {
        safeSockWrite(sock, writeErr("?", "invalid JSON line"));
        return;
      }
      if (req.cmd !== "invoke" || typeof req.reqId !== "string") {
        safeSockWrite(
          sock,
          writeErr(
            typeof req.reqId === "string" ? req.reqId : "",
            "expected { cmd:invoke, reqId, tool }",
          ),
        );
        return;
      }
      const reqId = req.reqId;
      if (typeof req.tool !== "string" || !req.tool) {
        safeSockWrite(sock, writeErr(reqId, "missing tool name"));
        return;
      }
      const toolName = req.tool;
      void (async () => {
        try {
          const result = await dispatchZenlinkTool(
            session,
            toolName,
            req.args ?? {},
          );
          safeSockWrite(sock, writeOk(reqId, result));
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e);
          safeSockWrite(sock, writeErr(reqId, msg));
        }
      })();
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
  status.listening = true;
  status.daemon_addr = bindLine.trim();
  flushStatus("listening");
  logStructured("daemon_listening", {
    listen_addr: bindLine.trim(),
    addr_file: addrFile,
    status_file: statusFile,
    state_file: stateFile,
    lock_file: lockFile,
    pid: process.pid,
  });

  const trackedRoomId = readPersistedTrackedRoomId(stateFile);
  if (trackedRoomId) {
    logStructured("room_restore_bootstrap", { room_id: trackedRoomId });
    session.markRoomRestorePending(trackedRoomId);
    try {
      const restored = await session.restoreTrackedRoomMembership();
      logStructured("room_restore_bootstrap_done", restored);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      flushStatus("room_restore_bootstrap_failed");
      logStructured("room_restore_bootstrap_failed", {
        message,
        room_id: trackedRoomId,
      });
    }
  }

  const shutdown = (): void => {
    status.listening = false;
    flushStatus("shutdown");
    logStructured("daemon_shutdown", {
      addr_file: addrFile,
      keep_addr_file: true,
    });
    server.close();
    daemonLock.release();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", () => daemonLock.release());

  await new Promise<void>(() => {
    /* run until signal */
  });
}
