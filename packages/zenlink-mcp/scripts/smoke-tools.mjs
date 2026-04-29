#!/usr/bin/env node
/**
 * Thin wrapper: runs the same check as **`dist/cli.js smoke`** (no OpenClaw MCP name required).
 * Requires built **`dist/`** (`npm run build` in zenlink-mcp).
 *
 * Prefer: **`npx zenlink-mcp smoke`** or **`node dist/cli.js smoke`**
 */
import { spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const cli = resolve(root, "..", "dist", "cli.js");
const r = spawnSync(process.execPath, [cli, "smoke"], {
  stdio: "inherit",
  env: process.env,
});
process.exit(typeof r.status === "number" ? r.status : 1);
