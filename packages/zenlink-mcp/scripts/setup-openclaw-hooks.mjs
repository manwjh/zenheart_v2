#!/usr/bin/env node
/**
 * Enable OpenClaw Gateway HTTP hooks in openclaw.json and generate hooks.token (64 hex chars).
 *
 * Usage:
 *   npm run setup:openclaw-hooks
 *   npm run setup:openclaw-hooks -- --config /path/to/openclaw.json
 *   npm run setup:openclaw-hooks -- --rotate-token
 *
 * Requires: OPENCLAW_JSON or default ~/.openclaw/openclaw.json writable.
 */
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  defaultOpenClawJsonPath,
  openClawHookWakeUrl,
  readModifyWriteOpenClawHooks,
} from "./openclaw-json-helpers.mjs";

const scriptDir = dirname(fileURLToPath(import.meta.url));

function usage() {
  console.log(`usage: node ${resolve(scriptDir, "setup-openclaw-hooks.mjs")} [options]

Options:
  --config <path>   OpenClaw JSON (default: OPENCLAW_JSON or ~/.openclaw/openclaw.json)
  --rotate-token    Replace hooks.token even if already set
  --dry-run         Print actions only; do not write
  -h, --help        This help
`);
}

function parseArgs(argv) {
  let configPath = defaultOpenClawJsonPath();
  let rotateToken = false;
  let dryRun = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") {
      return { help: true };
    }
    if (a === "--rotate-token") {
      rotateToken = true;
      continue;
    }
    if (a === "--dry-run") {
      dryRun = true;
      continue;
    }
    if (a === "--config") {
      configPath = argv[++i];
      if (!configPath) {
        throw new Error("--config requires a path");
      }
      continue;
    }
    throw new Error(`unknown argument: ${a}`);
  }
  return { configPath, rotateToken, dryRun, help: false };
}

function main() {
  let opts;
  try {
    opts = parseArgs(process.argv.slice(2));
  } catch (e) {
    console.error(String(e.message));
    usage();
    process.exit(1);
  }
  if (opts.help) {
    usage();
    process.exit(0);
  }

  const { configPath, rotateToken, dryRun } = opts;

  const rw = readModifyWriteOpenClawHooks(configPath, {
    rotateToken,
    dryRun,
    allowCreate: false,
  });

  if (!rw.ok) {
    console.error(`error: ${rw.reason}`, rw.error ?? "");
    if (rw.reason === "missing_file") {
      console.error(
        "Create the file first, or install OpenClaw and run:\n  openclaw hooks init\n",
      );
    }
    process.exit(1);
  }

  const token =
    typeof rw.cfg.hooks?.token === "string" ? rw.cfg.hooks.token.trim() : "";
  const hookBase = rw.hookBase;
  const wakeUrl = openClawHookWakeUrl(hookBase);

  if (dryRun) {
    console.log("[dry-run] would write:", configPath);
    console.log("[dry-run] hooks.enabled=true hooks.path=", rw.cfg.hooks?.path);
    console.log(
      "[dry-run] hooks.token=",
      rw.rotated ? "(set/changed)" : "(unchanged)",
    );
    process.exit(0);
  }

  console.log(`wrote ${configPath}`);
  console.log("");
  console.log("Restart the OpenClaw Gateway so hooks.* takes effect.");
  console.log("`npm run openclaw:register` merges hook env from this file.");
  console.log("");
  console.log(`export ZENLINK_MCP_OPENCLAW_HOOK_BASE=${JSON.stringify(hookBase)}`);
  console.log(`export ZENLINK_MCP_OPENCLAW_HOOK_TOKEN=${JSON.stringify(token)}`);
  console.log("export ZENLINK_MCP_LONG_LIVED=1");
  console.log("");
  console.log("npm run openclaw:register");
  console.log("");
  console.log(`curl probe (wake): curl -sS -X POST ${JSON.stringify(wakeUrl)} ...`);
}

main();
