import { ref, watch } from "vue";

export type SiteLocale = "zh" | "en";

const STORAGE_KEY = "zenheart.siteLocale";

function readStored(): SiteLocale {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "en" || v === "zh") return v;
  } catch {
    /* ignore */
  }
  return "zh";
}

/** App-wide UI language. Import this ref from any component; persisted to localStorage. */
export const siteLocale = ref<SiteLocale>(readStored());

export function setSiteLocale(next: SiteLocale): void {
  siteLocale.value = next;
}

/** Sync `<html lang>` and persist. Call once from application bootstrap. */
export function initSiteLocale(): void {
  const apply = (loc: SiteLocale) => {
    document.documentElement.lang = loc === "zh" ? "zh-CN" : "en";
    document.documentElement.setAttribute("data-site-locale", loc);
    try {
      localStorage.setItem(STORAGE_KEY, loc);
    } catch {
      /* ignore */
    }
  };
  apply(siteLocale.value);
  watch(siteLocale, apply);
}
