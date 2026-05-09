/**
 * Streaming phase markers during offline install / upgrade (stderr, one line each).
 *
 * Prefixes:
 *   ZENLINK_INSTALL_PHASE_JSON=
 *   ZENLINK_UPGRADE_PHASE_JSON=
 *
 * Opt out install (bash + register): ZENLINK_MCP_INSTALL_PHASE_EVENTS=0|false
 * Opt out upgrade script:           ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0|false
 *
 * CLI (from bash next to bundled install / upgrade scripts):
 *   node pipeline-phase-emit.mjs install <pkgRoot|-> <component> <phase> [detail...]
 *     pkgRoot "-" skips zenlink_mcp_version in payload.
 *
 *   node pipeline-phase-emit.mjs upgrade <script_dir|-> <phase> [detail...]
 *     Uses env ZENLINK_OFFLINE_BUNDLE_ID, ZENLINK_OFFLINE_MCP_VERSION when set (resolved by upgrade-offline-install.sh from bundle metadata).
 */
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

export const PHASE_SCHEMA = "zenlink_pipeline_phase/v1";
export const INSTALL_PHASE_PREFIX = "ZENLINK_INSTALL_PHASE_JSON=";
export const UPGRADE_PHASE_PREFIX = "ZENLINK_UPGRADE_PHASE_JSON=";

function installPhaseEventsEnabled() {
  const x = process.env.ZENLINK_MCP_INSTALL_PHASE_EVENTS;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  return true;
}

function upgradePhaseEventsEnabled() {
  const x = process.env.ZENLINK_MCP_UPGRADE_PHASE_EVENTS;
  if (x === "0" || String(x ?? "").toLowerCase() === "false") {
    return false;
  }
  return true;
}

function readVersion(pkgRoot) {
  if (!pkgRoot || pkgRoot === "-") {
    return undefined;
  }
  try {
    const pkg = JSON.parse(
      readFileSync(join(pkgRoot, "package.json"), "utf8"),
    );
    return String(pkg.version ?? undefined);
  } catch {
    return undefined;
  }
}

/**
 * @param {{
 *   pkgRoot: string,
 *   component: string,
 *   phase: string,
 *   detail?: string | null,
 * }} opts
 */
export function emitInstallPhase(opts) {
  if (!installPhaseEventsEnabled()) {
    return;
  }
  const { pkgRoot, component, phase, detail } = opts;
  /** @type {Record<string, unknown>} */
  const payload = {
    schema: PHASE_SCHEMA,
    pipeline: "install",
    epoch_ms: Date.now(),
    component,
    phase,
  };
  const ver = readVersion(pkgRoot === "-" ? undefined : pkgRoot);
  if (ver !== undefined) {
    payload.zenlink_mcp_version = ver;
  }
  if (detail !== undefined && detail !== null && String(detail) !== "") {
    payload.detail = String(detail);
  }
  process.stderr.write(`${INSTALL_PHASE_PREFIX}${JSON.stringify(payload)}\n`);
}

/**
 * @param {{
 *   scriptDir?: string,
 *   phase: string,
 *   detail?: string | null,
 * }} opts
 */
export function emitUpgradePhase(opts) {
  if (!upgradePhaseEventsEnabled()) {
    return;
  }
  const { scriptDir, phase, detail } = opts;
  /** @type {Record<string, unknown>} */
  const payload = {
    schema: PHASE_SCHEMA,
    pipeline: "upgrade",
    epoch_ms: Date.now(),
    bundle_id: process.env.ZENLINK_OFFLINE_BUNDLE_ID ?? undefined,
    zenlink_mcp_version: process.env.ZENLINK_OFFLINE_MCP_VERSION ?? undefined,
    phase,
  };
  if (scriptDir !== undefined && scriptDir !== "" && scriptDir !== "-") {
    payload.script_dir = String(scriptDir).replace(/\\/g, "/");
  }
  if (
    payload.bundle_id === undefined ||
    payload.bundle_id === ""
  ) {
    delete payload.bundle_id;
  }
  if (
    payload.zenlink_mcp_version === undefined ||
    payload.zenlink_mcp_version === ""
  ) {
    delete payload.zenlink_mcp_version;
  }
  if (
    detail !== undefined &&
    detail !== null &&
    String(detail) !== ""
  ) {
    payload.detail = String(detail);
  }
  process.stderr.write(`${UPGRADE_PHASE_PREFIX}${JSON.stringify(payload)}\n`);
}

function parseDirectCli() {
  const cmd = process.argv[2];
  if (!cmd) {
    process.exit(0);
  }
  const rest = process.argv.slice(3);
  if (cmd === "install") {
    const [pkgRoot = "-", component, phase, ...detailParts] = rest;
    if (!component || !phase) {
      console.error(
        "usage: node pipeline-phase-emit.mjs install <pkgRoot|-> <component> <phase> [detail...]",
      );
      process.exit(2);
    }
    const detail =
      detailParts.length > 0
        ? detailParts.join(" ").trim() || undefined
        : undefined;
    emitInstallPhase({ pkgRoot, component, phase, detail });
    process.exit(0);
  }
  if (cmd === "upgrade") {
    const [scriptDirArg = "-", phase, ...detailParts] = rest;
    if (!phase) {
      console.error(
        "usage: node pipeline-phase-emit.mjs upgrade <script_dir|-> <phase> [detail...]",
      );
      process.exit(2);
    }
    const detail =
      detailParts.length > 0
        ? detailParts.join(" ").trim() || undefined
        : undefined;
    emitUpgradePhase({
      scriptDir: scriptDirArg === "-" ? undefined : scriptDirArg,
      phase,
      detail,
    });
    process.exit(0);
  }
  console.error(
    "unknown subcommand:",
    cmd,
    "\n(use install or upgrade)",
  );
  process.exit(2);
}

function isExecutedDirectly() {
  try {
    return import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
  } catch {
    return false;
  }
}

/* Only invoke CLI when executed as primary module (never when imported). */
if (isExecutedDirectly()) {
  parseDirectCli();
}
