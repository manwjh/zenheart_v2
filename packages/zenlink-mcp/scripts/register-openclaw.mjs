#!/usr/bin/env node
/**
 * Register zenlink-mcp in OpenClaw config (mcp.servers) via CLI.
 *
 * Requires: openclaw on PATH (or ZENLINK_MCP_OPENCLAW_COMMAND / OPENCLAW_BIN), built dist/cli.js, and registration-email credentials:
 *   ZENLINK_AGENT_ID + ZENLINK_TOKEN.
 *
 * Registration writes a plain stdio MCP spec; forwards **`ZENLINK_MCP_USE_DAEMON`** /
 * **`ZENLINK_MCP_DAEMON_ADDR_FILE`** (and related **`ZENLINK_MCP_DAEMON_*`**) when non-empty in the shell
 * (same rule as hook vars). They are **not** read back from `openclaw.json`. **Offline** **`install-openclaw.sh`**
 * defaults **`USE_DAEMON=1`** and a stable **`~/.openclaw/tmp/zenlink-mcp-daemon.addr`** when unset (opt out with
 * **`ZENLINK_MCP_USE_DAEMON=0`** in **`zenlink-deploy.env`** or **`ZENLINK_MCP_NO_DEFAULT_DAEMON=1`**). Re-run register after edits; by default it also starts the daemon and restarts the Gateway unless **`ZENLINK_MCP_INSTALL_AUTO_ACTIVATE=0`**.
 *
 * Usage:
 *   export ZENLINK_AGENT_ID=...
 *   export ZENLINK_TOKEN=...
 *   npm run openclaw:register
 *
 * **OpenClaw hooks (wake):**
 * - By default merges **`hooks.token`** (+ derived **`ZENLINK_MCP_OPENCLAW_HOOK_BASE`**) from **`openclaw.json`**.
 * - If **`hooks.token`** / hooks blocks are incomplete, prints **`openclaw hooks init`** and **`npm run setup:openclaw-hooks`**,
 *   then (**default**) patches **`openclaw.json`** to add **`hooks.*`** (+ random **`hooks.token`**) unless
 *   **`ZENLINK_MCP_AUTO_SETUP_HOOKS=0`**.
 * - Optional: **`ZENLINK_MCP_OPENCLAW_CREATE_CONFIG=1`** creates a minimal **`~/.openclaw/openclaw.json`** when missing.
 * - After hooks merge, defaults **`ZENLINK_MCP_OPENCLAW_WAKE_MODE=now`** when hook base+token are present and wake mode is unset in the shell.
 * - Hook delivery uses **`/hooks/agent`** so ZenHeart inbound starts an explicit OpenClaw agent turn instead of depending on an existing wake session.
 * - After **`openclaw mcp set`**, optionally runs hook smoke unless **`ZENLINK_MCP_HOOK_SMOKE=0`** or hook env missing.
 * - After the MCP spec is finalized, writes zenlink-openclaw-integration-summary.md as a sibling of zenlink-mcp/ (offline: extract root; dev from this repo: parent of the package dir, e.g. v2/packages/) with a paste-ready AGENTS.md routing block. Emitted on successful openclaw mcp set and when openclaw is missing (JSON paste path). Opt out: ZENLINK_MCP_WRITE_INTEGRATION_SUMMARY=0. Override path: ZENLINK_MCP_INTEGRATION_SUMMARY_PATH.
 * - On every exit, prints one stderr line **`ZENLINK_INSTALL_REPORT_JSON={...}`** (machine-readable checks for agents). Opt out: **`ZENLINK_MCP_INSTALL_REPORT=0`**.
 * - Streaming progress (stderr during the run): many **`ZENLINK_INSTALL_PHASE_JSON=`** lines (`zenlink_pipeline_phase/v1`, `pipeline:install`, **`component`** `shell`|`register`). Opt out **`ZENLINK_MCP_INSTALL_PHASE_EVENTS=0`**. Offline upgrade script emits **`ZENLINK_UPGRADE_PHASE_JSON=`** (`ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0`).
 * - Offline tarball ships **`pipeline-phase-emit.mjs`** at bundle root and under **`zenlink-mcp/scripts/`**.
 *
 * Skip hook merge entirely: **`ZENLINK_MCP_SKIP_OPENCLAW_HOOK_MERGE=1`**.
 *
 * Upgrade: run `npm run build` in zenlink-mcp (and peer zenlink), then re-run this script; restart OpenClaw.
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import net from "node:net";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY,
  defaultOpenClawJsonPath,
  hooksCompletenessIssues,
  mergeHookEnvFromOpenClawJsonIfPresent,
  probeOpenClawHookAgent,
  readModifyWriteOpenClawHooks,
  readOpenClawJson,
} from "./openclaw-json-helpers.mjs";
import { writeOpenClawIntegrationSummary } from "./openclaw-integration-summary.mjs";
import { printInstallReport } from "./install-report.mjs";
import { emitInstallPhase } from "./pipeline-phase-emit.mjs";
import { resolveNodeCommand } from "./node-command-helper.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const pkgRoot = dirname(scriptDir);
const cliJs = resolve(pkgRoot, "dist", "cli.js");

function autoSetupHooksEnabled() {
  const x = process.env.ZENLINK_MCP_AUTO_SETUP_HOOKS;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  return true;
}

function createMinimalConfigAllowed() {
  const x = process.env.ZENLINK_MCP_OPENCLAW_CREATE_CONFIG;
  return (
    x === "1" || String(x ?? "").toLowerCase() === "true"
  );
}

function resolveOpenClawCommand() {
  const explicit =
    process.env.ZENLINK_MCP_OPENCLAW_COMMAND?.trim() ||
    process.env.OPENCLAW_BIN?.trim();
  return explicit || "openclaw";
}

/**
 * When hook base + token are present in the payload env (from zenlink-deploy.env and/or
 * merge from openclaw.json), default **`ZENLINK_MCP_OPENCLAW_WAKE_MODE=now`** if the operator
 * did not set it in the shell — so `openclaw mcp set` persists wake behaviour (not only LONG_LIVED).
 */
