#!/usr/bin/env node
/**
 * After build: ensure embedded zenlink SDK (dist/zenlink/index.js) exports symbols zenlink-mcp uses.
 * Run with cwd zenlink-mcp (or pass ZENLINK_MCP_ROOT).
 */
import { dirname, join } from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = process.env.ZENLINK_MCP_ROOT
  ? process.env.ZENLINK_MCP_ROOT
  : join(__dirname, "..");
process.chdir(root);

const sdkEntry = pathToFileURL(join(root, "dist", "zenlink", "index.js")).href;

let zl;
try {
  zl = await import(sdkEntry);
} catch (e) {
  console.error(
    "error: cannot load dist/zenlink/index.js — run npm run build in zenlink-mcp.",
  );
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
}

if (typeof zl.ackMsgboxGlobal !== "function") {
  console.error(
    "error: embedded zenlink SDK missing ackMsgboxGlobal — rebuild from clean dist/.",
  );
  process.exit(1);
}

const sdkVer =
  typeof zl.ZENLINK_SDK_VERSION === "string" ? zl.ZENLINK_SDK_VERSION : "?";
console.log(
  `embedded zenlink SDK OK (sdk ${sdkVer}, ackMsgboxGlobal present)`,
);
