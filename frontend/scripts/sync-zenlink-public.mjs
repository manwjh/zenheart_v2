/**
 * Copy embedded Zenlink client sources into public/zenlink for browsing.
 * Source directory resolution (first match wins):
 *   1. ZENLINK_PUBLIC_EMBED_SRC — absolute path to folder containing client.ts / client.js
 *   2. packages/zenlink-mcp/src/zenlink — vendored copy inside zenlink-mcp
 *   3. packages/zenlink/src — standalone zenlink package in this monorepo
 *   4. packages/zenlink-mcp/dist/zenlink — tsc output after `npm run build` in zenlink-mcp
 *
 * Publishes only versioned OpenClaw artifacts under https://SITE/zenlink/ (no stable-mirror filenames).
 * If `packages/zenlink-mcp-openclaw-{macos,linux}-v<semver>.tar.gz` exist (from `npm run pack` in zenlink-mcp), copies them.
 * If `packages/install-zenlink-mcp-openclaw-{macos,linux}-v<semver>.sh` exist (same pack), copies them beside the tarballs.
 * Optional `zenlink-mcp.tgz` is a maintainer-only `npm run pack:npx` output — not written here.
 */
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const packagesDir = path.resolve(frontendRoot, "../packages");
const destRoot = path.resolve(frontendRoot, "public/zenlink");
const distZenlinkRoot = path.resolve(frontendRoot, "dist/zenlink");

/** Resolve folder whose contents are copied to public/zenlink/src (expects client.ts or client.js). */
async function resolveZenlinkEmbedRoot() {
  const fromEnv = process.env.ZENLINK_PUBLIC_EMBED_SRC?.trim();
  const candidates = [
    ...(fromEnv ? [path.resolve(fromEnv)] : []),
    path.join(packagesDir, "zenlink-mcp", "src", "zenlink"),
    path.join(packagesDir, "zenlink", "src"),
    path.join(packagesDir, "zenlink-mcp", "dist", "zenlink"),
  ];
  const seen = new Set();
  for (const dir of candidates) {
    const key = path.normalize(dir);
    if (seen.has(key)) continue;
    seen.add(key);
    try {
      const stat = await fs.stat(dir);
      if (!stat.isDirectory()) continue;
      const ts = path.join(dir, "client.ts");
      const js = path.join(dir, "client.js");
      try {
        await fs.stat(ts);
        return dir;
      } catch {
        /* skip */
      }
      try {
        await fs.stat(js);
        return dir;
      } catch {
        /* skip */
      }
    } catch {
      /* skip */
    }
  }
  throw new Error(
    [
      "Zenlink embed sources not found for public sync.",
      "Expected one of:",
      "  v2/packages/zenlink-mcp/src/zenlink  (embedded copy inside zenlink-mcp)",
      "  v2/packages/zenlink/src               (standalone zenlink package)",
      "  v2/packages/zenlink-mcp/dist/zenlink  (after npm run build in zenlink-mcp)",
      "Or set ZENLINK_PUBLIC_EMBED_SRC to the directory that contains client.ts (or client.js).",
    ].join("\n")
  );
}

async function readZenlinkSdkVersion(zenlinkRoot) {
  for (const name of ["sdk-version.ts", "sdk-version.js"]) {
    const p = path.join(zenlinkRoot, name);
    try {
      const raw = await fs.readFile(p, "utf8");
      const m = raw.match(/ZENLINK_SDK_VERSION\s*=\s*"([^"]+)"/);
      if (m?.[1]) return m[1];
    } catch {
      /* try next */
    }
  }
  return "unknown";
}

async function copyDir(src, dest) {
  await fs.mkdir(dest, { recursive: true });
  const entries = await fs.readdir(src, { withFileTypes: true });
  for (const e of entries) {
    const s = path.join(src, e.name);
    const d = path.join(dest, e.name);
    if (e.isDirectory()) await copyDir(s, d);
    else await fs.copyFile(s, d);
  }
}

