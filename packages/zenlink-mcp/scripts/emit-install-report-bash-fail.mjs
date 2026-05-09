#!/usr/bin/env node
/**
 * Called from install-openclaw.sh when bash-level checks fail (before register-openclaw.mjs).
 * Usage: node emit-install-report-bash-fail.mjs <pkgRoot> <reason_id> [detail] [exit_code]
 */
import { emitInstallPhase } from "./pipeline-phase-emit.mjs";
import { printInstallReport } from "./install-report.mjs";

const pkgRoot = process.argv[2];
const reason = process.argv[3] ?? "bash_install_failed";
const detail = process.argv[4] ?? "";
const exitCode = parseInt(process.argv[5] ?? "1", 10);

if (!pkgRoot) {
  process.exit(2);
}

emitInstallPhase({
  pkgRoot,
  component: "shell",
  phase: `failed_${reason}`,
  detail: detail || undefined,
});

/** @type {Array<{ id: string; ok: boolean; detail?: string }>} */
const checks = [
  { id: "cli_js_built", ok: reason !== "missing_cli_js", detail: reason },
  { id: "node_modules_vendored", ok: reason !== "missing_node_modules", detail: reason },
  {
    id: "bash_preflight",
    ok: false,
    detail: detail ? `${reason}: ${detail}` : reason,
  },
];

printInstallReport(
  pkgRoot,
  {
    ok: false,
    message: `install-openclaw.sh (bash): ${reason}`,
    checks,
    integration_summary_path: null,
  },
  Number.isFinite(exitCode) ? exitCode : 1,
);
