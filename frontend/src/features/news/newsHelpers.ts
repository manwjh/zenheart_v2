export function buildShareText(title: string, summary: string, url: string): string {
  const t = (title || "").trim();
  const s = (summary || "").trim();
  const u = (url || "").trim();
  return [t, s, u].filter((p) => p.length > 0).join("\n\n");
}

export function toIsoDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}
