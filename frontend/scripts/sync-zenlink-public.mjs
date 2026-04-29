/**
 * Zenlink: reference SDK for wiring your app to ZenHeart (HTTP/WebSocket/msgbox primitives).
 * Copy package source into public/zenlink; writes zenlink-source.tar.gz (SDK-only tarball).
 * Also builds and copies zenheart-openclaw-zenlink-kit-src.tar.gz — full OpenClaw kit (zenlink + zenlink-mcp + skills/zenlink; skill source v2/packages/zenlink-mcp/skill); typical install workspaces/skills/zenlink; see v2/packages/zenlink-mcp/README.md.
 * Runs before dev/build via npm lifecycle scripts.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const frontendRoot = path.resolve(__dirname, "..");
const zenlinkRoot = path.resolve(frontendRoot, "../packages/zenlink");
const destRoot = path.resolve(frontendRoot, "public/zenlink");

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
  await fs.rm(destRoot, { recursive: true, force: true });
  await fs.mkdir(destRoot, { recursive: true });
  await copyDir(path.join(zenlinkRoot, "src"), path.join(destRoot, "src"));
  for (const f of ["README.md", "package.json", "tsconfig.json", "package-lock.json"]) {
    const src = path.join(zenlinkRoot, f);
    try {
      await fs.copyFile(src, path.join(destRoot, f));
    } catch (e) {
      if (f === "package-lock.json") {
        console.warn("sync-zenlink-public: package-lock.json missing — npm ci on client may need npm install instead");
      } else {
        throw e;
      }
    }
  }

  const archive = path.join(destRoot, "zenlink-source.tar.gz");
  execFileSync(
    "tar",
    [
      "-czf",
      archive,
      "-C",
      zenlinkRoot,
      "src",
      "README.md",
      "package.json",
      "tsconfig.json",
      "package-lock.json",
    ],
    { stdio: "inherit" }
  );

  // OpenClaw integration kit (stable URL on zenheart.net/zenlink/…)
  const zenlinkMcpRoot = path.resolve(frontendRoot, "../packages/zenlink-mcp");
  const packagesRoot = path.resolve(frontendRoot, "../packages");
  try {
    execFileSync("npm", ["run", "bundle:source"], { cwd: zenlinkMcpRoot, stdio: "inherit" });
    const names = await fs.readdir(packagesRoot);
    const kits = names.filter(
      (f) => f.startsWith("zenheart-openclaw-zenlink-kit-src-") && f.endsWith(".tar.gz")
    );
    if (kits.length === 0) {
      console.warn(
        "sync-zenlink-public: no zenheart-openclaw-zenlink-kit-src-*.tar.gz in v2/packages"
      );
    } else {
      let best = kits[0];
      let bestM = 0;
      for (const f of kits) {
        const st = await fs.stat(path.join(packagesRoot, f));
        if (st.mtimeMs >= bestM) {
          bestM = st.mtimeMs;
          best = f;
        }
      }
      const kitStable = path.join(destRoot, "zenheart-openclaw-zenlink-kit-src.tar.gz");
      await fs.copyFile(path.join(packagesRoot, best), kitStable);
      console.log(
        `synced OpenClaw kit -> public/zenlink/zenheart-openclaw-zenlink-kit-src.tar.gz (from v2/packages/${best})`
      );
    }
  } catch (e) {
    console.warn(
      "sync-zenlink-public: OpenClaw kit copy skipped:",
      e instanceof Error ? e.message : e
    );
  }

  console.log(
    "synced zenlink -> public/zenlink (+ zenlink-source.tar.gz; + zenheart-openclaw-zenlink-kit-src.tar.gz when bundle:source succeeds)"
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
