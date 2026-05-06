#!/usr/bin/env node
/**
 * OpenClaw-oriented supervisor for zenlink-mcp --daemon (optional).
 *
 * Commands: start | stop | status
 *
 * Requires for start: ZENLINK_AGENT_ID, ZENLINK_TOKEN (or ZENHEART_* aliases).
 * Optional: ZENLINK_MCP_DAEMON_ADDR_FILE, ZENLINK_MCP_DAEMON_SUPERVISOR_PID_FILE
 *   (default: <addrFile>.run.pid).
 *
 * Upgrade: if addr file already points at a live TCP endpoint, start is a no-op
 * (avoids spawning a second daemon when .run.pid was lost). Use stop first, or
 * ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1 after killing the old process.
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
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

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
  return join(tmpdir(), "zenlink-mcp-daemon.addr");
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
      "error: set ZENLINK_AGENT_ID and ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_*)",
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
        const supPid = readPid(pidFile);
        const statusPid = readDaemonPidFromStatus(addrFile);
        if (supPid && alive(supPid)) {
          console.error(
            `note: daemon already reachable at ${host}:${port} (supervisor pid ${supPid})`,
          );
          return;
        }
        console.error(
          `note: daemon already reachable at ${host}:${port} — not spawning another (upgrade: run stop first, or kill pid from ${addrFile}.status.json, or set ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1)`,
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

  const logFd = openAppendingLog(logFile);
  const child = spawn(process.execPath, [cliJs, "--daemon"], {
    detached: true,
    stdio: ["ignore", logFd, logFd],
    env: { ...process.env },
    cwd: pkgRoot,
  });
  child.unref();
  writeFileSync(pidFile, `${child.pid}\n`, { mode: 0o600 });
  console.error(
    `note: spawned zenlink-mcp --daemon pid=${child.pid} (recorded in ${pidFile})`,
  );
  console.error(`note: daemon stdout/stderr -> ${logFile}`);
  console.error(`note: waiting for ${addrFile} …`);

  for (let i = 0; i < 60; i += 1) {
    await delay(500);
    if (!existsSync(addrFile)) {
      continue;
    }
    try {
      const { host, port } = parseAddrLine(addrFile);
      if (await probeTcp(host, port, 1500)) {
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

function cmdStop() {
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
    console.error(`note: no supervisor pid in ${pidFile} and no live pid in status — nothing to stop`);
    try {
      if (existsSync(pidFile)) {
        unlinkSync(pidFile);
      }
    } catch {
      /* ignore */
    }
    return;
  }
  if (!alive(pid)) {
    console.error(`note: pid ${pid} not running`);
    try {
      unlinkSync(pidFile);
    } catch {
      /* ignore */
    }
    return;
  }
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
}

async function cmdStatus() {
  const addrFile = defaultAddrFile();
  const pidFile = defaultPidFile(addrFile);
  const logFile = defaultLogFile(addrFile);
  const pid = readPid(pidFile);
  console.error(`addr_file: ${addrFile}`);
  console.error(`supervisor_pid_file: ${pidFile}`);
  console.error(`log_file: ${logFile}`);
  console.error(`recorded_pid: ${pid ?? "(none)"}`);
  if (pid && alive(pid)) {
    console.error(`recorded_pid_alive: true`);
  } else {
    console.error(`recorded_pid_alive: false`);
  }
  if (!existsSync(addrFile)) {
    console.error("tcp: addr file missing");
    return;
  }
  try {
    const { host, port } = parseAddrLine(addrFile);
    const ok = await probeTcp(host, port);
    console.error(`tcp: ${host}:${port} reachable=${ok}`);
  } catch (e) {
    console.error(
      `tcp: error ${e instanceof Error ? e.message : String(e)}`,
    );
  }
}

const sub = process.argv[2];
if (sub === "start") {
  await cmdStart();
} else if (sub === "stop") {
  cmdStop();
} else if (sub === "status") {
  await cmdStatus();
} else {
  console.error(
    `usage: node scripts/openclaw-zenlink-daemon.mjs start|stop|status [--force]`,
  );
  console.error(
    `  start: optional --force or ZENLINK_MCP_DAEMON_SUPERVISOR_FORCE_START=1 to ignore live addr (use after killing old daemon manually)`,
  );
  process.exit(2);
}
