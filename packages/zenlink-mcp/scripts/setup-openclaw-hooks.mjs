#!/usr/bin/env node
/**
 * Ensure ~/.openclaw/openclaw.json has hooks.enabled + hooks.path + hooks.token.
 *
 * Usage:
 *   npm run setup:openclaw-hooks
 *   npm run setup:openclaw-hooks -- --dry-run
 *   npm run setup:openclaw-hooks -- --rotate-token
 *
 * Env:
 *   ZENLINK_MCP_OPENCLAW_CREATE_CONFIG=1  create minimal JSON when missing (default: must exist)
 */
import {
  defaultOpenClawJsonPath,
  hooksCompletenessIssues,
  readModifyWriteOpenClawHooks,
} from "./openclaw-json-helpers.mjs";

const rotateToken = process.argv.includes("--rotate-token");
const dryRun = process.argv.includes("--dry-run");
const allowCreate =
  process.env.ZENLINK_MCP_OPENCLAW_CREATE_CONFIG === "1" ||
  String(process.env.ZENLINK_MCP_OPENCLAW_CREATE_CONFIG ?? "").toLowerCase() === "true";

const jsonPath = defaultOpenClawJsonPath();
const result = readModifyWriteOpenClawHooks(jsonPath, {
  rotateToken,
  dryRun,
  allowCreate,
});

if (!result.ok) {
  console.error(`error: ${result.reason}${result.error ? `: ${result.error}` : ""}`);
  console.error(`path: ${jsonPath}`);
  if (result.reason === "missing_file") {
    console.error("hint: export ZENLINK_MCP_OPENCLAW_CREATE_CONFIG=1 to create a minimal openclaw.json");
  }
  process.exit(1);
}

const issues = hooksCompletenessIssues(result.cfg);
if (issues.length > 0 && dryRun) {
  console.error("warning (dry-run): hooks completeness:", issues.join("; "));
}

console.log(`ok: ${dryRun ? "dry-run " : ""}hooks ready`);
console.log(`path: ${jsonPath}`);
console.log(`hook_base: ${result.hookBase}`);
console.log(`token_rotated_or_generated: ${result.rotated}`);
console.log(`default_session_key: ${result.cfg.hooks?.defaultSessionKey ?? "(none)"}`);
console.log("next: add ZENLINK_MCP_OPENCLAW_HOOK_BASE + TOKEN to zenlink-deploy.env if unset, then bash install-openclaw.sh");
console.log("next: openclaw gateway restart");
