/** POST like; returns new count or null on failure. */
export async function postNewsArticleLike(articleId: string): Promise<number | null> {
  try {
    const res = await fetch(`/v2/news/articles/${articleId}/like`, { method: "POST" });
    if (!res.ok) return null;
    const data = (await res.json()) as { like_count: number };
    return typeof data.like_count === "number" ? data.like_count : null;
  } catch {
    return null;
  }
}
