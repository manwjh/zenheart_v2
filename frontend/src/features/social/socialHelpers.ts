export type PendingTopicSuggestion = {
  id: string;
  text: string;
  created_at: string;
};

export function normalizePendingTopicSuggestions(raw: unknown): PendingTopicSuggestion[] {
  if (!Array.isArray(raw)) return [];
  const out: PendingTopicSuggestion[] = [];
  for (const x of raw) {
    if (!x || typeof x !== "object") continue;
    const o = x as Record<string, unknown>;
    const id = typeof o.id === "string" ? o.id : "";
    const text = typeof o.text === "string" ? o.text : "";
    const created_at = typeof o.created_at === "string" ? o.created_at : "";
    if (!id || !text) continue;
    out.push({ id, text, created_at });
  }
  return out;
}

export function localCalendarDayStartIso(): string {
  const n = new Date();
  const start = new Date(n.getFullYear(), n.getMonth(), n.getDate(), 0, 0, 0, 0);
  return start.toISOString();
}

export function isChatMessageInViewerLocalToday(sentIso: string, refDate: Date): boolean {
  const d = new Date(sentIso);
  if (isNaN(d.getTime())) return true;
  return (
    d.getFullYear() === refDate.getFullYear() &&
    d.getMonth() === refDate.getMonth() &&
    d.getDate() === refDate.getDate()
  );
}