function applyDefaultOpenClawWakeModeIfHooksPresent(env) {
  const fromShell = Object.prototype.hasOwnProperty.call(
    process.env,
    "ZENLINK_MCP_OPENCLAW_WAKE_MODE",
  );
  if (fromShell) {
    const v = process.env.ZENLINK_MCP_OPENCLAW_WAKE_MODE;
    if (v !== undefined && v !== "") {
      env["ZENLINK_MCP_OPENCLAW_WAKE_MODE"] = v;
    }
    return;
  }
  const base = String(env["ZENLINK_MCP_OPENCLAW_HOOK_BASE"] ?? "").trim();
  const tok = String(env["ZENLINK_MCP_OPENCLAW_HOOK_TOKEN"] ?? "").trim();
  if (base && tok) {
    env["ZENLINK_MCP_OPENCLAW_WAKE_MODE"] = "now";
  }
}

/**
 * Make wake routing explicit in the POST body. This removes dependence on Gateway
 * default-session dispatch for non-mention room traffic.
 */
function applyDefaultOpenClawSessionKeyIfHooksPresent(env) {
  const fromShell = Object.prototype.hasOwnProperty.call(
    process.env,
    "ZENLINK_MCP_OPENCLAW_SESSION_KEY",
  );
  if (fromShell) {
    const v = process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY;
    if (v !== undefined && v !== "") {
      env["ZENLINK_MCP_OPENCLAW_SESSION_KEY"] = v;
    }
    return;
  }
  const base = String(env["ZENLINK_MCP_OPENCLAW_HOOK_BASE"] ?? "").trim();
  const tok = String(env["ZENLINK_MCP_OPENCLAW_HOOK_TOKEN"] ?? "").trim();
  if (base && tok) {
    env["ZENLINK_MCP_OPENCLAW_SESSION_KEY"] = DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY;
    process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY = DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY;
  }
}

function integrationSummaryEnabled() {
  const x = process.env.ZENLINK_MCP_WRITE_INTEGRATION_SUMMARY;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  return true;
}

/**
 * @param {{ pkgRoot: string; nodeCommand: string; cliJs: string; mcpName: string; env: Record<string, string> }} opts
 * @returns {{ skipped?: boolean, ok: boolean, path: string | null, version?: string, error?: string }}
 */
function tryWriteIntegrationSummary(opts) {
  if (!integrationSummaryEnabled()) {
    return { skipped: true, ok: true, path: null };
  }
  try {
    const { outPath, version } = writeOpenClawIntegrationSummary(opts);
    console.error(
      `note: wrote OpenClaw integration summary (${version}): ${outPath}`,
    );
    return { ok: true, path: outPath, version };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("warning: could not write integration summary:", msg);
    return { ok: false, path: null, error: msg };
  }
}

/** @param {{ skipped?: boolean, ok: boolean, path: string | null, error?: string }} sum */
function integrationSummaryCheck(sum) {
  if (sum.skipped) {
    return { id: "integration_summary", ok: true, detail: "disabled_by_env" };
  }
  if (sum.ok && sum.path) {
    return { id: "integration_summary", ok: true, detail: sum.path };
  }
  return {
    id: "integration_summary",
    ok: false,
    detail: sum.error ?? "write_failed",
  };
}

/** @param {{ status: string, detail?: string, http_status?: number }} sr */
function hookAgentSmokeCheck(sr) {
  if (sr.status === "ok") {
    return {
      id: "hook_agent_smoke",
      ok: true,
      detail: `http_${sr.http_status ?? 0}`,
    };
  }
  if (sr.status === "skipped") {
    return {
      id: "hook_agent_smoke",
      ok: true,
      detail: sr.detail ?? "skipped",
    };
  }
  if (sr.status === "failed") {
    return {
      id: "hook_agent_smoke",
      ok: false,
      detail: `http_${sr.http_status ?? 0}:${sr.detail ?? ""}`,
    };
  }
  return {
    id: "hook_agent_smoke",
    ok: false,
    detail: sr.detail ?? "probe_error",
  };
}

