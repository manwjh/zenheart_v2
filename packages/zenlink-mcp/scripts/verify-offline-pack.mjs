#!/usr/bin/env node
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const packagesDir = join(root, "..");
const pkg = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));

const targets = ["macos", "linux"];

function die(message) {
  console.error(`error: ${message}`);
  process.exit(1);
}

function assertFile(path, label) {
  try {
    const st = statSync(path);
    if (!st.isFile()) die(`${label} is not a file: ${path}`);
  } catch {
    die(`missing ${label}: ${path}`);
  }
}

function assertExecutable(path, label) {
  assertFile(path, label);
  const mode = statSync(path).mode;
  if ((mode & 0o111) === 0) {
    die(`${label} is not executable: ${path}`);
  }
}

function assertDir(path, label) {
  try {
    const st = statSync(path);
    if (!st.isDirectory()) die(`${label} is not a directory: ${path}`);
  } catch {
    die(`missing ${label}: ${path}`);
  }
}

function verifyTarget(target) {
  const bundleId = `openclaw-${target}`;
  const top = `zenlink-mcp-${bundleId}-v${pkg.version}`;
  const tarPath = join(packagesDir, `${top}.tar.gz`);
  const selfInstallerPath = join(packagesDir, `install-${top}.sh`);
  assertFile(tarPath, `${bundleId} tarball`);
  assertExecutable(selfInstallerPath, `${bundleId} self-extracting installer`);
  const selfInstaller = readFileSync(selfInstallerPath, "utf8");
  if (!selfInstaller.includes("__ZENLINK_TARBALL_BASE64_BELOW__")) {
    die(`${bundleId} self-extracting installer missing payload marker`);
  }
  if (!selfInstaller.includes(`TOP_NAME="${top}"`)) {
    die(`${bundleId} self-extracting installer top name mismatch`);
  }
  execFileSync("bash", ["-n", selfInstallerPath], { stdio: "pipe" });

  const work = mkdtempSync(join(tmpdir(), `zenlink-mcp-pack-${target}-`));
  try {
    execFileSync("tar", ["xzf", tarPath, "-C", work], { stdio: "pipe" });
    const bundleRoot = join(work, top);
    const mcpRoot = join(bundleRoot, "zenlink-mcp");

    assertFile(join(bundleRoot, "README-OFFLINE.txt"), "offline README");
    assertExecutable(join(bundleRoot, "install-openclaw.sh"), "installer");
    assertExecutable(join(bundleRoot, "upgrade-offline-install.sh"), "upgrader");
    assertFile(join(mcpRoot, "package.json"), "package manifest");
    assertFile(join(mcpRoot, "dist", "cli.js"), "compiled CLI");
    assertFile(
      join(mcpRoot, "scripts", "node-command-helper.mjs"),
      "Node command helper",
    );
    assertFile(
      join(mcpRoot, "scripts", "openclaw-integration-summary.mjs"),
      "OpenClaw integration summary writer",
    );
    assertFile(
      join(mcpRoot, "scripts", "install-report.mjs"),
      "install report (ZENLINK_INSTALL_REPORT_JSON)",
    );
    assertFile(
      join(mcpRoot, "scripts", "emit-install-report-bash-fail.mjs"),
      "bash-phase install failure reporter",
    );
    assertFile(
      join(mcpRoot, "scripts", "pipeline-phase-emit.mjs"),
      "pipeline phase streaming (zenlink-mcp/scripts)",
    );
    assertFile(join(bundleRoot, "pipeline-phase-emit.mjs"), "pipeline phase at bundle root");
    assertFile(join(bundleRoot, "zenlink-bundle.manifest.json"), "bundle manifest");
    assertFile(join(bundleRoot, "AGENT_PLAYBOOK.md"), "AGENT_PLAYBOOK.md");
    const manifest = JSON.parse(
      readFileSync(join(bundleRoot, "zenlink-bundle.manifest.json"), "utf8"),
    );
    if (manifest.schema !== "zenlink_offline_bundle_manifest/v1") {
      die(`${bundleId} manifest schema mismatch`);
    }
    if (manifest.bundle_id !== bundleId) {
      die(`${bundleId} manifest bundle_id mismatch`);
    }
    if (manifest.zenlink_mcp_version !== pkg.version) {
      die(`${bundleId} manifest version mismatch`);
    }
    if (manifest.recommended_entrypoint !== "self_extracting_installer") {
      die(`${bundleId} manifest recommended_entrypoint mismatch`);
    }
    if (manifest.entrypoints?.self_extracting_installer !== `install-${top}.sh`) {
      die(`${bundleId} manifest self installer entrypoint mismatch`);
    }
    for (const check of [
      "daemon_started",
      "gateway_restarted",
      "zenlink_doctor",
      "session_key_present_when_hooks_enabled",
    ]) {
      if (!manifest.post_install_required_checks?.includes(check)) {
        die(`${bundleId} manifest missing required check: ${check}`);
      }
    }
    for (const rel of manifest.artifacts_relative) {
      const p = join(bundleRoot, rel);
      try {
        statSync(p);
      } catch {
        die(`${bundleId} missing manifest artifact: ${rel}`);
      }
    }
    assertDir(join(mcpRoot, "node_modules"), "vendored node_modules");
    assertFile(
      join(mcpRoot, "node_modules", "@modelcontextprotocol", "sdk", "package.json"),
      "@modelcontextprotocol/sdk dependency",
    );
    assertFile(join(mcpRoot, "node_modules", "ws", "package.json"), "ws dependency");
    assertFile(join(mcpRoot, "node_modules", "zod", "package.json"), "zod dependency");

    const readme = readFileSync(join(bundleRoot, "README-OFFLINE.txt"), "utf8");
    if (!readme.includes(`Bundle id: ${bundleId}`)) {
      die(`${bundleId} README does not contain its bundle id`);
    }

    const launchdPath = join(bundleRoot, "launchd-zenlink-mcp-daemon.example.plist");
    if (target === "macos") {
      assertFile(launchdPath, "macOS launchd plist");
    } else {
      try {
        statSync(launchdPath);
        die("linux bundle must not include macOS launchd plist");
      } catch {
        // Expected.
      }
    }

    const versionOut = execFileSync(
      process.execPath,
      [join(mcpRoot, "dist", "cli.js"), "--version"],
      { cwd: mcpRoot, encoding: "utf8" },
    ).trim();
    if (versionOut !== pkg.version) {
      die(`${bundleId} CLI --version expected ${pkg.version}, got ${JSON.stringify(versionOut)}`);
    }

    console.log(`offline pack OK: ${tarPath}`);
  } finally {
    rmSync(work, { recursive: true, force: true });
  }
}

for (const target of targets) {
  verifyTarget(target);
}
