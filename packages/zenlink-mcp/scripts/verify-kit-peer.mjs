#!/usr/bin/env node
/**
 * Monorepo sanity: zenlink-mcp embeds Zenlink at src/zenlink (no separate npm peer package).
 */
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const pkgRoot = dirname(root);
const markers = [
  join(pkgRoot, "src", "zenlink", "index.ts"),
  join(pkgRoot, "src", "zenlink", "sdk-version.ts"),
];

for (const p of markers) {
  if (!existsSync(p)) {
    console.error(`verify-kit-peer: missing embedded zenlink source: ${p}`);
    process.exit(1);
  }
}

console.log("verify-kit-peer: embedded src/zenlink present");