function hookSmokeDesired() {
  const x = process.env.ZENLINK_MCP_HOOK_SMOKE;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  if (x === "1" || String(x ?? "").toLowerCase() === "true") {
    return true;
  }
  return null;
}

function envTruthy(value) {
  const normalized = String(value ?? "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function postInstallActivationEnabled() {
  const x = process.env.ZENLINK_MCP_INSTALL_AUTO_ACTIVATE;
  return !(x === "0" || String(x ?? "").toLowerCase() === "false");
}

function parseDaemonAddrLine(line) {
  const trimmed = String(line ?? "").trim();
  const index = trimmed.lastIndexOf(":");
  if (index <= 0) {
    throw new Error(`invalid daemon addr line: ${trimmed}`);
  }
  const host = trimmed.slice(0, index).trim();
  const port = Number.parseInt(trimmed.slice(index + 1).trim(), 10);
  if (!host || !Number.isFinite(port) || port <= 0 || port > 65535) {
    throw new Error(`invalid daemon addr line: ${trimmed}`);
  }
  return { host, port };
}

function daemonDoctorTimeoutMs() {
  const raw = process.env.ZENLINK_MCP_DAEMON_DOCTOR_TIMEOUT_MS?.trim();
  if (!raw) return 5000;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("ZENLINK_MCP_DAEMON_DOCTOR_TIMEOUT_MS must be a positive number");
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

function invokeDaemonRpc(host, port, token, tool, args = {}, ms = daemonDoctorTimeoutMs()) {
  return new Promise((resolve) => {
    const socket = net.connect({ host, port });
    let buffer = "";
    let settled = false;
    let timer;
    const done = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      resolve(result);
    };
    timer = setTimeout(() => done({ ok: false, error: "daemon_rpc_timeout" }), ms);
    socket.setEncoding("utf8");
    socket.once("connect", () => {
      socket.write(JSON.stringify({ id: 1, token, tool, args }) + "\n");
    });
    socket.on("data", (chunk) => {
      buffer += chunk;
      const index = buffer.indexOf("\n");
      if (index < 0) return;
      try {
        const msg = JSON.parse(buffer.slice(0, index).trim());
        done(msg.error ? { ok: false, error: msg.error } : { ok: true, result: msg.result });
      } catch (error) {
        done({ ok: false, error: error instanceof Error ? error.message : String(error) });
      }
    });
    socket.once("error", (error) => done({ ok: false, error: error.message }));
    socket.once("close", () => done({ ok: false, error: "daemon_rpc_closed" }));
  });
}

function compactOpenClawPushEvidence(push) {
  if (!push || typeof push !== "object") {
    return null;
  }
  return {
    enabled: push.enabled ?? null,
    hook_base: push.hook_base ?? null,
    delivery_mode: push.delivery_mode ?? null,
    agent_id: push.agent_id ?? null,
    wake_mode: push.wake_mode ?? null,
    session_key: push.session_key ?? null,
    last_http_status: push.last_http_status ?? null,
    last_error: push.last_error ?? null,
    sent_total: push.sent_total ?? null,
    pending_wake_count: push.pending_wake_count ?? null,
    dropped_wake_count: push.dropped_wake_count ?? null,
  };
}

function daemonFileEvidence(env) {
  const addrFile = String(env.ZENLINK_MCP_DAEMON_ADDR_FILE ?? "").trim();
  return {
    addr_file: addrFile || null,
    token_file: addrFile ? `${addrFile}.token` : null,
    status_file: addrFile ? `${addrFile}.status.json` : null,
    log_file: addrFile ? `${addrFile}.log` : null,
  };
}

async function runPostInstallDoctorCheck(env, opts = {}) {
  const requireHookDelivery = opts.requireHookDelivery !== false;
  if (!requireHookDelivery) {
    return {
      id: "zenlink_doctor",
      ok: true,
      detail: "manual_only_no_hook_env",
      mode: "manual_only",
    };
  }
  if (!envTruthy(env.ZENLINK_MCP_USE_DAEMON)) {
    return {
      id: "zenlink_doctor",
      ok: true,
      detail: "skipped_daemon_disabled",
      mode: "manual_only",
    };
  }
  const addrFile = String(env.ZENLINK_MCP_DAEMON_ADDR_FILE ?? "").trim();
  if (!addrFile) {
    return {
      id: "zenlink_doctor",
      ok: false,
      detail: "daemon_addr_file_missing",
      addr_file: null,
    };
  }
  try {
    const addrLine = readFileSync(addrFile, "utf8").split(/\r?\n/).find((line) => line.trim()) ?? "";
    const { host, port } = parseDaemonAddrLine(addrLine);
    const token = readFileSync(`${addrFile}.token`, "utf8").trim();
    if (!token) {
      return { id: "zenlink_doctor", ok: false, detail: "daemon_token_empty" };
    }
    const rpc = await invokeDaemonRpc(host, port, token, "zenlink_doctor", {});
    if (!rpc.ok) {
      return { id: "zenlink_doctor", ok: false, detail: String(rpc.error ?? "rpc_failed") };
    }
    const report = parseToolTextJson(rpc.result);
    const push = report?.status_evidence?.openclaw_push;
    const errorFindings = Array.isArray(report?.findings)
      ? report.findings.filter((finding) => finding?.severity === "error")
      : [];
    const failedFindingIds = Array.isArray(report?.findings)
      ? report.findings
          .filter((finding) => finding?.ok === false || finding?.severity === "error")
          .map((finding) => finding?.id)
          .filter(Boolean)
      : [];
    const sessionKeyOk = push?.session_key === DEFAULT_ZENLINK_OPENCLAW_SESSION_KEY;
    const deliveryOk = push?.delivery_mode === "agent";
    const pushEnabled = push?.enabled === true;
    const ok = report?.ok === true && sessionKeyOk && deliveryOk && pushEnabled && errorFindings.length === 0;
    const openclawPush = compactOpenClawPushEvidence(push);
    const detail = ok
      ? "ok"
      : JSON.stringify({
          report_ok: report?.ok,
          session_key: push?.session_key ?? null,
          delivery_mode: push?.delivery_mode ?? null,
          push_enabled: push?.enabled ?? null,
          failed_finding_ids: failedFindingIds,
          error_finding_ids: errorFindings.map((finding) => finding.id).filter(Boolean),
          openclaw_push: openclawPush,
        });
    return {
      id: "zenlink_doctor",
      ok,
      detail,
      failed_finding_ids: failedFindingIds,
      openclaw_push: openclawPush,
      agent_next_action: report?.agent_next_action ?? null,
      addr_file: addrFile,
      token_file: `${addrFile}.token`,
    };
  } catch (error) {
    return {
      id: "zenlink_doctor",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
      addr_file: addrFile,
      token_file: `${addrFile}.token`,
    };
  }
}

/**
 * @param {{ pkgRoot: string; nodeCommand: string; openClawCommand: string; env: Record<string, string> }} opts
 * @returns {Array<{ id: string, ok: boolean, detail?: string }>}
 */
function runPostInstallActivation(opts) {
  const { pkgRoot, nodeCommand, openClawCommand, env } = opts;
  if (!postInstallActivationEnabled()) {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "post_install_activation_skipped",
      detail: "ZENLINK_MCP_INSTALL_AUTO_ACTIVATE=0",
    });
    return [
      {
        id: "post_install_activation",
        ok: true,
        detail: "skipped_by_env",
      },
    ];
  }

  const checks = [];
  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "post_install_activation_enter",
  });

  if (envTruthy(env.ZENLINK_MCP_USE_DAEMON)) {
    const supervisor = resolve(scriptDir, "openclaw-zenlink-daemon.mjs");
    const files = daemonFileEvidence(env);
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "daemon_stop_enter",
      detail: files.addr_file ? `addr_file=${files.addr_file}` : "addr_file_missing",
    });
    const stopResult = spawnSync(nodeCommand, [supervisor, "stop", "--require-dead"], {
      stdio: "inherit",
      env: { ...process.env, ...env },
    });
    if (stopResult.error || (stopResult.status ?? 0) !== 0) {
      const detail = stopResult.error
        ? String(stopResult.error)
        : `exit_${stopResult.status ?? 1}`;
      emitInstallPhase({
        pkgRoot,
        component: "register",
        phase: "daemon_stop_failed",
        detail: JSON.stringify({ reason: detail, ...files }),
      });
      checks.push({
        id: "daemon_stopped_before_start",
        ok: false,
        detail: JSON.stringify({ reason: detail, ...files }),
        ...files,
      });
      return checks;
    }
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "daemon_stop_ok",
    });
    checks.push({ id: "daemon_stopped_before_start", ok: true, ...files });
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "daemon_start_enter",
    });
    const result = spawnSync(nodeCommand, [supervisor, "start"], {
      stdio: "inherit",
      env: { ...process.env, ...env },
    });
    if (result.error || (result.status ?? 1) !== 0) {
      const detail = result.error
        ? String(result.error)
        : `exit_${result.status ?? 1}`;
      emitInstallPhase({
        pkgRoot,
        component: "register",
        phase: "daemon_start_failed",
        detail: JSON.stringify({ reason: detail, ...files }),
      });
      checks.push({
        id: "daemon_started",
        ok: false,
        detail: JSON.stringify({ reason: detail, ...files }),
        ...files,
      });
    } else {
      emitInstallPhase({
        pkgRoot,
        component: "register",
        phase: "daemon_start_ok",
      });
      checks.push({ id: "daemon_started", ok: true, ...files });
    }
  } else {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "daemon_start_skipped",
      detail: "ZENLINK_MCP_USE_DAEMON disabled",
    });
    checks.push({ id: "daemon_started", ok: true, detail: "daemon_disabled" });
  }

  if (process.env.ZENLINK_MCP_INSTALL_SKIP_GATEWAY_RESTART === "1") {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "gateway_restart_skipped",
      detail: "ZENLINK_MCP_INSTALL_SKIP_GATEWAY_RESTART=1",
    });
    checks.push({ id: "gateway_restarted", ok: true, detail: "skipped_by_env" });
    return checks;
  }

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "gateway_restart_enter",
  });
  const restart = spawnSync(openClawCommand, ["gateway", "restart"], {
    stdio: "inherit",
  });
  if (restart.error || (restart.status ?? 1) !== 0) {
    const detail = restart.error
      ? String(restart.error)
      : `exit_${restart.status ?? 1}`;
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "gateway_restart_failed",
      detail,
    });
    checks.push({ id: "gateway_restarted", ok: false, detail });
  } else {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "gateway_restart_ok",
    });
    checks.push({ id: "gateway_restarted", ok: true });
  }

  return checks;
}

