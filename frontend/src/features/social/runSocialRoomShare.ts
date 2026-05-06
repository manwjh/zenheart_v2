export type SocialRoomShareUi = {
  isWechatBrowser: boolean;
  flashCopied: () => void;
  showErrorToast: (message: string) => void;
};

export type SocialRoomSharePayload = {
  room_id: string;
  name: string;
  topic: string;
  /** Room rules / description from the server (shown as "Room Rules" in the UI). */
  rules?: string;
  creator_name?: string;
};

const RULES_SHARE_MAX_CHARS = 480;

/** Canonical share URL (OG + WeChat bar), same pattern as `/v2/share/news/{id}`. */
export function buildSocialRoomSharePageUrl(roomId: string): string {
  const id = (roomId || "").trim();
  return `${location.origin}/v2/share/social/room/${encodeURIComponent(id)}`;
}

/** Full URL to the hash-route room observe page (works for manual share and deep links). */
export function buildSocialRoomObserveUrl(roomId: string): string {
  const rawBase = import.meta.env.BASE_URL || "/";
  const base = rawBase.endsWith("/") ? rawBase : `${rawBase}/`;
  return `${location.origin}${base}#/social/room/${encodeURIComponent(roomId)}`;
}

/** Multi-line text for WeChat paste and clipboard (headline + intro + link). */
export function buildSocialRoomShareText(room: SocialRoomSharePayload): string {
  const name = (room.name || "").trim();
  const topic = (room.topic || "").trim();
  const headline = (topic || name) || "Social room";
  const lines: string[] = [headline];

  if (topic && name && topic !== name) {
    lines.push(name);
  }

  const host = (room.creator_name || "").trim();
  if (host) {
    lines.push(`Host: ${host}`);
  }

  let rules = (room.rules || "").trim();
  if (rules) {
    if (rules.length > RULES_SHARE_MAX_CHARS) {
      rules = `${rules.slice(0, RULES_SHARE_MAX_CHARS - 1)}…`;
    }
    lines.push(rules);
  }

  const shareUrl = buildSocialRoomSharePageUrl(room.room_id);
  return `${lines.join("\n")}\n\n${shareUrl}`;
}

export async function runSocialRoomShare(
  room: SocialRoomSharePayload,
  ui: SocialRoomShareUi,
): Promise<void> {
  const shareUrl = buildSocialRoomSharePageUrl(room.room_id);
  const name = (room.name || "").trim();
  const topic = (room.topic || "").trim();
  const label = (topic || name) || "Social room";
  const fullText = buildSocialRoomShareText(room);
  const host = (room.creator_name || "").trim();
  const stubLines = [label, host ? `Host: ${host}` : ""].filter((s) => s.length > 0);
  const shareStubText =
    stubLines.length > 0 ? `${stubLines.join("\n")}\n\n${shareUrl}` : shareUrl;

  if (ui.isWechatBrowser) {
    try {
      await navigator.clipboard.writeText(fullText);
      ui.flashCopied();
    } catch {
      ui.showErrorToast("Could not copy. Check clipboard permission.");
    }
    return;
  }

  if (typeof navigator.share === "function") {
    try {
      await navigator.share({
        title: label,
        text: shareStubText,
        url: shareUrl,
      });
    } catch {
      // user cancelled
    }
    return;
  }

  try {
    await navigator.clipboard.writeText(fullText);
    ui.flashCopied();
  } catch {
    ui.showErrorToast("Could not copy to clipboard.");
  }
}
