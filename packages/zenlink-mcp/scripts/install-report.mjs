/**
 * Machine-readable install / register outcome for agents (stderr, one line).
 * Parse lines starting with ZENLINK_INSTALL_REPORT_JSON=
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { defaultOpenClawJsonPath } from "./openclaw-json-helpers.mjs";

export const INSTALL_REPORT_SCHEMA = "zenlink_install_report/v1";
export const INSTALL_REPORT_PREFIX = "ZENLINK_INSTALL_REPORT_JSON=";

export function installReportEnabled() {
  const x = process.env.ZENLINK_MCP_INSTALL_REPORT;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  return true;
}

export function readPackageVersion(pkgRoot) {
  try {
    const pkg = JSON.parse(
      readFileSync(join(pkgRoot, "package.json"), "utf8"),
    );
    return String(pkg.version ?? "unknown");
  } catch {
    return "unknown";
  }
}

/**
 * @param {string} pkgRoot zenlink-mcp package root (directory with package.json)
 * @param {object} partial
 * @param {boolean} [partial.ok]
 * @param {Array<{ id: string, ok: boolean, detail?: string }>} [partial.checks]
 * @param {string} [partial.message]
 * @param {string | null} [partial.integration_summary_path]
 * @param {number} exitCode
 */
export function printInstallReport(pkgRoot, partial, exitCode) {
  if (!installReportEnabled()) {
    return;
  }
  const checks = partial.checks ?? [];
  const ok = partial.ok !== undefined ? partial.ok : exitCode === 0;
  /** @type {Record<string, unknown>} */
  const payload = {
    schema: INSTALL_REPORT_SCHEMA,
    ok,
    exit_code: exitCode,
    zenlink_mcp_version: readPackageVersion(pkgRoot),
    mcp_server_name: process.env.OPENCLAW_MCP_NAME ?? "zenheart",
    openclaw_config_path: defaultOpenClawJsonPath(),
    checks,
  };
  if (partial.message !== undefined) {
    payload.message = partial.message;
  }
  if (partial.integration_summary_path !== undefined) {
    payload.integration_summary_path = partial.integration_summary_path;
  }
  if (checks.length > 0) {
    payload.degraded = exitCode === 0 && checks.some((c) => !c.ok);
  }
  process.stderr.write(
    `${INSTALL_REPORT_PREFIX}${JSON.stringify(payload)}\n`,
  );
}