function printHooksIncompleteHint(note) {
  console.error("");
  console.error(
    "OpenClaw Gateway hooks section is missing or incomplete (/hooks/agent env merge).",
  );
  if (note) console.error(note);
  console.error("");
  console.error(
    "Recommended (official scaffolding): openclaw hooks init",
  );
  console.error(
    "This kit adds hooks locally: npm run setup:openclaw-hooks",
  );
  console.error("");
}

function isENOENTReadFailure(merged) {
  if (merged.reason !== "read_failed" || merged.error === undefined) {
    return false;
  }
  return /ENOENT|no such file|cannot find/i.test(merged.error);
}

/**
 * Applies automatic hooks setup + merges hook **`env`**; returns merge result (**`skipped`** forwarded).
 *
 * @param {Record<string, string>} env
 */
function finalizeOpenClawHooksForRegister(env) {
  let merged = mergeHookEnvFromOpenClawJsonIfPresent(env);
  const ocPath = defaultOpenClawJsonPath();

  if (merged.skipped) {
    return merged;
  }

  const auto = autoSetupHooksEnabled();

  if (!auto) {
    if (merged.ok !== true && merged.reason === "no_token") {
      printHooksIncompleteHint(
        `hooks.token absent in ${ocPath}; merge skipped.`,
      );
    } else if (merged.ok !== true && merged.reason === "read_failed") {
      printHooksIncompleteHint(
        `cannot read OpenClaw config ${ocPath}: ${merged.error ?? ""}`,
      );
    }

    try {
      if (merged.ok === true && existsSync(ocPath)) {
        const cfg = readOpenClawJson(ocPath);
        const issues = hooksCompletenessIssues(cfg);
        if (issues.length > 0) {
          console.error(
            `warning: hooks check on ${ocPath}: ${issues.join("; ")}`,
          );
          printHooksIncompleteHint(undefined);
        }
      }
    } catch {
      /* ignore advisory read failures */
    }
    return merged;
  }

  if (merged.ok === true && existsSync(ocPath)) {
    try {
      const cfg = readOpenClawJson(ocPath);
      const issues = hooksCompletenessIssues(cfg);
      if (issues.length === 0) {
        console.error(`note: merged OpenClaw hooks into MCP env (${ocPath})`);
        return merged;
      }
      console.error(
        `warning: incomplete hooks (${issues.join("; ")}) — patching ${ocPath}`,
      );
      const rw = readModifyWriteOpenClawHooks(ocPath, {
        rotateToken: false,
        dryRun: false,
        allowCreate: false,
      });
      if (!rw.ok) {
        console.error("error: could not persist hooks fixes:", rw.reason);
        return merged;
      }
      merged = mergeHookEnvFromOpenClawJsonIfPresent(env);
      if (merged.ok === true) {
        console.error(`note: merged OpenClaw hooks into MCP env (${ocPath})`);
      }
      return merged;
    } catch (e) {
      console.error(
        "warning: hooks completeness check failed:",
        e instanceof Error ? e.message : e,
      );
      return merged;
    }
  }

  if (
    merged.reason === "read_failed" &&
    isENOENTReadFailure(merged) &&
    createMinimalConfigAllowed()
  ) {
    console.error(
      `note: creating minimal OpenClaw config with hooks at ${ocPath} (ZENLINK_MCP_OPENCLAW_CREATE_CONFIG=1)`,
    );
    const rw = readModifyWriteOpenClawHooks(ocPath, {
      rotateToken: false,
      dryRun: false,
      allowCreate: true,
    });
    if (!rw.ok) {
      printHooksIncompleteHint(
        `cannot create hooks in ${ocPath}: ${rw.reason} ${rw.error ?? ""}`,
      );
      mergeHookEnvFromOpenClawJsonIfPresent(env);
      return merged;
    }
    merged = mergeHookEnvFromOpenClawJsonIfPresent(env);
    if (merged.ok === true) {
      console.error(`note: merged OpenClaw hooks into MCP env (${ocPath})`);
    }
    return merged;
  }

  if (
    merged.reason === "read_failed" &&
    isENOENTReadFailure(merged) &&
    !createMinimalConfigAllowed()
  ) {
    printHooksIncompleteHint(
      `no openclaw.json at ${ocPath}. Set ZENLINK_MCP_OPENCLAW_CREATE_CONFIG=1 to generate a minimal file, or install OpenClaw and run:\n  openclaw hooks init`,
    );
    mergeHookEnvFromOpenClawJsonIfPresent(env);
    return merged;
  }

  if (merged.reason === "read_failed" && merged.ok !== true) {
    console.error(`error: cannot read OpenClaw config (${ocPath})`);
    console.error(merged.error ?? "");
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "cannot read OpenClaw config",
        checks: [
          { id: "cli_js_built", ok: true },
          { id: "agent_credentials", ok: true },
          {
            id: "openclaw_config_readable",
            ok: false,
            detail: String(merged.error ?? "read_failed"),
          },
        ],
      },
      1,
    );
    process.exit(1);
    return merged;
  }

  if (merged.reason === "no_token") {
    printHooksIncompleteHint(
      `auto-generating hooks.token in ${ocPath}`,
    );
    const rw = readModifyWriteOpenClawHooks(ocPath, {
      rotateToken: false,
      dryRun: false,
      allowCreate: false,
    });
    if (!rw.ok) {
      console.error(`error: could not persist hooks (${rw.reason})`);
      printInstallReport(
        pkgRoot,
        {
          ok: false,
          message: "could not persist hooks",
          checks: [
            { id: "cli_js_built", ok: true },
            { id: "agent_credentials", ok: true },
            {
              id: "openclaw_hooks_persist",
              ok: false,
              detail: String(rw.reason),
            },
          ],
        },
        1,
      );
      process.exit(1);
      return merged;
    }
    merged = mergeHookEnvFromOpenClawJsonIfPresent(env);
    if (merged.ok === true && merged.path) {
      console.error(
        `note: merged OpenClaw hooks into MCP env (${merged.path})`,
      );
    }
    return merged;
  }

  if (merged.ok !== true) {
    printHooksIncompleteHint(undefined);
    console.error(
      "warning: hook-related MCP env vars may be missing until hooks are configured.",
    );
  }

  return merged;
}

