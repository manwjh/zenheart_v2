/**
 * Copy zenlink package source into public/zenlink for on-site transparency.
 * Writes zenlink-source.tar.gz (full tree for third parties: npm ci without the monorepo).
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

  console.log("synced zenlink -> public/zenlink (+ zenlink-source.tar.gz)");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
