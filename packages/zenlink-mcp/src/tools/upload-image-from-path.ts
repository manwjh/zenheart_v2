/**
 * Optional local filesystem ingest for zenlink_upload_image (avoids giant base64 blobs in MCP JSON).
 */
import { homedir } from "node:os";
import { basename, extname, isAbsolute, relative, resolve, sep } from "node:path";
import { readFileSync, realpathSync, statSync } from "node:fs";
import type { ZenlinkAgentImageContentType } from "../zenlink/http.js";

const _MAX_AGENT_IMAGE_BYTES = 10 * 1024 * 1024;

const _EXT_FOR_CT = new Map<string, ZenlinkAgentImageContentType>([
  [".jpg", "image/jpeg"],
  [".jpeg", "image/jpeg"],
  [".png", "image/png"],
  [".gif", "image/gif"],
  [".webp", "image/webp"],
  [".svg", "image/svg+xml"],
]);

function truthyEnv(v: string | undefined): boolean {
  const s = v?.trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

/** When set, zenlink_upload_image may use `image_path` instead of `image_base64`. */
export function isUploadImageFromPathEnabled(): boolean {
  return truthyEnv(process.env["ZENLINK_MCP_UPLOAD_IMAGE_FS"]);
}

function expandLeadingTilde(p: string): string {
  const t = p.trim();
  if (t.startsWith(`~${sep}`)) {
    return resolve(homedir(), t.slice(2));
  }
  if (t === "~") {
    return homedir();
  }
  return t;
}

/** Collect absolute allowed directory roots after `~` expansion. */
export function collectUploadImageAllowedRoots(): string[] {
  const single = process.env["ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT"]?.trim();
  const multi = process.env["ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS"]?.trim();
  const roots: string[] = [];
  if (single) {
    roots.push(expandLeadingTilde(single));
  }
  if (multi) {
    for (const part of multi.split(",")) {
      const tt = part.trim();
      if (tt) roots.push(expandLeadingTilde(tt));
    }
  }
  const seen = new Set<string>();
  const out: string[] = [];
  for (const r of roots) {
    const key = resolve(r);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

function isPathInsideResolvedDir(fileReal: string, dirReal: string): boolean {
  const rel = relative(dirReal, fileReal);
  return rel !== "" && !rel.startsWith(`..${sep}`) && rel !== "..";
}

/**
 * Read a regular image file under an allowed root directory.
 *
 * Requires ZENLINK_MCP_UPLOAD_IMAGE_FS=1 / true / yes / on,
 * ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT and/or ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS (comma-separated).
 *
 * @param explicitContentType — required when the file extension is not a known image suffix.
 */
export function readAgentImageBytesFromResolvedPath(
  rawPath: string,
  explicitContentType: ZenlinkAgentImageContentType | undefined,
): {
  data: Uint8Array;
  contentType: ZenlinkAgentImageContentType;
  defaultFilename: string;
} {
  if (!isUploadImageFromPathEnabled()) {
    throw new Error(
      "zenlink_upload_image image_path is disabled. Set ZENLINK_MCP_UPLOAD_IMAGE_FS=1 and configure ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT or ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS (comma-separated prefixes). Prefer image_base64 for portable installs.",
    );
  }

  const rootsRaw = collectUploadImageAllowedRoots();
  if (rootsRaw.length === 0) {
    throw new Error(
      "zenlink_upload_image image_path requires ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT (one directory) and/or ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOTS (comma-separated). Paths must resolve inside those directories.",
    );
  }

  const expanded = expandLeadingTilde(rawPath);
  if (!isAbsolute(expanded)) {
    throw new Error(
      "image_path must be an absolute filesystem path after ~ expansion (relative paths rejected).",
    );
  }

  let candidateReal: string;
  try {
    candidateReal = realpathSync(expanded);
  } catch {
    throw new Error(`image_path not found or not readable: ${rawPath}`);
  }

  let st;
  try {
    st = statSync(candidateReal);
  } catch {
    throw new Error(`image_path stat failed: ${rawPath}`);
  }
  if (!st.isFile()) {
    throw new Error("image_path must be a regular file (not a directory or special device).");
  }

  let allowed = false;
  for (const rr of rootsRaw) {
    let rootReal: string;
    try {
      rootReal = realpathSync(rr);
    } catch {
      continue;
    }
    const rs = statSync(rootReal);
    if (!rs.isDirectory()) continue;
    if (isPathInsideResolvedDir(candidateReal, rootReal)) {
      allowed = true;
      break;
    }
  }

  if (!allowed) {
    throw new Error(
      "image_path resolves outside configured allowed roots (ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT / _ROOTS).",
    );
  }

  const size = st.size;
  if (size === 0 || size > _MAX_AGENT_IMAGE_BYTES) {
    throw new Error(
      `image file must be between 1 and ${_MAX_AGENT_IMAGE_BYTES} bytes (same limit as decoded base64 uploads).`,
    );
  }

  const data = readFileSync(candidateReal);

  const ext = extname(candidateReal).toLowerCase();
  const fromExt = _EXT_FOR_CT.get(ext);
  const ct = explicitContentType ?? fromExt;
  if (!ct) {
    throw new Error(
      "Cannot infer image MIME from file extension; pass content_type on zenlink_upload_image (e.g. image/png).",
    );
  }
  const bn = basename(candidateReal);
  const defaultFilename = bn || `upload${ext || ".png"}`;

  return {
    data,
    contentType: ct,
    defaultFilename,
  };
}
