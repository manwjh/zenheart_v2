/**
 * Shared helpers for OpenClaw ~/.openclaw/openclaw.json (hooks + gateway URL).
 */

import { randomBytes } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

export function defaultOpenClawJsonPath() {
  const fromEnv =
    process.env.OPENCLAW_JSON ?? process.env.OPENCLAW_CONFIG_PATH ?? "";
  if (typeof fromEnv === "string" && fromEnv.trim() !== "") {
    return fromEnv.trim();
  }
  return join(homedir(), ".openclaw", "openclaw.json");
}

/**
 * Build `http(s)://host:port/path` hook base (`…/hooks`). Must match MCP `wake` POST base minus `/wake`.
 *
 * Prefer OpenClaw `gateway` fields when present; override with env when tuning without editing JSON:
 * `ZENLINK_MCP_GATEWAY_PORT`, `ZENLINK_MCP_GATEWAY_HOST`, `ZENLINK_MCP_GATEWAY_TLS=1`.
 */
export function deriveHookBaseFromOpenClaw(cfg) {
  const hooksPathRaw = cfg.hooks?.path ?? "/hooks";
  const normalized =
    typeof hooksPathRaw === "string" && hooksPathRaw.startsWith("/")
      ? hooksPathRaw
      : `/${String(hooksPathRaw)}`;
  const pathNoTrail = normalized.replace(/\/$/, "") || "/hooks";

  const portRaw =
    cfg.gateway?.port ??
    cfg.gateway?.listen?.port ??
    process.env.ZENLINK_MCP_GATEWAY_PORT;
  let port =
    typeof portRaw === "number" && Number.isFinite(portRaw)
      ? portRaw
      : Number(portRaw);
  if (!Number.isFinite(port) || port <= 0) {
    port = 18789;
  }

  const host =
    (typeof cfg.gateway?.host === "string" ? cfg.gateway.host : null) ??
    process.env.ZENLINK_MCP_GATEWAY_HOST ??
    "127.0.0.1";

  const useTls =
    cfg.gateway?.tls === true ||
    process.env.ZENLINK_MCP_GATEWAY_TLS === "1";
  const scheme = useTls ? "https" : "http";
  return `${scheme}://${host}:${port}${pathNoTrail}`;
}

export function readOpenClawJson(path) {
  return JSON.parse(readFileSync(path, "utf8"));
}

/**
 * Structured issues when hooks are missing or inconsistent (for UX messages).
 * @param {unknown} cfg
 * @returns {string[]}
 */
export function hooksCompletenessIssues(cfg) {
  const issues = [];
  if (!cfg || typeof cfg !== "object") {
    issues.push("config root invalid");
    return issues;
  }
  if (!cfg.hooks || typeof cfg.hooks !== "object") {
    issues.push("hooks section missing");
    return issues;
  }
  const h = cfg.hooks;
  if (h.enabled !== true) {
    issues.push('hooks.enabled is not true (Gateway may ignore hooks until enabled)');
  }
  const hp = h.path;
  if (
    hp !== undefined &&
    hp !== "" &&
    (typeof hp !== "string" || !hp.startsWith("/"))
  ) {
    issues.push('hooks.path should be absolute (e.g. "/hooks")');
  }
  const tok = typeof h.token === "string" ? h.token.trim() : "";
  if (!tok) {
    issues.push("hooks.token missing or empty");
  }
  return issues;
}

/**
 * Ensure **`hooks`** object enables Gateway HTTP hooks with default path + token when missing.
 * Does not write disk — used by **`register-openclaw`** and **`setup-openclaw-hooks`**.
 *
 * @param {Record<string, unknown>} cfg Root OpenClaw config object (mutated).
 * @param {{ rotateToken?: boolean }} [opts]
 */
export function applyDefaultOpenClawHooksToConfig(cfg, opts = {}) {
  const rotateToken = opts.rotateToken === true;
  if (!cfg.hooks || typeof cfg.hooks !== "object") {
    cfg.hooks = {};
  }
  /** @type {Record<string, unknown>} */
  const hooks = cfg.hooks;

  const hadToken =
    typeof hooks.token === "string" && hooks.token.trim().length > 0;

  hooks.enabled = true;
  if (hooks.path === undefined || hooks.path === "") {
    hooks.path = "/hooks";
  }

  if (rotateToken || !hadToken) {
    hooks.token = randomBytes(32).toString("hex");
  }
}

/**
 * Read **`openclaw.json`**, apply default **`hooks`**, optionally create parent dirs.file.
 *
 * **allowCreate=true** writes a minimal JSON when the path is missing (opt-in via env).
 *
 * @param {string} jsonPath
 * @param {{ rotateToken?: boolean, dryRun?: boolean, allowCreate?: boolean }} [opts]
 * @returns {{ ok: true, jsonPath: string, cfg: Record<string, unknown>, hookBase: string, rotated: boolean } | { ok: false, jsonPath: string, reason: string, error?: string }}
 */
