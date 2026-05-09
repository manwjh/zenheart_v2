#!/usr/bin/env node
/**
 * OpenClaw-oriented supervisor for zenlink-mcp --daemon (optional).
 *
 * Commands: start | stop | status
 *
 * Requires for start: ZENLINK_AGENT_ID, ZENLINK_TOKEN from the registration email.
 * Optional: ZENLINK_MCP_DAEMON_ADDR_FILE, ZENLINK_MCP_DAEMON_SUPERVISOR_PID_FILE
 *   (default: <addrFile>.run.pid).
 *
 * Upgrade: if addr file already points at a live TCP endpoint, start is a no-op
 * (avoids spawning a second daemon when .run.pid was lost). Use stop first, or
 * ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1 after killing the old process.
 *
 * stop --require-dead (or ZENLINK_MCP_DAEMON_STOP_REQUIRE_DEAD=1): wait until the
 * daemon PID exits (SIGKILL if needed) and until TCP at addr-file host:port is down,
 * else exit 1. Used by upgrade-offline-install.sh so upgrades fail closed instead of
 * swapping trees while a listener is still up.
 */
import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  openSync,
  readFileSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import * as net from "node:net";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { resolveNodeCommand } from "./node-command-helper.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(scriptDir, "..");
const cliJs = resolve(pkgRoot, "dist", "cli.js");

function defaultAddrFile() {
  const fromEnv = process.env.ZENLINK_MCP_DAEMON_ADDR_FILE?.trim();
  if (fromEnv) {
    try {
      mkdirSync(dirname(fromEnv), { recursive: true });
    } catch {
      /* ignore */
    }
    return fromEnv;
  }
  if (
    process.env.ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP === "1" &&
    process.platform !== "win32"
  ) {
    return "/tmp/zenlink-mcp-daemon.addr";
  }
  return join(homedir(), ".openclaw", "tmp", "zenlink-mcp-daemon.addr");
}

function defaultPidFile(addrFile) {
  return (
    process.env.ZENLINK_MCP_DAEMON_SUPERVISOR_PID_FILE?.trim() ||
    `${addrFile}.run.pid`
  );
}

function defaultLogFile(addrFile) {
  return (
    process.env.ZENLINK_MCP_DAEMON_LOG_FILE?.trim() ||
    `${addrFile}.log`
  );
}

function openAppendingLog(path) {
  try {
    mkdirSync(dirname(path), { recursive: true });
  } catch {
    /* ignore */
  }
  return openSync(path, "a", 0o600);
}

function parseAddrLine(addrFile) {
  const line =
    readFileSync(addrFile, "utf8")
      .split(/\r?\n/)
      .find((l) => l.trim())
      ?.trim() ?? "";
  const i = line.lastIndexOf(":");
  if (i <= 0) {
    throw new Error(`invalid addr line in ${addrFile}`);
  }
  const host = line.slice(0, i).trim();
  const port = Number.parseInt(line.slice(i + 1).trim(), 10);
  if (!host || !Number.isFinite(port)) {
    throw new Error(`invalid addr in ${addrFile}`);
  }
  return { host, port };
}

function tokenFileForAddrFile(addrFile) {
  return `${addrFile}.token`;
}

function readDaemonToken(addrFile) {
  const tokenFile = tokenFileForAddrFile(addrFile);
  if (!existsSync(tokenFile)) {
    return { ok: false, tokenFile, error: "token_file_missing" };
  }
  const token = readFileSync(tokenFile, "utf8").trim();
  if (!token) {
    return { ok: false, tokenFile, error: "token_file_empty" };
  }
  return { ok: true, tokenFile, token };
}

function probeTcp(host, port, ms = 2000) {
  return new Promise((resolve) => {
    const sock = net.connect({ host, port }, () => {
      sock.destroy();
      resolve(true);
    });
    sock.once("error", () => resolve(false));
    setTimeout(() => {
      sock.destroy();
      resolve(false);
    }, ms);
  });
}

function invokeDaemonRpc(host, port, token, tool, args = {}, ms = 3000) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    let buffer = "";
    let settled = false;
    let timer;
    const done = (result) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(result);
    };
    timer = setTimeout(() => {
      done({ ok: false, error: "daemon_rpc_timeout" });
    }, ms);
    socket.setEncoding("utf8");
    socket.once("connect", () => {
      socket.write(JSON.stringify({ id: 1, token, tool, args }) + "\n");
    });
    socket.on("data", (chunk) => {
      buffer += chunk;
      const idx = buffer.indexOf("\n");
      if (idx < 0) {
        return;
      }
      const line = buffer.slice(0, idx).trim();
      try {
        const msg = JSON.parse(line);
        if (msg.error) {
          done({ ok: false, error: msg.error });
        } else {
          done({ ok: true, result: msg.result });
        }
      } catch (error) {
        done({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      }
    });
    socket.once("error", (error) => {
      done({ ok: false, error: error.message });
    });
    socket.once("close", () => {
      done({ ok: false, error: "daemon_rpc_closed" });
    });
  });
}

