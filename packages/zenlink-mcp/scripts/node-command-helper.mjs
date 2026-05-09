import { spawnSync } from "node:child_process";

function executableWorks(command) {
  const r = spawnSync(command, ["--version"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  return r.status === 0;
}

function pathNodeCommand() {
  if (process.platform === "win32") {
    return "";
  }
  const r = spawnSync("sh", ["-lc", "command -v node"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  if (r.status !== 0) {
    return "";
  }
  return String(r.stdout ?? "").trim().split("\n")[0] ?? "";
}

export function resolveNodeCommand() {
  const explicit = process.env.ZENLINK_MCP_NODE_COMMAND?.trim();
  if (explicit) {
    if (!executableWorks(explicit)) {
      throw new Error(
        `ZENLINK_MCP_NODE_COMMAND is not executable or cannot run --version: ${explicit}`,
      );
    }
    return explicit;
  }

  const fromPath = pathNodeCommand();
  if (fromPath && executableWorks(fromPath)) {
    return fromPath;
  }

  return process.execPath;
}
