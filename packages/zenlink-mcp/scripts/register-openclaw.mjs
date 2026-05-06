#!/usr/bin/env node
/**
 * Register zenlink-mcp in OpenClaw config (mcp.servers) via CLI.
 *
 * Requires: openclaw on PATH, built dist/cli.js, and agent credentials:
 *   ZENLINK_AGENT_ID + ZENLINK_TOKEN, or ZENHEART_* / ZENHEART_V2_*.
 *
 * Registration writes a plain stdio MCP spec; forwards **`ZENLINK_MCP_USE_DAEMON`** /
 * **`ZENLINK_MCP_DAEMON_ADDR_FILE`** (and related **`ZENLINK_MCP_DAEMON_*`**) when non-empty in the shell
 * (same rule as hook vars). They are **not** read back from `openclaw.json`. **Offline** **`install-openclaw.sh`**
 * defaults **`USE_DAEMON=1`** and a stable **`~/.openclaw/tmp/zenlink-mcp-daemon.addr`** when unset (opt out with
 * **`ZENLINK_MCP_USE_DAEMON=0`** in **`zenlink-deploy.env`** or **`ZENLINK_MCP_NO_DEFAULT_DAEMON=1`**). Re-run register after edits (no automatic daemon start).
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
 * - After **`openclaw mcp set`**, optionally runs **`POST .../hooks/wake`** smoke unless **`ZENLINK_MCP_HOOK_SMOKE=0`** or hook env missing.
 *
 * Skip hook merge entirely: **`ZENLINK_MCP_SKIP_OPENCLAW_HOOK_MERGE=1`**.
 *
 * Upgrade: run `npm run build` in zenlink-mcp (and peer zenlink), then re-run this script; restart OpenClaw.
 */
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  defaultOpenClawJsonPath,
  hooksCompletenessIssues,
  mergeHookEnvFromOpenClawJsonIfPresent,
  probeOpenClawHookWake,
  readModifyWriteOpenClawHooks,
  readOpenClawJson,
} from "./openclaw-json-helpers.mjs";

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

function printHooksIncompleteHint(note) {
  console.error("");
  console.error(
    "OpenClaw Gateway hooks section is missing or incomplete (wake-related env merge).",
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
 * Default: smoke **`POST /hooks/wake`** when **`ZENLINK_MCP_HOOK_SMOKE`** unset — only if **`HOOK_*`** present.
 */
async function runHookSmokeIfConfigured(env) {
  const base = env.ZENLINK_MCP_OPENCLAW_HOOK_BASE ?? "";
  const tok = env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN ?? "";
  if (!base.trim() || !tok.trim()) {
    return;
  }
  console.error("");
  console.error(`note: probing OpenClaw hook wake endpoint …`);
  try {
    const r = await probeOpenClawHookWake(base.trim(), tok.trim());
    if (r.ok) {
      console.error(
        `note: hooks wake probe OK (${r.status}) ${JSON.stringify(r.url)}`,
      );
      return;
    }
    console.error(
      `warning: hooks wake probe non-OK: ${r.status} ${r.statusText} ${JSON.stringify(r.url)}`,
    );
    if (r.bodyPreview) {
      console.error(`warning: response body preview: ${r.bodyPreview}`);
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error("");
    console.error(
      `warning: hooks wake probe failed (${msg}). Restart the Gateway after changing hooks.json,`,
    );
    console.error(
      "        or probe manually:",
    );
    console.error(
      `curl -sS -X POST ${JSON.stringify(`${base.trim().replace(/\/$/, "")}/wake`)} ` +
        `-H \"Authorization: Bearer <hooks.token>\" -H Content-Type:\\ application/json`,
    );
    console.error(
      `-d '{\"text\":\"ZenHeart probe\",\"mode\":\"now\"}'`,
    );
  }
}

async function main() {
  if (!existsSync(cliJs)) {
    console.error("error: dist/cli.js not found — run: npm run build");
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
      "error: set ZENLINK_AGENT_ID and ZENLINK_TOKEN, or ZENHEART_* / ZENHEART_V2_*",
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
    "ZENLINK_MCP_PARTICIPANT_RULES",
    "ZENLINK_MCP_PARTICIPANT_RULES_FILE",
    "ZENLINK_MCP_PARTICIPANT_RULES_WRITE",
    "ZENLINK_MCP_OPENCLAW_HOOK_BASE",
    "ZENLINK_MCP_OPENCLAW_HOOK_TOKEN",
    "ZENLINK_MCP_OPENCLAW_WAKE_MODE",
    "ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES",
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

  const pushOk =
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim()) &&
    Boolean(env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim());
  console.error(
    `note: OpenClaw hook push (zenlink_status.openclaw_push): ${
      pushOk ? "enabled — base+token set in registration env" : "disabled — set hooks in openclaw.json and/or zenlink-deploy.env, then re-run"
    }`,
  );

  const spec = {
    command: process.execPath,
    args: [cliJs],
    env,
  };

  const name = process.env.OPENCLAW_MCP_NAME ?? "zenheart";
  const payload = JSON.stringify(spec);

  const result = spawnSync("openclaw", ["mcp", "set", name, payload], {
    stdio: "inherit",
  });

  if (result.error) {
    if ("code" in result.error && result.error.code === "ENOENT") {
      console.error(
        "error: openclaw not found in PATH.\n\nPaste under mcp.servers in ~/.openclaw/openclaw.json:\n",
      );
      const snippet = { mcp: { servers: { [name]: spec } } };
      console.log(JSON.stringify(snippet, null, 2));
      return 1;
    }
    console.error(result.error);
    return 1;
  }

  const st = result.status ?? 1;
  if (st !== 0) {
    return st;
  }

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
    await runHookSmokeIfConfigured(env);
  } else if (smokeModeUnset && !hasHookCred) {
    console.error("");
    console.error(
      "note: hook wake smoke skipped (no hook env merged — normal if hooks not configured)",
    );
  }

  return 0;
}

main()
  .then((code) => process.exit(typeof code === "number" ? code : 0))
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
