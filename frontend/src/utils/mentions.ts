/**
 * Renders plain text with @handle spans for display (matches v2 social `parse_mentions` token shape).
 * When the server sent `mentions` (agent ids), use `formatTextWithMentionSpansWithHints` so only
 * handles that map to an id in that list render as authoritative (see social `mention_agent_ids`).
 */
const MENTION_RE = /@(?:\{([^{}\n]{1,120})\}|([A-Za-z0-9_-]+))/g;

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
export type MentionRender =
  | MentionHint
  | {
      hint: MentionHint;
      displayText?: string;
      title?: string;
    };

const HINT_CLASS: Record<MentionHint, string> = {
  authoritative: "text-mention text-mention--valid",
  room_only: "text-mention text-mention--room",
  stray: "text-mention text-mention--unknown",
};

export function formatTextWithMentionSpansWithHints(
  text: string,
  getHint: (nameLower: string, rawToken: string) => MentionRender,
): string {
  const re = new RegExp(MENTION_RE.source, "g");
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    out += escapeHtml(text.slice(last, m.index!));
    const name = (m[1] ?? m[2] ?? "").trim();
    const rawToken = m[0] ?? "";
    const rendered = getHint(name.toLowerCase(), rawToken);
    const hint = typeof rendered === "string" ? rendered : rendered.hint;
    const displayText =
      typeof rendered === "string" ? rawToken : rendered.displayText ?? rawToken;
    const titleAttr =
      typeof rendered === "string" || !rendered.title
        ? ""
        : ` title="${escapeHtml(rendered.title)}"`;
    out += `<span class="${HINT_CLASS[hint]}"${titleAttr}>${escapeHtml(displayText)}</span>`;
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
