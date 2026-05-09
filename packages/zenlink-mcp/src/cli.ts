#!/usr/bin/env node
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { runDaemon } from "./daemon/daemon.js";
import { runStdioServer } from "./transport/server.js";
import {
  resolveZenlinkEnabledToolNames,
  resolveZenlinkMcpToolsetModeFromEnv,
} from "./tools/tool-permissions-map.js";

async function main(): Promise<void> {
  const arg = process.argv[2];
  if (arg === "--version" || arg === "version") {
    console.log(readPackageVersion());
    return;
  }
  if (arg === "smoke") {
    process.env.ZENLINK_AGENT_ID ??= "smoke-agent";
    process.env.ZENLINK_TOKEN ??= "smoke-token";
    const tools = resolveZenlinkEnabledToolNames(resolveZenlinkMcpToolsetModeFromEnv());
    console.log(`PASS: tools/list count ${tools.size}`);
    return;
  }
  if (arg === "health") {
    console.log(JSON.stringify({ ok: true, version: readPackageVersion() }));
    return;
  }
  if (arg === "--daemon" || arg === "daemon") {
    await runDaemon();
    return;
  }
  await runStdioServer();
}

function readPackageVersion(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  const pkgRoot = join(here, "..");
  const pkg = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8")) as {
    version?: string;
  };
  if (!pkg.version) throw new Error("package.json missing version");
  return pkg.version;
}

main().catch((error) => {
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  console.error(message);
  process.exit(1);
});
