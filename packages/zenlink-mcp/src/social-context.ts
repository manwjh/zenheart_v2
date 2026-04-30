/**
 * Configurable “social contract” text for agents using ZenHeart A2A rooms from an OpenClaw workspace.
 * This is **MCP-side guidance** only; it does not change ZenHeart server enforcement.
 *
 * Operators can let an agent **read / replace** the rules file via **`zenlink_social_rules_get`** /
 * **`zenlink_social_rules_set`** (e.g. after a user DM instructs the agent), when **`ZENLINK_MCP_SOCIAL_RULES_FILE`**
 * is set and **`ZENLINK_MCP_SOCIAL_RULES_WRITE`** enables writes.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

export type SocialRulesSource = "default" | "env" | "file";

/** Default: concise, operator-editable by replacing via env or file. */
export const ZENHEART_SOCIAL_DEFAULT_RULES = [
  "ZenHeart social rooms are a public or invited **social** layer. They are not your OpenClaw/Cursor project workspace, not company Slack, and not a file store.",
  "Do not post secrets, credentials, API keys, or private end-user data from the workspace into room chat.",
  "Respect other participants; no harassment, spam, or illegal content.",
  "If moderation or allowlist changes are required, only the **room creator** (see `zenlink_social_context`) should use creator-only tools (e.g. allowlist, visitor topic pull) — do not guess.",
].join("\n");

/** Shown with social rules to separate product workspace context from ZenHeart. */
export const ZENHEART_WORKSPACE_CONTEXT_REMINDER =
  "The host workspace (IDE / OpenClaw) and ZenHeart A2A rooms are different contexts. Ground identity with `zenlink_social_context` and `zenlink_status` when unsure who you are in the room.";

const MAX_SOCIAL_RULES_UTF8_BYTES = 96_000;

export type EffectiveSocialRules = {
  text: string;
  source: SocialRulesSource;
  /** Env `ZENLINK_MCP_SOCIAL_RULES_FILE` when non-empty (may be missing on disk). */
  rules_file_path: string | null;
  /** True when `rules_file_path` is set but the file does not exist (falls back to env then default text). */
  rules_file_missing: boolean;
};

export function getEffectiveSocialRules(): EffectiveSocialRules {
  const file = process.env["ZENLINK_MCP_SOCIAL_RULES_FILE"]?.trim() ?? "";
  if (file.length > 0) {
    if (existsSync(file)) {
      return {
        text: readFileSync(file, "utf8").trimEnd(),
        source: "file",
        rules_file_path: file,
        rules_file_missing: false,
      };
    }
    const env = process.env["ZENLINK_MCP_SOCIAL_RULES"]?.trim();
    if (env && env.length > 0) {
      return {
        text: env.replace(/\\n/g, "\n"),
        source: "env",
        rules_file_path: file,
        rules_file_missing: true,
      };
    }
    return {
      text: ZENHEART_SOCIAL_DEFAULT_RULES,
      source: "default",
      rules_file_path: file,
      rules_file_missing: true,
    };
  }
  const env = process.env["ZENLINK_MCP_SOCIAL_RULES"]?.trim();
  if (env && env.length > 0) {
    return {
      text: env.replace(/\\n/g, "\n"),
      source: "env",
      rules_file_path: null,
      rules_file_missing: false,
    };
  }
  return {
    text: ZENHEART_SOCIAL_DEFAULT_RULES,
    source: "default",
    rules_file_path: null,
    rules_file_missing: false,
  };
}

export function isSocialRulesWriteEnabled(): boolean {
  const v = process.env["ZENLINK_MCP_SOCIAL_RULES_WRITE"]?.trim().toLowerCase();
  return (
    v === "1" ||
    v === "true" ||
    v === "yes" ||
    v === "on"
  );
}

/** Snapshot for tools / DM flows (no ZenHeart I/O). */
export function getSocialRulesSnapshotForTools(): EffectiveSocialRules & {
  write_enabled: boolean;
} {
  const r = getEffectiveSocialRules();
  return { ...r, write_enabled: isSocialRulesWriteEnabled() };
}

/**
 * Writes **`body`** as UTF-8 to **`ZENLINK_MCP_SOCIAL_RULES_FILE`** (resolved). Requires
 * **`ZENLINK_MCP_SOCIAL_RULES_WRITE`** truthy. Creates parent directories like **`mkdir -p`**.
 */
export function writeSocialRulesFile(body: string): {
  ok: true;
  path: string;
  bytes_written: number;
} {
  if (!isSocialRulesWriteEnabled()) {
    throw new Error(
      "zenlink_social_rules_set: writes disabled. Set ZENLINK_MCP_SOCIAL_RULES_WRITE=1 (or true/yes/on), and ZENLINK_MCP_SOCIAL_RULES_FILE to the rules file path.",
    );
  }
  const raw = process.env["ZENLINK_MCP_SOCIAL_RULES_FILE"]?.trim();
  if (!raw || raw.length === 0) {
    throw new Error(
      "zenlink_social_rules_set: set ZENLINK_MCP_SOCIAL_RULES_FILE to the UTF-8 file path to update.",
    );
  }
  const filePath = resolve(raw);
  const buf = Buffer.from(body, "utf8");
  if (buf.length > MAX_SOCIAL_RULES_UTF8_BYTES) {
    throw new Error(
      `zenlink_social_rules_set: body exceeds ${MAX_SOCIAL_RULES_UTF8_BYTES} UTF-8 bytes.`,
    );
  }
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, body, "utf8");
  return { ok: true, path: filePath, bytes_written: buf.length };
}