async function main() {
  const zenlinkRoot = await resolveZenlinkEmbedRoot();
  console.log(`sync-zenlink-public: using embed root ${zenlinkRoot}`);

  await fs.rm(distZenlinkRoot, { recursive: true, force: true });
  await fs.rm(destRoot, { recursive: true, force: true });
  await fs.mkdir(destRoot, { recursive: true });
  await copyDir(zenlinkRoot, path.join(destRoot, "src"));
  const sdkReadme = path.join(zenlinkRoot, "README.md");
  try {
    await fs.copyFile(sdkReadme, path.join(destRoot, "README.md"));
  } catch {
    await fs.writeFile(
      path.join(destRoot, "README.md"),
      "# Embedded client\n\nTypeScript under `src/`; version in `src/sdk-version.ts`.\n",
      "utf8"
    );
  }

  const zenlinkSdkVersion = await readZenlinkSdkVersion(zenlinkRoot);

  const mcpPkgRaw = await fs.readFile(
    path.join(packagesDir, "zenlink-mcp", "package.json"),
    "utf8"
  );
  const mcpPkg = JSON.parse(mcpPkgRaw);
  const openclawMacosTar = `zenlink-mcp-openclaw-macos-v${mcpPkg.version}.tar.gz`;
  const openclawLinuxTar = `zenlink-mcp-openclaw-linux-v${mcpPkg.version}.tar.gz`;
  async function syncOpenclawTarball(versionedName, label) {
    const src = path.join(packagesDir, versionedName);
    try {
      await fs.stat(src);
      await fs.copyFile(src, path.join(destRoot, versionedName));
      console.log(`synced OpenClaw tarball (${label}) -> public/zenlink/${versionedName}`);
      return true;
    } catch {
      return false;
    }
  }

  const macosTarOk = await syncOpenclawTarball(openclawMacosTar, "openclaw-macos");
  const linuxTarOk = await syncOpenclawTarball(openclawLinuxTar, "openclaw-linux");

  const installMacosName = `install-zenlink-mcp-openclaw-macos-v${mcpPkg.version}.sh`;
  const installLinuxName = `install-zenlink-mcp-openclaw-linux-v${mcpPkg.version}.sh`;
  async function syncSelfExtractingInstaller(filename, label) {
    const src = path.join(packagesDir, filename);
    try {
      await fs.stat(src);
      await fs.copyFile(src, path.join(destRoot, filename));
      console.log(`synced self-extracting installer (${label}) -> public/zenlink/${filename}`);
      return true;
    } catch {
      return false;
    }
  }
  const installMacosSynced = await syncSelfExtractingInstaller(
    installMacosName,
    "openclaw-macos"
  );
  const installLinuxSynced = await syncSelfExtractingInstaller(
    installLinuxName,
    "openclaw-linux"
  );

  if (!macosTarOk || !linuxTarOk) {
    console.warn(
      "sync-zenlink-public: expected both OpenClaw tarballs (macOS + linux); run `npm run pack` in packages/zenlink-mcp then re-sync."
    );
  }
  if (!installMacosSynced || !installLinuxSynced) {
    console.warn(
      "sync-zenlink-public: expected both install-zenlink-mcp-openclaw-*.sh; run `npm run pack` in packages/zenlink-mcp then re-sync."
    );
  }

  const bundlesComplete =
    macosTarOk && linuxTarOk && installMacosSynced && installLinuxSynced;

  const manifest = {
    generated_at: new Date().toISOString(),
    openclaw_bundles: {
      "openclaw-macos": {
        tarball: openclawMacosTar,
        tarball_present: macosTarOk,
        installer: installMacosName,
        installer_present: installMacosSynced,
      },
      "openclaw-linux": {
        tarball: openclawLinuxTar,
        tarball_present: linuxTarOk,
        installer: installLinuxName,
        installer_present: installLinuxSynced,
      },
    },
    openclaw_bundles_complete: bundlesComplete,
    versions: {
      zenlink_mcp: mcpPkg.version,
      zenlink_sdk: zenlinkSdkVersion,
    },
  };
  await fs.writeFile(
    path.join(destRoot, "release-manifest.json"),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8"
  );
  console.log("wrote release manifest -> public/zenlink/release-manifest.json");

  console.log("synced zenlink -> public/zenlink (+ release-manifest.json)");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
