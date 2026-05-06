/**
 * Copy embedded client sources into public/zenlink for browsing.
 * Builds npm pack tarball (npx-dist) and copies stable zenlink-mcp.tgz for /zenlink/ downloads.
 * If `packages/zenlink-mcp-offline-v<semver>.tar.gz` exists (from `npm run pack` in zenlink-mcp), copies offline bundles too.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const zenlinkRoot = path.resolve(frontendRoot, "../packages/zenlink-mcp/src/zenlink");
const destRoot = path.resolve(frontendRoot, "public/zenlink");
const distZenlinkRoot = path.resolve(frontendRoot, "dist/zenlink");

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

  const zenlinkMcpRoot = path.resolve(frontendRoot, "../packages/zenlink-mcp");
  const npxDir = path.join(zenlinkMcpRoot, "npx-dist");
  try {
    execFileSync("npm", ["run", "pack:npx"], {
      cwd: zenlinkMcpRoot,
      stdio: "inherit",
    });
    const stable = path.join(npxDir, "zenlink-mcp.tgz");
    await fs.copyFile(stable, path.join(destRoot, "zenlink-mcp.tgz"));
    const entries = await fs.readdir(npxDir);
    const versioned = entries.find(
      (f) => f.startsWith("zenlink-mcp-") && f.endsWith(".tgz") && f !== "zenlink-mcp.tgz"
    );
    let versionedName = "";
    if (versioned) {
      versionedName = versioned;
      await fs.copyFile(
        path.join(npxDir, versioned),
        path.join(destRoot, versioned)
      );
    }
    console.log(
      `synced npm pack -> public/zenlink/zenlink-mcp.tgz${versionedName ? ` + ${versionedName}` : ""}`
    );
  } catch (e) {
    console.warn(
      "sync-zenlink-public: pack:npx skipped:",
      e instanceof Error ? e.message : e
    );
  }

  const sdkVersionPath = path.resolve(
    frontendRoot,
    "../packages/zenlink-mcp/src/zenlink/sdk-version.ts"
  );
  const sdkVersionRaw = await fs.readFile(sdkVersionPath, "utf8");
  const sdkVersionMatch = sdkVersionRaw.match(
    /ZENLINK_SDK_VERSION\s*=\s*"([^"]+)"/
  );
  const zenlinkSdkVersion = sdkVersionMatch?.[1] ?? "unknown";

  const mcpPkgRaw = await fs.readFile(
    path.resolve(frontendRoot, "../packages/zenlink-mcp/package.json"),
    "utf8"
  );
  const mcpPkg = JSON.parse(mcpPkgRaw);
  const versionedFilename = `zenlink-mcp-${mcpPkg.version}.tgz`;
  const offlineVersionedFilename = `zenlink-mcp-offline-v${mcpPkg.version}.tar.gz`;

  const offlineSrc = path.resolve(
    frontendRoot,
    "../packages",
    offlineVersionedFilename
  );
  let offlineSynced = false;
  try {
    await fs.stat(offlineSrc);
    await fs.copyFile(
      offlineSrc,
      path.join(destRoot, offlineVersionedFilename)
    );
    await fs.copyFile(offlineSrc, path.join(destRoot, "zenlink-mcp-offline.tar.gz"));
    offlineSynced = true;
    console.log(
      `synced offline pack -> public/zenlink/zenlink-mcp-offline.tar.gz (+ ${offlineVersionedFilename})`
    );
  } catch {
    console.warn(
      "sync-zenlink-public: offline tarball not built; run `npm run pack` in packages/zenlink-mcp then re-sync."
    );
  }

  const manifest = {
    generated_at: new Date().toISOString(),
    offline_pack_stable_filename: "zenlink-mcp-offline.tar.gz",
    offline_pack_versioned_filename: offlineVersionedFilename,
    offline_bundle_present_on_sync_disk: offlineSynced,
    npx_pack_filename: "zenlink-mcp.tgz",
    npx_pack_versioned_filename: versionedFilename,
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

  console.log("synced zenlink -> public/zenlink (+ npx pack + release-manifest.json)");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
