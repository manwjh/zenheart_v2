import type { SiteLocale } from "@/features/locale/siteLocale";

export function formatRelativeUi(ts: number, nowMs: number, locale: SiteLocale): string {
  const sec = Math.max(0, Math.floor((nowMs - ts) / 1000));
  if (locale === "zh") {
    if (sec < 45) return "刚刚";
    const min = Math.floor(sec / 60);
    if (min < 60) return `${min}m`;
    const h = Math.floor(min / 60);
    return `${h}h`;
  }
  if (sec < 45) return "just now";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const h = Math.floor(min / 60);
  return `${h}h ago`;
}

export function relativeTimeJoinedUi(value: string | null, nowMs: number, locale: SiteLocale): string {
  if (!value) return locale === "zh" ? "—" : "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = nowMs - date.getTime();
  const diffS = Math.floor(diffMs / 1000);
  if (locale === "zh") {
    if (diffS < 60) return `${diffS}s`;
    const diffM = Math.floor(diffS / 60);
    if (diffM < 60) return `${diffM}m`;
    const diffH = Math.floor(diffM / 60);
    if (diffH < 24) return `${diffH}h`;
    const diffD = Math.floor(diffH / 24);
    return `${diffD}d`;
  }
  if (diffS < 60) return `${diffS}s ago`;
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) return `${diffM}m ago`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}
