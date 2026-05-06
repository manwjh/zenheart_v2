const STORAGE_KEY = "zenheart.news.fromListNav";
const MAX_AGE_MS = 30 * 60_000;

type Stamp = { id: string; t: number };

/** Call immediately before navigating to `/news/:id` from the list. */
export function stampNewsOpenFromList(articleId: string): void {
  try {
    const payload: Stamp = { id: articleId, t: Date.now() };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  } catch {
    // private mode / quota — back button falls through to `push` list
  }
}

/**
 * If the current detail was opened from our list (same tab), return true and clear the stamp.
 * Used so `router.back()` restores the cached list; otherwise navigate explicitly.
 */
export function consumeNewsOpenFromList(articleId: string): boolean {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const p = JSON.parse(raw) as Stamp;
    const ok =
      typeof p?.id === "string" &&
      p.id === articleId &&
      typeof p?.t === "number" &&
      Date.now() - p.t < MAX_AGE_MS;
    sessionStorage.removeItem(STORAGE_KEY);
    return ok;
  } catch {
    try {
      sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    return false;
  }
}
