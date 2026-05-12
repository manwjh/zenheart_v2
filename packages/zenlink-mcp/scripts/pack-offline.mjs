#!/usr/bin/env node
/**
 * Offline OpenClaw bundle pack — single entry for maintainer tooling (agent-first tarball contract).
 * Env / argv:
 *   ZENLINK_MCP_OFFLINE_TARGETS  comma macos,linux (default both)
 *   ZENLINK_MCP_OFFLINE_TARGET   single target when argv[2] custom out path is set
 *   argv[2]                      optional exact output .tar.gz path
 */
import { spawnSync } from "node:child_process";
import {
  appendFileSync,
  chmodSync,
  cpSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkgRoot = dirname(__dirname);
const packagesDir = dirname(pkgRoot);
const scriptsDir = __dirname;

/** Literal ${HOME} for README lines (shell placeholder for unpacker). */
const HOME_REF = "${HOME}";

function die(msg, code = 1) {
  console.error(msg);
  process.exit(code);
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", shell: false, ...opts });
  if (r.status !== 0) {
    die(`${cmd} ${args.join(" ")} failed (exit ${r.status ?? r.signal})`);
  }
}

function parseTargets() {
  const customOut = process.argv[2]?.trim() ?? "";
  if (customOut) {
    const t = process.env.ZENLINK_MCP_OFFLINE_TARGET || "macos";
    if (t !== "macos" && t !== "linux") {
      die(`error: ZENLINK_MCP_OFFLINE_TARGET must be macos or linux (got: ${t})`);
    }
    return { targets: [t], customOut };
  }
  const raw = (process.env.ZENLINK_MCP_OFFLINE_TARGETS || "macos,linux").replace(/\s/g, "");
  const parts = raw.split(",").map((s) => s.trim()).filter(Boolean);
  const targets = [];
  for (const x of parts) {
    if (x === "macos" || x === "linux") targets.push(x);
    else die(`error: unknown target in ZENLINK_MCP_OFFLINE_TARGETS: ${x} (use macos or linux)`);
  }
  if (targets.length === 0) die("error: ZENLINK_MCP_OFFLINE_TARGETS is empty");
  return { targets, customOut: "" };
}

const ZENLINK_DEPLOY_ENV_EXAMPLE = `# Copy to zenlink-deploy.env (same folder as install-openclaw.sh). install-openclaw.sh loads it automatically.
ZENLINK_AGENT_ID=
ZENLINK_TOKEN=

# Optional: OpenClaw hook delivery (set both hook lines or omit both — required for zenlink_status.openclaw_push.enabled)
# Base URL for hooks directory (zenlink-mcp posts to /hooks/agent).
ZENLINK_MCP_OPENCLAW_HOOK_BASE=http://127.0.0.1:18789/hooks
ZENLINK_MCP_OPENCLAW_HOOK_TOKEN=
# When BASE+TOKEN are set, install/register default wakeMode to "now" unless you override below.
ZENLINK_MCP_OPENCLAW_WAKE_MODE=now
# Request-level session targeting for /hooks/agent. The installer defaults this
# to hook:zenheart-main when BASE+TOKEN are set; uncomment to override.
# ZENLINK_MCP_OPENCLAW_SESSION_KEY=hook:zenheart-main

# Daemon forwarding (defaults applied by install-openclaw.sh when lines are omitted — still set explicitly if you prefer)
ZENLINK_MCP_USE_DAEMON=1
ZENLINK_MCP_DAEMON_ADDR_FILE=$HOME/.openclaw/tmp/zenlink-mcp-daemon.addr

# Typical extras (uncomment if needed):
# ZENLINK_MCP_LONG_LIVED=1
# ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES=message,msgbox_notify,social_notify
# ZENLINK_MCP_WAKE_SIGNALS=room.message,room.message_notify,msgbox.notify,room.dissolved
# ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS=2000   # one hook turn per room line (message + notify preview); 0=disable
# ZENLINK_MCP_UPLOAD_IMAGE_FS=1
# ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS=/tmp
`;

function writeBundleScripts(topDir) {
  writeFileSync(join(topDir, "zenlink-deploy.env.example"), ZENLINK_DEPLOY_ENV_EXAMPLE);
  cpSync(join(scriptsDir, "offline-embed", "install-openclaw.sh"), join(topDir, "install-openclaw.sh"));
  cpSync(join(scriptsDir, "offline-embed", "upgrade-offline-install.sh"), join(topDir, "upgrade-offline-install.sh"));
  chmodSync(join(topDir, "install-openclaw.sh"), 0o755);
  chmodSync(join(topDir, "upgrade-offline-install.sh"), 0o755);
}

function writeReadmeOffline(target, version, outPath) {
  const top = `zenlink-mcp-openclaw-${target}-v${version}`;
  const selfInstaller = `install-${top}.sh`;
  const bundleId = `openclaw-${target}`;
  let titleOs = "";
  let contentsExtra = "";
  let supervisorHint = "";
  if (target === "macos") {
    titleOs = "OpenClaw (macOS)";
    contentsExtra = `  launchd-zenlink-mcp-daemon.example.plist   macOS launchd: use absolute paths (see comments; avoid versioned /tmp extract paths)
`;
    supervisorHint =
      "You must keep zenlink-mcp --daemon running when USE_DAEMON=1: use openclaw-zenlink-daemon.mjs (in zenlink-mcp/scripts/) or launchd.";
  } else {
    titleOs = "OpenClaw (Linux)";
    supervisorHint =
      "You must keep zenlink-mcp --daemon running when USE_DAEMON=1: use openclaw-zenlink-daemon.mjs (foreground), systemd, or supervisord — see your distro docs.";
  }
  const subtitle = `ZenHeart zenlink-mcp — offline bundle for ${titleOs}`;
  const underline = "=".repeat(subtitle.length);

  const body = `${subtitle}
${underline}

Bundle id: ${bundleId}  (target: ${titleOs}; Node 18+)

Contents:
  ${selfInstaller}   Self-extracting one-command installer (distributed beside this tarball)
  zenlink-bundle.manifest.json   Machine-readable contract: artifacts, report prefixes, schemas (read first for autonomous installs)
  AGENT_PLAYBOOK.md              Concise playbook for LLM-driven install / upgrade / verification
  pipeline-phase-emit.mjs        Streams ZENLINK_*_PHASE_JSON lines (install + upgrade); also under zenlink-mcp/scripts/
  zenlink-mcp/              MCP package: dist/, node_modules/ (production), package.json, scripts/
  install-openclaw.sh       Registers stdio MCP (openclaw mcp set; persists hook + daemon forwarding env)
  upgrade-offline-install.sh   Optional: install/upgrade into a fixed directory (~/.openclaw/zenlink-mcp/current)
  zenlink-deploy.env.example   Credentials + hooks (agent: inject via env or write file before install-openclaw.sh)
${contentsExtra}
Requirements on the target machine:
  - Node.js 18+
  - openclaw CLI available as "openclaw" (for install-openclaw.sh)
  - No public npm registry required for running MCP (dependencies are bundled under zenlink-mcp/node_modules).

Recommended fixed path (supervisor / upgrades):
  bash ${selfInstaller}
  # Self-extracting installer: extracts this bundle to a temp dir, then runs upgrade-offline-install.sh.
  # If you only have the tarball:
  bash upgrade-offline-install.sh ${top}.tar.gz
  # Default: upgrade script runs install-openclaw.sh, starts daemon, restarts Gateway, and runs doctor.

Agent install sequence (preferred):
  1. If you were given ${selfInstaller}, run: bash ${selfInstaller}
  2. Parse stderr for ZENLINK_UPGRADE_REPORT_JSON=... and nested install report lines.
  3. Verify daemon_started, gateway_restarted, and zenlink_doctor checks.

Fallback manual sequence (tarball only):
  1. tar xzf ${top}.tar.gz && cd ${top}
  2. Read zenlink-bundle.manifest.json (contract)
  3. Ensure zenlink-deploy.env or exported ZENLINK_* (see AGENT_PLAYBOOK.md)
  4. Prefer: bash upgrade-offline-install.sh ../${top}.tar.gz
     Manual/debug fallback: bash install-openclaw.sh
  5. Parse stderr for ZENLINK_INSTALL_REPORT_JSON=... (exit code must match exit_code; checks[])
  6. Verify daemon_started and gateway_restarted checks, then verify zenlink_status in OpenClaw.

Autonomous agents: follow AGENT_PLAYBOOK.md; use manifest machine_contracts for exact stderr prefixes.

Install / upgrade JSON lines:
  ZENLINK_INSTALL_REPORT_JSON=  (register-openclaw / install-openclaw; disable ZENLINK_MCP_INSTALL_REPORT=0)
  ZENLINK_UPGRADE_REPORT_JSON=  (upgrade-offline-install.sh; disable ZENLINK_MCP_UPGRADE_REPORT=0)
  ZENLINK_INSTALL_PHASE_JSON=   (many lines during install-openclaw.sh + register-openclaw.mjs; zenlink_pipeline_phase/v1; disable ZENLINK_MCP_INSTALL_PHASE_EVENTS=0)
  ZENLINK_UPGRADE_PHASE_JSON=   (during upgrade-offline-install.sh; disable ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0)

install-openclaw.sh auto-loads, if present: zenlink-deploy.env then .env (KEY=value exports).
It defaults ZENLINK_MCP_USE_DAEMON=1 and ZENLINK_MCP_DAEMON_ADDR_FILE=${HOME_REF}/.openclaw/tmp/zenlink-mcp-daemon.addr when unset (written into openclaw.json). Opt out: ZENLINK_MCP_USE_DAEMON=0 in zenlink-deploy.env, or export ZENLINK_MCP_NO_DEFAULT_DAEMON=1 for a single run.

After changing persisted hook/daemon env, re-run install-openclaw.sh so ~/.openclaw/openclaw.json mcp.servers.*.env updates — that is what OpenClaw MCP workers read.

${supervisorHint}

OpenClaw hooks: Gateway must expose POST /hooks/agent with hooks.token matching ZENLINK_MCP_OPENCLAW_HOOK_TOKEN.
register-openclaw.mjs merges hooks.token from openclaw.json when unset; ZENLINK_MCP_OPENCLAW_WAKE_MODE defaults to "now" when base+token are present, and ZENLINK_MCP_OPENCLAW_SESSION_KEY defaults to hook:zenheart-main for stable agent hook routing.
If hooks are missing: openclaw hooks init (then re-run install-openclaw.sh).

Minimal shell exports (no zenlink-deploy.env file):
  export ZENLINK_AGENT_ID=... ZENLINK_TOKEN=...
  export ZENLINK_MCP_OPENCLAW_HOOK_BASE=... ZENLINK_MCP_OPENCLAW_HOOK_TOKEN=...
  bash install-openclaw.sh

Manual MCP command (no OpenClaw CLI): point mcp.servers at:
  command: node
  args: [ "<absolute-path>/zenlink-mcp/dist/cli.js" ]
  env: { ZENLINK_AGENT_ID, ZENLINK_TOKEN, ... }

Node command used by install/register:
  - Set ZENLINK_MCP_NODE_COMMAND to force a specific Node binary.
  - Otherwise register-openclaw.mjs prefers "command -v node" (stable Homebrew symlink such as /opt/homebrew/bin/node)
    before falling back to the current process executable.

Optional: global CLI from this folder (still offline if node_modules is present):
  npm install -g ./zenlink-mcp --offline --no-audit
`;
  writeFileSync(outPath, body);
}

function writeSelfExtractingInstaller(target, version, tarPath) {
  const topName = `zenlink-mcp-openclaw-${target}-v${version}`;
  const tarName = `${topName}.tar.gz`;
  const outPath = join(packagesDir, `install-${topName}.sh`);
  const payload = readFileSync(tarPath)
    .toString("base64")
    .match(/.{1,76}/g)
    ?.join("\n") ?? "";
  const script = `#!/usr/bin/env bash
# Self-extracting ZenHeart zenlink-mcp OpenClaw installer.
# Generated by scripts/pack-offline.mjs. Do not edit by hand.
set -euo pipefail

TOP_NAME=${JSON.stringify(topName)}
TAR_NAME=${JSON.stringify(tarName)}

decode_base64() {
  if base64 -d </dev/null >/dev/null 2>&1; then
    base64 -d
  elif base64 -D </dev/null >/dev/null 2>&1; then
    base64 -D
  else
    echo "error: base64 decoder not found; need GNU 'base64 -d' or BSD/macOS 'base64 -D'" >&2
    return 1
  fi
}

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

SELF_PATH="$0"
TAR_PATH="$TMP_DIR/$TAR_NAME"

echo "[zenlink-self-install] extracting embedded bundle to $TAR_PATH" >&2
awk 'found { print } /^__ZENLINK_TARBALL_BASE64_BELOW__$/ { found=1; next }' "$SELF_PATH" | decode_base64 > "$TAR_PATH"

EXTRACT_DIR="$TMP_DIR/extract"
mkdir -p "$EXTRACT_DIR"
tar xzf "$TAR_PATH" -C "$EXTRACT_DIR"

BUNDLE_DIR="$EXTRACT_DIR/$TOP_NAME"
if [[ ! -d "$BUNDLE_DIR" ]]; then
  echo "error: extracted bundle directory not found: $BUNDLE_DIR" >&2
  exit 1
fi

echo "[zenlink-self-install] running upgrade-offline-install.sh (auto activation enabled by default)" >&2
cd "$BUNDLE_DIR"
exec bash "./upgrade-offline-install.sh" "$TAR_PATH"

__ZENLINK_TARBALL_BASE64_BELOW__
`;
  writeFileSync(outPath, script, "utf8");
  appendFileSync(outPath, `${payload}\n`, "utf8");
  chmodSync(outPath, 0o755);
  console.log(`Wrote ${outPath} (${statSync(outPath).size} bytes)`);
}

const SCRIPT_COPY_NAMES = [
  "register-openclaw.mjs",
  "openclaw-json-helpers.mjs",
  "openclaw-zenlink-daemon.mjs",
  "node-command-helper.mjs",
  "openclaw-integration-summary.mjs",
  "install-report.mjs",
  "emit-install-report-bash-fail.mjs",
  "pipeline-phase-emit.mjs",
];

const { targets, customOut } = parseTargets();

const pkg = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf8"));
const version = pkg.version;
if (!version) die("package.json missing version");

console.log("==> npm ci (needs registry on this build machine)");
run("npm", ["ci"], { cwd: pkgRoot });
console.log("==> npm run build");
run("npm", ["run", "build"], { cwd: pkgRoot });

const shared = mkdtempSync(join(tmpdir(), "zenlink-mcp-pack-"));
try {
  const dest = join(shared, "zenlink-mcp");
  mkdirSync(join(dest, "scripts"), { recursive: true });

  cpSync(join(pkgRoot, "package.json"), join(dest, "package.json"));
  cpSync(join(pkgRoot, "dist"), join(dest, "dist"), { recursive: true });
  cpSync(join(pkgRoot, "node_modules"), join(dest, "node_modules"), { recursive: true });

  console.log("==> production node_modules only (staged copy; your repo tree is unchanged)");
  run("npm", ["prune", "--omit=dev"], { cwd: dest });

  for (const name of SCRIPT_COPY_NAMES) {
    cpSync(join(scriptsDir, name), join(dest, "scripts", name));
  }

  for (const target of targets) {
    const topName = `zenlink-mcp-openclaw-${target}-v${version}`;
    const bundleTmp = mkdtempSync(join(tmpdir(), "zenlink-mcp-bundle-"));
    try {
      const topDir = join(bundleTmp, topName);
      mkdirSync(topDir, { recursive: true });
      cpSync(dest, join(topDir, "zenlink-mcp"), { recursive: true });

      if (target === "macos") {
        cpSync(
          join(scriptsDir, "launchd-zenlink-mcp-daemon.example.plist"),
          join(topDir, "launchd-zenlink-mcp-daemon.example.plist"),
        );
      }

      writeBundleScripts(topDir);
      writeReadmeOffline(target, version, join(topDir, "README-OFFLINE.txt"));

      const manifestArgs = [
        join(scriptsDir, "write-offline-bundle-manifest.mjs"),
        "--out",
        join(topDir, "zenlink-bundle.manifest.json"),
        "--bundle-id",
        `openclaw-${target}`,
        "--platform",
        target,
        "--version",
        version,
      ];
      if (target === "macos") manifestArgs.push("--launchd");
      run(process.execPath, manifestArgs);

      cpSync(join(pkgRoot, "packaging", "AGENT_PLAYBOOK.md"), join(topDir, "AGENT_PLAYBOOK.md"));
      cpSync(join(scriptsDir, "pipeline-phase-emit.mjs"), join(topDir, "pipeline-phase-emit.mjs"));

      const outFile = customOut || join(packagesDir, `${topName}.tar.gz`);
      mkdirSync(dirname(outFile), { recursive: true });
      run("tar", ["czf", outFile, topName], { cwd: bundleTmp });

      const st = statSync(outFile);
      console.log(`Wrote ${outFile} (${st.size} bytes)`);
      writeSelfExtractingInstaller(target, version, outFile);

      if (customOut) break;
    } finally {
      rmSync(bundleTmp, { recursive: true, force: true });
    }
  }
} finally {
  rmSync(shared, { recursive: true, force: true });
}