function daemonRpcTimeoutMs() {
  const raw = process.env.ZENLINK_MCP_DAEMON_HEALTH_TIMEOUT_MS?.trim();
  if (!raw) {
    return 3000;
  }
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("ZENLINK_MCP_DAEMON_HEALTH_TIMEOUT_MS must be a positive number");
  }
  return Math.floor(value);
}

function requireWsOnline() {
  const raw = process.env.ZENLINK_MCP_REQUIRE_WS_ONLINE?.trim().toLowerCase();
  return raw === "1" || raw === "true" || raw === "yes" || raw === "on";
}

function parseToolTextJson(result) {
  const text = result?.content?.find?.((item) => item?.type === "text")?.text;
  if (typeof text !== "string") {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function checkDaemonHealth(addrFile) {
  if (!existsSync(addrFile)) {
    return { ok: false, reason: "addr_file_missing" };
  }
  let addr;
  try {
    addr = parseAddrLine(addrFile);
  } catch (error) {
    return {
      ok: false,
      reason: "addr_file_invalid",
      detail: error instanceof Error ? error.message : String(error),
    };
  }
  const tcpReachable = await probeTcp(addr.host, addr.port);
  if (!tcpReachable) {
    return { ok: false, reason: "tcp_unreachable", ...addr };
  }
  const token = readDaemonToken(addrFile);
  if (!token.ok) {
    return { ok: false, reason: token.error, token_file: token.tokenFile, ...addr };
  }
  const rpc = await invokeDaemonRpc(
    addr.host,
    addr.port,
    token.token,
    "zenlink_status",
    {},
    daemonRpcTimeoutMs(),
  );
  if (!rpc.ok) {
    return { ok: false, reason: "daemon_rpc_failed", detail: rpc.error, ...addr };
  }
  const status = parseToolTextJson(rpc.result);
  const wsOnline = status?.online === true;
  if (requireWsOnline() && !wsOnline) {
    return {
      ok: false,
      reason: "ws_offline",
      detail: "daemon RPC is healthy but ZenHeart WebSocket is offline",
      token_file: token.tokenFile,
      status,
      ...addr,
    };
  }
  return {
    ok: true,
    reason: "ok",
    token_file: token.tokenFile,
    ws_online: wsOnline,
    status,
    ...addr,
  };
}

function readPid(path) {
  if (!existsSync(path)) {
    return null;
  }
  const n = Number.parseInt(readFileSync(path, "utf8").trim(), 10);
  return Number.isFinite(n) ? n : null;
}

/** Daemon writes `${addrFile}.status.json` with `pid` — used when .run.pid is missing after upgrades. */
function readDaemonPidFromStatus(addrFile) {
  const statusPath = `${addrFile}.status.json`;
  if (!existsSync(statusPath)) {
    return null;
  }
  try {
    const j = JSON.parse(readFileSync(statusPath, "utf8"));
    const p = j.pid;
    return typeof p === "number" && Number.isFinite(p) ? Math.floor(p) : null;
  } catch {
    return null;
  }
}

function alive(pid) {
  if (!pid || pid <= 0) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function requireAgentEnv() {
  const aid =
    process.env.ZENLINK_AGENT_ID ??
    process.env.ZENHEART_AGENT_ID ??
    process.env.ZENHEART_V2_AGENT_ID;
  const tok =
    process.env.ZENLINK_TOKEN ??
    process.env.ZENHEART_TOKEN ??
    process.env.ZENHEART_V2_TOKEN;
  if (!aid?.trim() || !tok?.trim()) {
    console.error(
      "error: set ZENLINK_AGENT_ID and ZENLINK_TOKEN from the registration email",
    );
    process.exit(1);
  }
}

async function cmdStart() {
  requireAgentEnv();
  if (!existsSync(cliJs)) {
    console.error("error: dist/cli.js missing — run npm run build");
    process.exit(1);
  }

  const addrFile = defaultAddrFile();
  const pidFile = defaultPidFile(addrFile);
  const logFile = defaultLogFile(addrFile);
  const forceStart =
    process.env.ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START === "1" ||
    process.argv.includes("--force");

  if (existsSync(addrFile) && !forceStart) {
    try {
      const { host, port } = parseAddrLine(addrFile);
      if (await probeTcp(host, port)) {
        const health = await checkDaemonHealth(addrFile);
        const supPid = readPid(pidFile);
        const statusPid = readDaemonPidFromStatus(addrFile);
        if (!health.ok) {
          console.error(
            `error: daemon TCP is reachable at ${host}:${port}, but authenticated health failed (${health.reason}${health.detail ? `: ${health.detail}` : ""})`,
          );
          console.error(
            `       This usually means an old daemon is still running, the ${tokenFileForAddrFile(addrFile)} file is missing/stale, or OpenClaw workers have not been recycled.`,
          );
          console.error(
            "       Run: node scripts/openclaw-zenlink-daemon.mjs stop --require-dead, then start, then openclaw gateway restart.",
          );
          if (statusPid && alive(statusPid)) {
            console.error(`note: status.json pid ${statusPid} (likely the daemon process)`);
          }
          process.exit(1);
        }
        if (supPid && alive(supPid)) {
          console.error(
            `note: daemon already healthy at ${host}:${port} (supervisor pid ${supPid})`,
          );
          return;
        }
        console.error(
          `note: daemon already healthy at ${host}:${port} — not spawning another (upgrade: run stop first, or kill pid from ${addrFile}.status.json, or set ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1)`,
        );
        if (statusPid && alive(statusPid)) {
          console.error(`note: status.json pid ${statusPid} (likely the daemon process)`);
        }
        return;
      }
    } catch {
      /* stale addr — daemon will reconcile */
    }
  }

  const nodeCommand = resolveNodeCommand();
  const logFd = openAppendingLog(logFile);
  const child = spawn(nodeCommand, [cliJs, "--daemon"], {
    detached: true,
    stdio: ["ignore", logFd, logFd],
    env: {
      ...process.env,
      ZENLINK_MCP_DAEMON_ADDR_FILE: addrFile,
      ZENLINK_MCP_USE_DAEMON: "0",
    },
    cwd: pkgRoot,
  });
  child.unref();
  writeFileSync(pidFile, `${child.pid}\n`, { mode: 0o600 });
  console.error(
    `note: spawned zenlink-mcp --daemon pid=${child.pid} (recorded in ${pidFile})`,
  );
  console.error(`note: daemon command: ${nodeCommand}`);
  console.error(`note: daemon stdout/stderr -> ${logFile}`);
  console.error(`note: waiting for ${addrFile} …`);

  for (let i = 0; i < 60; i += 1) {
    await delay(500);
    if (!existsSync(addrFile)) {
      continue;
    }
    try {
      const { host, port } = parseAddrLine(addrFile);
      const health = await checkDaemonHealth(addrFile);
      if (health.ok) {
        console.error(`note: daemon ready ${host}:${port}`);
        return;
      }
    } catch {
      /* keep waiting */
    }
  }
  console.error("error: daemon did not publish a reachable addr in time");
  process.exit(1);
}

async function verifyTcpDown(host, port) {
  for (let i = 0; i < 48; i += 1) {
    if (!(await probeTcp(host, port, 400))) {
      return true;
    }
    await delay(250);
  }
  return false;
}

async function cmdStop({ requireDead }) {
  const addrFile = defaultAddrFile();
  const pidFile = defaultPidFile(addrFile);
  let pid = readPid(pidFile);
  if (!pid || !alive(pid)) {
    const fromStatus = readDaemonPidFromStatus(addrFile);
    if (fromStatus && alive(fromStatus)) {
      pid = fromStatus;
      console.error(`note: using daemon pid ${pid} from ${addrFile}.status.json`);
    }
  }
  if (!pid) {
    console.error(
      `note: no supervisor pid in ${pidFile} and no live pid in status — nothing to stop`,
    );
    try {
      if (existsSync(pidFile)) {
        unlinkSync(pidFile);
      }
    } catch {
      /* ignore */
    }
  } else if (!alive(pid)) {
    console.error(`note: pid ${pid} not running`);
    try {
      unlinkSync(pidFile);
    } catch {
      /* ignore */
    }
  } else {
    try {
      process.kill(pid, "SIGTERM");
    } catch (e) {
      console.error(e instanceof Error ? e.message : e);
      process.exit(1);
    }
    console.error(`note: sent SIGTERM to pid ${pid}`);
    try {
      unlinkSync(pidFile);
    } catch {
      /* ignore */
    }
    if (requireDead) {
      for (let i = 0; i < 48; i += 1) {
        await delay(250);
        if (!alive(pid)) {
          break;
        }
      }
      if (alive(pid)) {
        try {
          process.kill(pid, "SIGKILL");
          console.error(`note: sent SIGKILL to pid ${pid}`);
        } catch (e) {
          console.error(e instanceof Error ? e.message : e);
          process.exit(1);
        }
        await delay(400);
      }
    }
  }

  if (!requireDead) {
    return;
  }
  if (!existsSync(addrFile)) {
    return;
  }
  let host;
  let port;
  try {
    ({ host, port } = parseAddrLine(addrFile));
  } catch {
    return;
  }
  const ok = await verifyTcpDown(host, port);
  if (!ok) {
    console.error(
      `error: zenlink-mcp daemon TCP still reachable at ${host}:${port} after stop — wrong ZENLINK_MCP_DAEMON_ADDR_FILE, stale addr file, or unrelated listener`,
    );
    process.exit(1);
  }
}

async function cmdStatus() {
  const addrFile = defaultAddrFile();
  const pidFile = defaultPidFile(addrFile);
  const logFile = defaultLogFile(addrFile);
  const tokenFile = tokenFileForAddrFile(addrFile);
  const pid = readPid(pidFile);
  const statusPid = readDaemonPidFromStatus(addrFile);
  console.error(`addr_file: ${addrFile}`);
  console.error(`token_file: ${tokenFile}`);
  console.error(`supervisor_pid_file: ${pidFile}`);
  console.error(`log_file: ${logFile}`);
  console.error(`recorded_pid: ${pid ?? "(none)"}`);
  if (pid && alive(pid)) {
    console.error(`recorded_pid_alive: true`);
  } else {
    console.error(`recorded_pid_alive: false`);
  }
  console.error(`status_json_pid: ${statusPid ?? "(none)"}`);
  if (statusPid && alive(statusPid)) {
    console.error(`status_json_pid_alive: true`);
  } else {
    console.error(`status_json_pid_alive: false`);
  }
  const token = readDaemonToken(addrFile);
  console.error(`token_file_exists: ${existsSync(tokenFile)}`);
  console.error(`token_file_ok: ${token.ok}`);
  if (!existsSync(addrFile)) {
    console.error("tcp: addr file missing");
    return;
  }
  try {
    const { host, port } = parseAddrLine(addrFile);
    const ok = await probeTcp(host, port);
    console.error(`tcp: ${host}:${port} reachable=${ok}`);
    const health = await checkDaemonHealth(addrFile);
    console.error(`authenticated_rpc: ok=${health.ok} reason=${health.reason}`);
    if (health.status) {
      console.error(`ws_online: ${health.ws_online}`);
      console.error(`connection_state: ${health.status.connection_state ?? "(unknown)"}`);
      console.error(`last_ws_frame_at: ${health.status.last_ws_frame_at ?? "(none)"}`);
      console.error(`last_ws_close_at: ${health.status.last_ws_close_at ?? "(none)"}`);
      console.error(`last_ws_close_code: ${health.status.last_ws_close_code ?? "(none)"}`);
      console.error(`passive_disconnect_total: ${health.status.passive_disconnect_total ?? 0}`);
      console.error(`connect_failure_total: ${health.status.connect_failure_total ?? 0}`);
      console.error(`ws_superseded_total: ${health.status.ws_superseded_total ?? 0}`);
    }
    if (health.detail) {
      console.error(`authenticated_rpc_detail: ${health.detail}`);
    }
    if (!health.ok) {
      console.error(
        "next: stop old daemon with --require-dead, start this version, then run openclaw gateway restart",
      );
    }
  } catch (e) {
    console.error(
      `tcp: error ${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

const sub = process.argv[2];
const rest = process.argv.slice(3);
const stopRequireDead =
  rest.includes("--require-dead") ||
  process.env.ZENLINK_MCP_DAEMON_STOP_REQUIRE_DEAD === "1";
if (sub === "start") {
  await cmdStart();
} else if (sub === "stop") {
  await cmdStop({ requireDead: stopRequireDead });
} else if (sub === "status") {
  await cmdStatus();
} else {
  console.error(
    `usage: node scripts/openclaw-zenlink-daemon.mjs start|stop|status [--force] [--require-dead]`,
  );
  console.error(
    `  start: optional --force or ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1 to ignore live addr (use after killing old daemon manually)`,
  );
  console.error(
    `  stop: optional --require-dead (or ZENLINK_MCP_DAEMON_STOP_REQUIRE_DEAD=1) wait until process + TCP addr are down`,
  );
  process.exit(2);
}
