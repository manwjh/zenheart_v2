#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";
import * as net from "node:net";

const REQUIRE_AUTO_WAKE =
  process.env.ZENLINK_MCP_REQUIRE_AUTO_WAKE === "1" ||
  String(process.env.ZENLINK_MCP_REQUIRE_AUTO_WAKE ?? "").toLowerCase() === "true";
const REQUIRE_WS_ONLINE =
  process.env.ZENLINK_MCP_REQUIRE_WS_ONLINE === "1" ||
  String(process.env.ZENLINK_MCP_REQUIRE_WS_ONLINE ?? "").toLowerCase() === "true";

const checks = [];

function add(id, ok, detail = "") {
  checks.push({ id, ok, detail });
}

function parseAddrLine(line) {
  const trimmed = line.trim();
  const i = trimmed.lastIndexOf(":");
  if (i <= 0) {
    throw new Error(`invalid daemon addr line: ${trimmed}`);
  }
  const host = trimmed.slice(0, i).trim();
  const port = Number.parseInt(trimmed.slice(i + 1).trim(), 10);
  if (!host || !Number.isFinite(port) || port <= 0 || port > 65535) {
    throw new Error(`invalid daemon addr line: ${trimmed}`);
  }
  return { host, port };
}

function daemonRpcTimeoutMs() {
  const raw = process.env.ZENLINK_MCP_DAEMON_HEALTH_TIMEOUT_MS?.trim();
  if (!raw) return 3000;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("ZENLINK_MCP_DAEMON_HEALTH_TIMEOUT_MS must be a positive number");
  }
  return Math.floor(value);
}

function parseToolTextJson(result) {
  const text = result?.content?.find?.((item) => item?.type === "text")?.text;
  if (typeof text !== "string") return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function invokeDaemonRpc(host, port, token, tool, args = {}, ms = daemonRpcTimeoutMs()) {
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
      done({ ok: false, error: "timeout" });
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
      try {
        const msg = JSON.parse(buffer.slice(0, idx).trim());
        done(msg.error ? { ok: false, error: msg.error } : { ok: true, result: msg.result });
      } catch (error) {
        done({ ok: false, error: error instanceof Error ? error.message : String(error) });
      }
    });
    socket.once("error", (error) => {
      done({ ok: false, error: error.message });
    });
    socket.once("close", () => {
      done({ ok: false, error: "closed" });
    });
  });
}

const hookBase = process.env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim() ?? "";
const hookToken = process.env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim() ?? "";
add("openclaw_hook_base", Boolean(hookBase), hookBase ? "configured" : "missing");
add("openclaw_hook_token", Boolean(hookToken), hookToken ? "configured" : "missing");

const useDaemon = process.env.ZENLINK_MCP_USE_DAEMON?.trim();
const daemonRequired = useDaemon === "1" || String(useDaemon).toLowerCase() === "true";
add("daemon_mode_declared", daemonRequired, daemonRequired ? "enabled" : "not enabled");

const addrFile = process.env.ZENLINK_MCP_DAEMON_ADDR_FILE?.trim() ?? "";
if (daemonRequired) {
  add("daemon_addr_file_configured", Boolean(addrFile), addrFile ? addrFile : "missing");
  if (addrFile) {
    add("daemon_addr_file_exists", existsSync(addrFile), addrFile);
    if (existsSync(addrFile)) {
      const line = readFileSync(addrFile, "utf8").split(/\r?\n/).find((value) => value.trim()) ?? "";
      add("daemon_addr_file_nonempty", Boolean(line.trim()), line.trim() ? "has address" : "empty");
      const tokenFile = `${addrFile}.token`;
      add("daemon_token_file_exists", existsSync(tokenFile), tokenFile);
      const token = existsSync(tokenFile) ? readFileSync(tokenFile, "utf8").trim() : "";
      add("daemon_token_file_nonempty", Boolean(token), token ? "has token" : "empty or missing");
      if (line.trim() && token) {
        try {
          const { host, port } = parseAddrLine(line);
          const rpc = await invokeDaemonRpc(host, port, token, "zenlink_status");
          const status = rpc.ok ? parseToolTextJson(rpc.result) : null;
          add(
            "daemon_authenticated_rpc",
            rpc.ok,
            rpc.ok ? `${host}:${port}` : `${host}:${port} ${rpc.error}`,
          );
          if (rpc.ok) {
            add(
              "daemon_ws_online",
              !REQUIRE_WS_ONLINE || status?.online === true,
              status?.online === true ? "online" : "offline",
            );
          }
        } catch (error) {
          add(
            "daemon_authenticated_rpc",
            false,
            error instanceof Error ? error.message : String(error),
          );
        }
      }
    }
  }
}

const ok = REQUIRE_AUTO_WAKE || REQUIRE_WS_ONLINE
  ? checks.every((check) => check.ok)
  : true;
const report = {
  schema: "zenlink_openclaw_wake_verify/v1",
  ok,
  mode: REQUIRE_AUTO_WAKE || REQUIRE_WS_ONLINE ? "required" : "advisory",
  auto_wake_capable: Boolean(
    hookBase &&
      hookToken &&
      (!daemonRequired ||
        checks
          .filter((check) => check.id.startsWith("daemon_"))
          .every((check) => check.ok)),
  ),
  checks,
};

console.error(`ZENLINK_OPENCLAW_WAKE_VERIFY_JSON=${JSON.stringify(report)}`);
if (!ok) process.exit(1);
