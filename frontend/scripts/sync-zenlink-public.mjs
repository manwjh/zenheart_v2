/**
 * Delegates to zenheart-agent/zenlink-mcp/scripts/sync-openclaw-site-bundle.mjs (single source of truth).
 * Clears v2/frontend/dist/zenlink via ZENLINK_FRONTEND_ROOT when bundle runs.
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const destRoot = path.join(frontendRoot, "public", "zenlink");
const syncScript = path.resolve(
  frontendRoot,
  "..",
  "..",
  "zenheart-agent",
  "zenlink-mcp",
  "scripts",
  "sync-openclaw-site-bundle.mjs",
);

const env = {
  ...process.env,
  ZENLINK_FRONTEND_ROOT: frontendRoot,
};

const r = spawnSync(process.execPath, [syncScript, destRoot], {
  stdio: "inherit",
  env,
  shell: false,
});

process.exit(r.status === null ? 1 : r.status);
