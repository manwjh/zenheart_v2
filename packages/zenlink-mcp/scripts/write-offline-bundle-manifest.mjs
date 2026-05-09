#!/usr/bin/env node
/**
 * Emit zenlink-bundle.manifest.json for offline OpenClaw tarballs (pack-time only).
 * Usage: node scripts/write-offline-bundle-manifest.mjs --out <path> --bundle-id openclaw-macos --platform macos --version 0.13.23 [--launchd]
 */
import { writeFileSync } from "node:fs";

import { INSTALL_PHASE_PREFIX, UPGRADE_PHASE_PREFIX, PHASE_SCHEMA } from "./pipeline-phase-emit.mjs";
import { INSTALL_REPORT_PREFIX, INSTALL_REPORT_SCHEMA } from "./install-report.mjs";

function argValue(name) {
  const i = process.argv.indexOf(name);
  if (i === -1 || i + 1 >= process.argv.length) return null;
  return process.argv[i + 1];
}

const out = argValue("--out");
const bundleId = argValue("--bundle-id");
const platform = argValue("--platform");
const version = argValue("--version");
const hasLaunchd = process.argv.includes("--launchd");

if (!out || !bundleId || !platform || !version) {
  console.error(
    "usage: node write-offline-bundle-manifest.mjs --out <file> --bundle-id <id> --platform macos|linux --version <semver> [--launchd]",
  );
  process.exit(1);
}

const UPGRADE_REPORT_PREFIX = "ZENLINK_UPGRADE_REPORT_JSON=";
const UPGRADE_REPORT_SCHEMA = "zenlink_upgrade_report/v1";
const MANIFEST_SCHEMA = "zenlink_offline_bundle_manifest/v1";

/** @type {Record<string, unknown>} */
const manifest = {
  schema: MANIFEST_SCHEMA,
  bundle_id: bundleId,
  platform_target: platform,
  zenlink_mcp_version: version,
  minimum_node_major: 18,
  human_readme: "README-OFFLINE.txt",
  agent_playbook: "AGENT_PLAYBOOK.md",
  recommended_entrypoint: "self_extracting_installer",
  entrypoints: {
    self_extracting_installer: `install-zenlink-mcp-${bundleId}-v${version}.sh`,
    stable_upgrade: "upgrade-offline-install.sh <tarball>",
    manual_install_debug_only: "install-openclaw.sh",
  },
  post_install_required_checks: [
    "daemon_started",
    "gateway_restarted",
    "zenlink_doctor",
    "session_key_present_when_hooks_enabled",
  ],
  machine_contracts: {
    install_report: {
      stream: "stderr",
      line_prefix: INSTALL_REPORT_PREFIX.trimEnd(),
      schema: INSTALL_REPORT_SCHEMA,
      disable_env: "ZENLINK_MCP_INSTALL_REPORT=0",
    },
    upgrade_report: {
      stream: "stderr",
      line_prefix: UPGRADE_REPORT_PREFIX.trimEnd(),
      schema: UPGRADE_REPORT_SCHEMA,
      disable_env: "ZENLINK_MCP_UPGRADE_REPORT=0",
    },
    install_phase_stream: {
      stream: "stderr",
      line_prefix: INSTALL_PHASE_PREFIX.trimEnd(),
      schema: PHASE_SCHEMA,
      pipeline_values: ["install"],
      disable_env: "ZENLINK_MCP_INSTALL_PHASE_EVENTS=0",
    },
    upgrade_phase_stream: {
      stream: "stderr",
      line_prefix: UPGRADE_PHASE_PREFIX.trimEnd(),
      schema: PHASE_SCHEMA,
      pipeline_values: ["upgrade"],
      disable_env: "ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0",
    },
  },
  artifacts_relative: [
    "zenlink-mcp/package.json",
    "zenlink-mcp/dist/cli.js",
    "zenlink-mcp/node_modules",
    "zenlink-mcp/scripts/register-openclaw.mjs",
    "zenlink-mcp/scripts/install-report.mjs",
    "zenlink-mcp/scripts/emit-install-report-bash-fail.mjs",
    "zenlink-mcp/scripts/pipeline-phase-emit.mjs",
    "pipeline-phase-emit.mjs",
    "install-openclaw.sh",
    "upgrade-offline-install.sh",
    "zenlink-deploy.env.example",
    "zenlink-bundle.manifest.json",
    "AGENT_PLAYBOOK.md",
    "README-OFFLINE.txt",
  ],
  agent_flow: {
    credentials_file: "zenlink-deploy.env",
    credentials_template: "zenlink-deploy.env.example",
    install_script: "install-openclaw.sh",
    upgrade_script: "upgrade-offline-install.sh",
    self_extracting_installer: `install-zenlink-mcp-${bundleId}-v${version}.sh`,
    preferred_install_command: `bash install-zenlink-mcp-${bundleId}-v${version}.sh`,
    fallback_upgrade_command: "bash upgrade-offline-install.sh <tarball>",
    integration_summary_glob: "zenlink-openclaw-integration-summary.md",
    post_register_activation: "default_auto",
    post_register_activation_opt_out:
      "ZENLINK_MCP_INSTALL_AUTO_ACTIVATE=0",
  },
};

if (hasLaunchd) {
  manifest.launchd_example_plist = "launchd-zenlink-mcp-daemon.example.plist";
  manifest.artifacts_relative.push("launchd-zenlink-mcp-daemon.example.plist");
}

writeFileSync(out, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
