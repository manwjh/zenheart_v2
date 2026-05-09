<script setup lang="ts">
import { computed } from "vue";
import { siteLocale, setSiteLocale, type SiteLocale } from "@/features/locale/siteLocale";
import { faqUiByLocale } from "@/features/faq/faqCopy";

const ui = computed(() => faqUiByLocale[siteLocale.value]);

function select(loc: SiteLocale) {
  setSiteLocale(loc);
}
</script>

<template>
  <div
    class="site-locale-switcher"
    role="group"
    :aria-label="ui.localeSwitcherGroup"
  >
    <button
      type="button"
      class="site-locale-btn"
      :class="{ 'is-active': siteLocale === 'zh' }"
      :aria-pressed="siteLocale === 'zh'"
      @click="select('zh')"
    >
      {{ ui.localeZhShort }}
    </button>
    <button
      type="button"
      class="site-locale-btn"
      :class="{ 'is-active': siteLocale === 'en' }"
      :aria-pressed="siteLocale === 'en'"
      @click="select('en')"
    >
      {{ ui.localeEnShort }}
    </button>
  </div>
</template>

<style scoped>
.site-locale-switcher {
  display: inline-flex;
  border-radius: var(--radius-pill);
  border: 1px solid var(--border, rgba(0, 0, 0, 0.12));
  overflow: hidden;
  background: color-mix(in srgb, var(--fg) 6%, var(--bg));
}

.site-locale-btn {
  font: inherit;
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.02em;
  padding: 0.38rem 0.85rem;
  border: none;
  background: transparent;
  color: var(--muted, #5c5c5c);
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
}

.site-locale-btn:hover {
  color: var(--fg);
  background: rgba(0, 0, 0, 0.04);
}

.site-locale-btn.is-active {
  background: var(--fg, #1a1a1a);
  color: var(--bg, #fafafa);
}

@media (prefers-color-scheme: dark) {
  .site-locale-btn.is-active {
    background: var(--fg, #e8f1f8);
    color: var(--bg, #070d12);
  }
}
</style>
