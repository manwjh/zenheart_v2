/** 8-4-4-4-12 hex (PostgreSQL-style UUID string) — rejects non-id paths before calling the API. */
const UUID_LOOSE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isNewsArticleId(value: string | undefined | null): boolean {
  if (value == null || typeof value !== "string") return false;
  return UUID_LOOSE.test(value.trim());
}