/**
 * Default: smoke **`POST /hooks/agent`** when **`ZENLINK_MCP_HOOK_SMOKE`** unset — only if **`HOOK_*`** present.
 *
 * @returns {Promise<{ status: string, detail?: string, http_status?: number }>}
 */
async function runHookSmokeIfConfigured(env) {
  const base = env.ZENLINK_MCP_OPENCLAW_HOOK_BASE ?? "";
  const tok = env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN ?? "";
  if (!base.trim() || !tok.trim()) {
    return { status: "skipped", detail: "no_hook_base_or_token" };
  }
  console.error("");
  console.error(`note: probing OpenClaw hook agent endpoint …`);
  try {
    const r = await probeOpenClawHookAgent(base.trim(), tok.trim());
    if (r.ok) {
      console.error(
        `note: hooks agent probe OK (${r.status}) ${JSON.stringify(r.url)}`,
      );
      return { status: "ok", http_status: r.status, detail: String(r.url) };
    }
    console.error(
      `warning: hooks agent probe non-OK: ${r.status} ${r.statusText} ${JSON.stringify(r.url)}`,
    );
    if (r.bodyPreview) {
      console.error(`warning: response body preview: ${r.bodyPreview}`);
    }
    return {
      status: "failed",
      http_status: r.status,
      detail: r.statusText,
    };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("");
    console.error(
      `warning: hooks agent probe failed (${msg}). Restart the Gateway after changing hooks.json,`,
    );
    console.error(
      "        or probe manually:",
    );
    console.error(
      `curl -sS -X POST ${JSON.stringify(`${base.trim().replace(/\/$/, "")}/agent`)} ` +
        `-H \"Authorization: Bearer <hooks.token>\" -H Content-Type:\\ application/json`,
    );
    console.error(
      `-d '{\"message\":\"ZenHeart probe: call zenlink_doctor\",\"agentId\":\"main\",\"wakeMode\":\"now\",\"deliver\":\"none\",\"sessionKey\":\"hook:zenheart-main\"}'`,
    );
    return { status: "error", detail: msg };
  }
}

