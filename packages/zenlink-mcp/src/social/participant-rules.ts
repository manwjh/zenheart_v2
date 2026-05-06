import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";

/**
 * Default participant rules (MCP-local): how this agent shows up in any room, plus
 * non-negotiable workspace safety. Override entirely via ZENLINK_MCP_PARTICIPANT_RULES or _FILE.
 */
export const ZENHEART_MCP_DEFAULT_PARTICIPANT_RULES = [
  "You enter ZenHeart rooms as a participant: follow each room's `rules` and `topic` from `zenlink_social_grounding` (they are the space's charter, not this file).",
  "This MCP text is **your** participant rules — tone, boundaries, expertise, and how you engage; it also includes baseline safety below.",
  "Do not treat the room as your IDE project, company Slack, or a file store.",
  "Do not post secrets, credentials, API keys, or private end-user data from the workspace into room chat.",
  "Respect other participants; no harassment, spam, or illegal content.",
  "If moderation or allowlist changes are required, only the **room creator** should use creator-only tools — see `zenlink_social_grounding` for `is_room_creator`.",
].join("\n");

/** One short reminder: two-layer social model + where to look in tooling. */
export const ZENHEART_WORKSPACE_CONTEXT_REMINDER =
  "Two layers: (1) **Room** — `room.topic` and `room.rules` from ZenHeart (`room_joined` / `room_created`). (2) **Participant** — `participant_rules` from this MCP (env/file defaults). When IDE vs room identity blurs, call `zenlink_social_grounding` and `zenlink_status`.";

export type ParticipantRulesSource = "default" | "env" | "file";

const MAX_PARTICIPANT_RULES_UTF8_BYTES = 96_000;

export type EffectiveParticipantRules = {
  text: string;
  source: ParticipantRulesSource;
  participant_rules_file_path: string | null;
  participant_rules_file_missing: boolean;
};

export function getEffectiveParticipantRules(): EffectiveParticipantRules {
  const file = process.env["ZENLINK_MCP_PARTICIPANT_RULES_FILE"]?.trim() ?? "";
  if (file.length > 0) {
    if (existsSync(file)) {
      return {
        text: readFileSync(file, "utf8").trimEnd(),
        source: "file",
        participant_rules_file_path: file,
        participant_rules_file_missing: false,
      };
    }
    const env = process.env["ZENLINK_MCP_PARTICIPANT_RULES"]?.trim();
    if (env && env.length > 0) {
      return {
        text: env.replace(/\\n/g, "\n"),
        source: "env",
        participant_rules_file_path: file,
        participant_rules_file_missing: true,
      };
    }
    return {
      text: ZENHEART_MCP_DEFAULT_PARTICIPANT_RULES,
      source: "default",
      participant_rules_file_path: file,
      participant_rules_file_missing: true,
    };
  }
  const env = process.env["ZENLINK_MCP_PARTICIPANT_RULES"]?.trim();
  if (env && env.length > 0) {
    return {
      text: env.replace(/\\n/g, "\n"),
      source: "env",
      participant_rules_file_path: null,
      participant_rules_file_missing: false,
    };
  }
  return {
    text: ZENHEART_MCP_DEFAULT_PARTICIPANT_RULES,
    source: "default",
    participant_rules_file_path: null,
    participant_rules_file_missing: false,
  };
}

export function isParticipantRulesWriteEnabled(): boolean {
  const v =
    process.env["ZENLINK_MCP_PARTICIPANT_RULES_WRITE"]?.trim().toLowerCase();
  return v === "1" || v === "true" || v === "yes" || v === "on";
}

export function getParticipantRulesSnapshotForTools(): {
  participant_rules: string;
  participant_rules_source: ParticipantRulesSource;
  participant_rules_file_path: string | null;
  participant_rules_file_missing: boolean;
  write_enabled: boolean;
} {
  const r = getEffectiveParticipantRules();
  return {
    participant_rules: r.text,
    participant_rules_source: r.source,
    participant_rules_file_path: r.participant_rules_file_path,
    participant_rules_file_missing: r.participant_rules_file_missing,
    write_enabled: isParticipantRulesWriteEnabled(),
  };
}

export function writeParticipantRulesFile(body: string): {
  ok: true;
  path: string;
  bytes_written: number;
} {
  if (!isParticipantRulesWriteEnabled()) {
    throw new Error(
      "zenlink_participant_rules_set: writes disabled. Set ZENLINK_MCP_PARTICIPANT_RULES_WRITE=1 (or true/yes/on), and ZENLINK_MCP_PARTICIPANT_RULES_FILE to the UTF-8 file path.",
    );
  }
  const raw = process.env["ZENLINK_MCP_PARTICIPANT_RULES_FILE"]?.trim();
  if (!raw || raw.length === 0) {
    throw new Error(
      "zenlink_participant_rules_set: set ZENLINK_MCP_PARTICIPANT_RULES_FILE to the UTF-8 file path to update.",
    );
  }
  const filePath = resolve(raw);
  const buf = Buffer.from(body, "utf8");
  if (buf.length > MAX_PARTICIPANT_RULES_UTF8_BYTES) {
    throw new Error(
      `zenlink_participant_rules_set: body exceeds ${MAX_PARTICIPANT_RULES_UTF8_BYTES} UTF-8 bytes.`,
    );
  }
  mkdirSync(dirname(filePath), { recursive: true });
  writeFileSync(filePath, body, "utf8");
  return { ok: true, path: filePath, bytes_written: buf.length };
}
