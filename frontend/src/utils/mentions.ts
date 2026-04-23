/**
 * Renders plain text with @handle spans for display (matches v2 social `parse_mentions` token shape).
 * When the server sent `mentions` (agent ids), use `formatTextWithMentionSpansWithHints` so only
 * handles that map to an id in that list render as authoritative (see social `mention_agent_ids`).
 */
const MENTION_RE = /@([A-Za-z0-9_\-]+)/g;

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** @token matches a current room member by name; whether it is the server's resolved mention. */
export type MentionHint = "authoritative" | "room_only" | "stray";

const HINT_CLASS: Record<MentionHint, string> = {
  authoritative: "text-mention text-mention--valid",
  room_only: "text-mention text-mention--room",
  stray: "text-mention text-mention--unknown",
};

export function formatTextWithMentionSpansWithHints(
  text: string,
  getHint: (nameLower: string) => MentionHint,
): string {
  const re = new RegExp(MENTION_RE.source, "g");
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, m.index!));
    const name = m[1] ?? "";
    const hint = getHint(name.toLowerCase());
    out += `<span class="${HINT_CLASS[hint]}">@${escapeHtml(name)}</span>`;
    last = m.index! + m[0].length;
  }
  out += escapeHtml(text.slice(last));
  return out;
}

export function formatTextWithMentionSpans(
  text: string,
  isValidMention: (nameLower: string) => boolean,
): string {
  return formatTextWithMentionSpansWithHints(text, (n) =>
    isValidMention(n) ? "authoritative" : "stray",
  );
}

/** Highlight every @token (no room context); use for e.g. public comments. */
export function formatTextWithMentionSpansAllValid(text: string): string {
  return formatTextWithMentionSpans(text, () => true);
}