async function main() {
  const baseOk = [
    { id: "cli_js_built", ok: true },
    { id: "agent_credentials", ok: true },
  ];

  if (!existsSync(cliJs)) {
    console.error("error: dist/cli.js not found — run: npm run build");
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "dist_missing",
    });
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "dist/cli.js missing",
        checks: [
          { id: "cli_js_built", ok: false, detail: "run npm run build" },
          { id: "agent_credentials", ok: false, detail: "not_checked" },
        ],
      },
      1,
    );
    return 1;
  }

  const agentId =
    process.env.ZENLINK_AGENT_ID ??
    process.env.ZENHEART_AGENT_ID ??
    process.env.ZENHEART_V2_AGENT_ID;
  const token =
    process.env.ZENLINK_TOKEN ??
    process.env.ZENHEART_TOKEN ??
    process.env.ZENHEART_V2_TOKEN;

  if (!agentId || !token) {
    console.error(
      "error: set ZENLINK_AGENT_ID and ZENLINK_TOKEN from the registration email",
    );
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "credentials_missing",
    });
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "missing agent credentials",
        checks: [
          { id: "cli_js_built", ok: true },
          {
            id: "agent_credentials",
            ok: false,
            detail:
              "ZENLINK_AGENT_ID and ZENLINK_TOKEN from the registration email are required",
          },
        ],
      },
      1,
    );
    return 1;
  }

  /** @type {Record<string, string>} */
  const env = { ZENLINK_AGENT_ID: agentId, ZENLINK_TOKEN: token };

  for (const k of [
    "ZENLINK_HOST",
    "ZENLINK_USE_TLS",
    "ZENLINK_MCP_WS_TIMEOUT_MS",
    "ZENLINK_MCP_USE_DAEMON",
    "ZENLINK_MCP_DAEMON_ADDR_FILE",
    "ZENLINK_MCP_DAEMON_INVOKE_TIMEOUT_MS",
    "ZENLINK_MCP_DAEMON_ADDR_IN_SYSTEM_TMP",
    "ZENLINK_MCP_LONG_LIVED",
    "ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS",
    "ZENLINK_MCP_INBOUND_QUEUE_MAX",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT",
    "ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS",
    "ZENLINK_MCP_OPENCLAW_HOOK_BASE",
    "ZENLINK_MCP_OPENCLAW_HOOK_TOKEN",
    "ZENLINK_MCP_OPENCLAW_WAKE_MODE",
    "ZENLINK_MCP_OPENCLAW_AGENT_ID",
    "ZENLINK_MCP_OPENCLAW_SESSION_KEY",
    "ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES",
    "ZENLINK_MCP_WAKE_SIGNALS",
    "ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS",
    "ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS",
    "ZENHEART_HOST",
    "ZENHEART_USE_TLS",
    "ZENHEART_V2_HOST",
    "ZENHEART_V2_USE_TLS",
  ]) {
    const v = process.env[k];
    if (v !== undefined && v !== "") {
      env[k] = v;
    }
  }

  finalizeOpenClawHooksForRegister(env);
  applyDefaultOpenClawWakeModeIfHooksPresent(env);
  applyDefaultOpenClawSessionKeyIfHooksPresent(env);

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "hooks_merge_passed",
    detail: `${Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim())}:${Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim())}`,
  });

  const pushOk =
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim()) &&
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim());
  console.error(
    `note: OpenClaw hook push (zenlink_status.openclaw_push): ${
      pushOk ? "enabled — base+token set in registration env" : "disabled — set hooks in openclaw.json and/or zenlink-deploy.env, then re-run"
    }`,
  );

  const nodeCommand = resolveNodeCommand();
  if (nodeCommand !== process.execPath) {
    console.error(`note: registering MCP command with Node from PATH: ${nodeCommand}`);
  } else {
    console.error(`note: registering MCP command with current Node: ${nodeCommand}`);
  }
  const openClawCommand = resolveOpenClawCommand();
  if (openClawCommand !== "openclaw") {
    console.error(`note: using OpenClaw CLI command: ${openClawCommand}`);
  }

  const spec = {
    command: nodeCommand,
    args: [cliJs],
    env,
  };

  const name = process.env.OPENCLAW_MCP_NAME ?? "zenheart";
  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "mcp_registration_profile",
    detail: `server=${name}`,
  });

  const payload = JSON.stringify(spec);

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "openclaw_cli_spawn",
    detail: `${openClawCommand} mcp set ${name}`,
  });

  const result = spawnSync(openClawCommand, ["mcp", "set", name, payload], {
    stdio: "inherit",
  });

  if (result.error) {
    if ("code" in result.error && result.error.code === "ENOENT") {
      emitInstallPhase({
        pkgRoot,
        component: "register",
        phase: "openclaw_cli_missing",
      });
      console.error(
        `error: OpenClaw CLI not found: ${openClawCommand}.\nSet ZENLINK_MCP_OPENCLAW_COMMAND or OPENCLAW_BIN, or put openclaw on PATH.\n\nPaste under mcp.servers in ~/.openclaw/openclaw.json:\n`,
      );
      const snippet = { mcp: { servers: { [name]: spec } } };
      console.log(JSON.stringify(snippet, null, 2));
      const sum = tryWriteIntegrationSummary({
        pkgRoot,
        nodeCommand,
        cliJs,
        mcpName: name,
        env,
      });
      printInstallReport(
        pkgRoot,
        {
          ok: false,
          message:
            "openclaw CLI missing — paste stdout JSON into openclaw.json mcp.servers",
          checks: [
            ...baseOk,
            {
              id: "openclaw_cli_on_path",
              ok: false,
              detail: `ENOENT:${openClawCommand}`,
            },
            {
              id: "mcp_servers_persisted",
              ok: false,
              detail: "skipped_openclaw_missing",
            },
            integrationSummaryCheck(sum),
          ],
          integration_summary_path: sum.path ?? null,
        },
        1,
      );
      return 1;
    }
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "openclaw_spawn_error",
      detail: String(result.error),
    });
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "failed to spawn openclaw",
        checks: [
          ...baseOk,
          {
            id: "openclaw_spawn",
            ok: false,
            detail: String(result.error),
          },
        ],
      },
      1,
    );
    return 1;
  }

  const st = result.status ?? 1;
  if (st !== 0) {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "openclaw_mcp_set_failed",
      detail: String(st),
    });
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "openclaw mcp set failed",
        checks: [
          ...baseOk,
          { id: "openclaw_cli_on_path", ok: true },
          {
            id: "mcp_servers_persisted",
            ok: false,
            detail: `openclaw_mcp_set_exit_${st}`,
          },
        ],
      },
      st,
    );
    return st;
  }

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "openclaw_mcp_set_ok",
  });

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "integration_summary_write",
    detail: integrationSummaryEnabled() ? "enabled" : "disabled_by_env",
  });

  const sum = tryWriteIntegrationSummary({
    pkgRoot,
    nodeCommand,
    cliJs,
    mcpName: name,
    env,
  });

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "integration_summary_result",
    detail: sum.skipped
      ? "skipped_by_env"
      : sum.ok && sum.path
        ? sum.path
        : sum.error ?? "write_failed",
  });

  /** Default smoke-on-success when **`ZENLINK_MCP_HOOK_SMOKE` unset.** */
  const smokeModeUnset =
    process.env.ZENLINK_MCP_HOOK_SMOKE === undefined;
  let shouldSmoke = smokeModeUnset;
  const m = hookSmokeDesired();
  if (m === true) shouldSmoke = true;
  if (m === false) shouldSmoke = false;

  const hasHookCred =
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim()) &&
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim());

  if (shouldSmoke && hasHookCred) {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "hook_smoke_start",
    });
  } else {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "hook_smoke_skipped",
      detail: !hasHookCred ? "no_hook_env" : "smoke_disabled_or_not_default",
    });
  }

  /** @type {{ id: string, ok: boolean, detail?: string }} */
  let smokeCheck;
  if (shouldSmoke && hasHookCred) {
    const sr = await runHookSmokeIfConfigured(env);
    smokeCheck = hookAgentSmokeCheck(sr);
  } else if (smokeModeUnset && !hasHookCred) {
    console.error("");
    console.error(
      "note: hook wake smoke skipped (no hook env merged — normal if hooks not configured)",
    );
    smokeCheck = {
      id: "hook_agent_smoke",
      ok: true,
      detail: "skipped_no_hook_env",
    };
  } else {
    smokeCheck = {
      id: "hook_agent_smoke",
      ok: true,
      detail: "skipped_hook_smoke_disabled",
    };
  }

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "hook_smoke_done",
    detail: smokeCheck.detail,
  });

  const activationChecks = runPostInstallActivation({
    pkgRoot,
    nodeCommand,
    openClawCommand,
    env,
  });
  let doctorCheck = { id: "zenlink_doctor", ok: true, detail: "skipped_activation_failed" };
  if (activationChecks.every((check) => check.ok)) {
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "zenlink_doctor_start",
    });
    doctorCheck = await runPostInstallDoctorCheck(env, {
      requireHookDelivery: hasHookCred,
    });
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "zenlink_doctor_done",
      detail: doctorCheck.detail,
    });
  }
  const activationOk =
    activationChecks.every((check) => check.ok) && doctorCheck.ok;

  emitInstallPhase({
    pkgRoot,
    component: "register",
    phase: "emitting_install_report_json",
  });

  printInstallReport(
    pkgRoot,
    {
      ok: activationOk,
      ...(activationOk
        ? {}
        : { message: "post-install activation or doctor check failed" }),
      checks: [
        ...baseOk,
        { id: "openclaw_cli_on_path", ok: true },
        { id: "mcp_servers_persisted", ok: true },
        integrationSummaryCheck(sum),
        smokeCheck,
        ...activationChecks,
        doctorCheck,
      ],
      integration_summary_path: sum.path ?? null,
    },
    activationOk ? 0 : 1,
  );

  return activationOk ? 0 : 1;
}

main()
  .then((code) => process.exit(typeof code === "number" ? code : 0))
  .catch((e) => {
    console.error(e);
    const msg = e instanceof Error ? e.message : String(e);
    emitInstallPhase({
      pkgRoot,
      component: "register",
      phase: "uncaught_exception",
      detail: msg,
    });
    printInstallReport(
      pkgRoot,
      {
        ok: false,
        message: "register-openclaw.mjs threw",
        checks: [
          {
            id: "register_uncaught_exception",
            ok: false,
            detail: msg,
          },
        ],
      },
      1,
    );
    process.exit(1);
  });