export function readModifyWriteOpenClawHooks(jsonPath, opts = {}) {
  const rotateToken = opts.rotateToken === true;
  const dryRun = opts.dryRun === true;
  const allowCreate = opts.allowCreate === true;

  const exists = existsSync(jsonPath);
  if (!exists && !allowCreate) {
    return { ok: false, jsonPath, reason: "missing_file" };
  }

  /** @type {Record<string, unknown>} */
  let cfg;
  if (exists) {
    try {
      const raw = readFileSync(jsonPath, "utf8");
      cfg = JSON.parse(raw);
    } catch (e) {
      return {
        ok: false,
        jsonPath,
        reason: "read_parse_failed",
        error: e instanceof Error ? e.message : String(e),
      };
    }
  } else {
    mkdirSync(dirname(jsonPath), { recursive: true });
    cfg = {};
  }

  if (typeof cfg !== "object" || cfg === null) {
    return { ok: false, jsonPath, reason: "bad_root" };
  }

  const hadTokenBefore =
    typeof cfg.hooks?.token === "string" && cfg.hooks.token.trim().length > 0;

  applyDefaultOpenClawHooksToConfig(cfg, { rotateToken });
  const hookBase = deriveHookBaseFromOpenClaw(cfg);

  const rotated =
    rotateToken || !hadTokenBefore;

  if (dryRun) {
    return {
      ok: true,
      jsonPath,
      cfg,
      hookBase,
      rotated,
    };
  }

  const out = `${JSON.stringify(cfg, null, 2)}\n`;
  writeFileSync(jsonPath, out, "utf8");
  return { ok: true, jsonPath, cfg, hookBase, rotated };
}

/** Full **`POST`** URL for **`/hooks/wake`** ( **`hookBase`** is **`…/hooks`** without trailing slash ok). */
export function openClawHookWakeUrl(hookBase) {
  const b = String(hookBase).replace(/\/$/, "");
  return `${b}/wake`;
}

/**
 * **`POST`** wake probe toward OpenClaw Gateway (Node 18+ **`fetch`**).
 *
 * @param {string} hookBase Derived base like **`http://127.0.0.1:18789/hooks`**
 * @param {string} token Same as **`hooks.token`**
 */
export async function probeOpenClawHookWake(hookBase, token) {
  const url = openClawHookWakeUrl(hookBase);
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      text: "[ZenHeart register] hooks wake smoke probe",
      mode: "now",
    }),
  });
  const bodyPreview = await res.text();
  return {
    url,
    ok: res.ok,
    status: res.status,
    statusText: res.statusText,
    bodyPreview:
      bodyPreview.length > 500 ? `${bodyPreview.slice(0, 500)}…` : bodyPreview,
  };
}

/**
 * Merge **`hooks.token`** and derived **`ZENLINK_MCP_OPENCLAW_HOOK_BASE`** from OpenClaw
 * `openclaw.json` into MCP `env` when not already set (shell forwards win).
 *
 * Called automatically by **`register-openclaw.mjs`** so upgrades need not paste hook env manually.
 *
 * Skip with **`ZENLINK_MCP_SKIP_OPENCLAW_HOOK_MERGE=1`**. Omit merge when JSON is unreadable or
 * **`hooks.token`** is missing ( **`openclaw:register`** can auto-patch hooks; **`npm run setup:openclaw-hooks`** remains the explicit path).
 *
 * Legacy: **`ZENLINK_MCP_HOOKS_FROM_OPENCLAW_CONFIG=1`** is no longer required (merge is default).
 */
export function mergeHookEnvFromOpenClawJsonIfPresent(env) {
  const skip =
    process.env.ZENLINK_MCP_SKIP_OPENCLAW_HOOK_MERGE === "1" ||
    String(process.env.ZENLINK_MCP_SKIP_OPENCLAW_HOOK_MERGE ?? "").toLowerCase() === "true";

  if (skip) {
    return { ok: false, reason: "skipped", skipped: true };
  }

  const path = defaultOpenClawJsonPath();
  let cfg;
  try {
    cfg = readOpenClawJson(path);
  } catch (e) {
    return {
      ok: false,
      reason: "read_failed",
      path,
      error: e instanceof Error ? e.message : String(e),
    };
  }

  const token =
    typeof cfg.hooks?.token === "string" ? cfg.hooks.token.trim() : "";
  if (!token) {
    return { ok: false, reason: "no_token", path };
  }

  if (!env["ZENLINK_MCP_OPENCLAW_HOOK_TOKEN"]) {
    env["ZENLINK_MCP_OPENCLAW_HOOK_TOKEN"] = token;
  }
  if (!env["ZENLINK_MCP_OPENCLAW_HOOK_BASE"]) {
    env["ZENLINK_MCP_OPENCLAW_HOOK_BASE"] = deriveHookBaseFromOpenClaw(cfg);
  }

  const longFromShell = Object.prototype.hasOwnProperty.call(
    process.env,
    "ZENLINK_MCP_LONG_LIVED",
  );
  if (
    !longFromShell &&
    !Object.prototype.hasOwnProperty.call(env, "ZENLINK_MCP_LONG_LIVED")
  ) {
    env["ZENLINK_MCP_LONG_LIVED"] = "1";
  }

  return { ok: true, path };
}

/** @deprecated Use {@link mergeHookEnvFromOpenClawJsonIfPresent}; same behavior now. */
export function applyHookEnvFromOpenClawJson(env) {
  return mergeHookEnvFromOpenClawJsonIfPresent(env);
}
