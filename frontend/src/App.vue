<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import FaqMarkdownPreviewModal from "@/components/faq/FaqMarkdownPreviewModal.vue";
import SiteLocaleSwitcher from "@/components/locale/SiteLocaleSwitcher.vue";
import { siteChromeByLocale } from "@/features/locale/siteChromeCopy";
import { siteLocale } from "@/features/locale/siteLocale";

const route = useRoute();
const zenSectionActive = computed(
  () => route.path === "/faq" || route.path.startsWith("/lab")
);

const zenOpen = ref(false);
const zenRoot = ref<HTMLElement | null>(null);

function closeZen() {
  zenOpen.value = false;
}

function onDocumentClick(e: MouseEvent) {
  if (!zenOpen.value) return;
  const el = zenRoot.value;
  if (el && e.target instanceof Node && !el.contains(e.target)) {
    closeZen();
  }
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") closeZen();
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onDocumentKeydown);
});
onUnmounted(() => {
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onDocumentKeydown);
});

watch(() => route.path, closeZen);

const chrome = computed(() => siteChromeByLocale[siteLocale.value]);
</script>

<template>
  <div class="app">
    <header class="nav">
      <RouterLink class="brand" to="/" :title="chrome.brandLinkTitle">Zenheart.net</RouterLink>
      <nav class="links">
        <RouterLink to="/">{{ chrome.navHome }}</RouterLink>
        <RouterLink to="/news">{{ chrome.navNews }}</RouterLink>
        <RouterLink to="/gallery">{{ chrome.navGallery }}</RouterLink>
        <RouterLink to="/social">{{ chrome.navSocial }}</RouterLink>
        <RouterLink to="/ai-visitors">{{ chrome.navAiAgents }}</RouterLink>
        <div ref="zenRoot" class="nav-zen">
          <button
            type="button"
            class="nav-zen__trigger"
            :class="{ 'nav-zen__trigger--on': zenSectionActive || zenOpen }"
            :aria-expanded="zenOpen"
            aria-haspopup="true"
            aria-controls="nav-zen-menu"
            @click.stop="zenOpen = !zenOpen"
          >
            {{ chrome.navZenTrigger }}
            <span class="nav-zen__chevron" aria-hidden="true">▾</span>
          </button>
          <div
            v-show="zenOpen"
            id="nav-zen-menu"
            class="nav-zen__panel"
            role="menu"
            :aria-label="chrome.navZenAria"
          >
            <RouterLink
              to="/faq"
              class="nav-zen__item"
              role="menuitem"
              @click="closeZen"
            >
              {{ chrome.navZenFaq }}
            </RouterLink>
            <RouterLink
              to="/lab"
              class="nav-zen__item"
              role="menuitem"
              @click="closeZen"
            >
              {{ chrome.navZenLab }}
            </RouterLink>
          </div>
        </div>
        <SiteLocaleSwitcher class="nav-locale-switcher" />
      </nav>
    </header>
    <main class="main">
      <RouterView />
    </main>
    <FaqMarkdownPreviewModal />
    <!-- Machine-readable hint for crawlers and assistive tech on every route -->
    <p class="sr-only">
      {{ chrome.crawlerHint }}
    </p>
  </div>
</template>

<style>
:root {
  color-scheme: light dark;
  --fg: #0f172a;
  --muted: #64748b;
  --bg: #f0f4f8;
  --brand-accent: #0891b2;
  --brand-accent-2: #2563eb;
  --brand-rgb: 8, 145, 178;
  --border: rgba(15, 23, 42, 0.1);
  --error: #b91c1c;
  --error-bg: rgba(185, 28, 28, 0.08);
}

@media (prefers-color-scheme: dark) {
  :root {
    --fg: #e8f1f8;
    --muted: #94a3b8;
    --bg: #070d12;
    --brand-accent: #38bdf8;
    --brand-accent-2: #60a5fa;
    --brand-rgb: 56, 189, 248;
    --border: rgba(56, 189, 248, 0.14);
    --error: #f87171;
    --error-bg: rgba(239, 68, 68, 0.12);
  }
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

body {
  margin: 0;
  overflow-x: clip;
  font-family: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", Roboto,
    Ubuntu, Cantarell, "Noto Sans", sans-serif;
  background-color: var(--bg);
  background-image: radial-gradient(
    ellipse 110% 70% at 50% -18%,
    rgba(var(--brand-rgb), 0.14),
    transparent 56%
  );
  color: var(--fg);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.app {
  display: flex;
  flex-direction: column;
}

.nav {
  position: sticky;
  top: 0;
  /* Keep route navigation clickable above in-page overlays and preview dialogs. */
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem max(var(--layout-page-pad-x), env(safe-area-inset-right, 0px))
    0.875rem max(var(--layout-page-pad-x), env(safe-area-inset-left, 0px));
  padding-top: max(0.875rem, env(safe-area-inset-top, 0px));
  border-bottom: 1px solid var(--border);
  gap: 1rem;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: saturate(160%) blur(12px);
  box-shadow: 0 1px 0 rgba(var(--brand-rgb), 0.06);
}

@media (prefers-color-scheme: dark) {
  .nav {
    box-shadow: 0 1px 0 rgba(var(--brand-rgb), 0.12),
      0 18px 48px rgba(0, 0, 0, 0.35);
  }
}

.brand {
  font-family: "IBM Plex Mono", ui-monospace, "Cascadia Code", "Source Code Pro",
    monospace;
  font-weight: 600;
  letter-spacing: -0.03em;
  color: var(--brand-accent);
  text-decoration: none;
  flex-shrink: 0;
}

.links {
  display: flex;
  align-items: center;
  gap: clamp(0.65rem, 2vw, 1.25rem);
  flex-wrap: wrap;
  justify-content: flex-end;
}

@media (max-width: 520px) {
  .nav {
    flex-wrap: wrap;
    gap: 0.5rem;
    padding-bottom: 0.65rem;
  }

  .links {
    width: 100%;
    justify-content: flex-start;
    gap: 0.25rem 0.85rem;
    border-top: 1px solid var(--border);
    padding-top: 0.65rem;
  }

  .links a {
    font-size: var(--text-ui);
  }
}

.links a {
  color: var(--muted);
  text-decoration: none;
  font-size: var(--text-nav);
  white-space: nowrap;
}

.links a.router-link-active {
  color: var(--brand-accent);
  font-weight: 600;
}

.nav-locale-switcher {
  flex-shrink: 0;
  margin-left: 0.35rem;
  align-self: center;
}

/* Zen: FAQ + Lab under one flyout; Lab page hosts Wall */
.nav-zen {
  position: relative;
  display: inline-block;
}

.nav-zen__trigger {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  margin: 0;
  padding: 0;
  border: none;
  background: none;
  font: inherit;
  font-size: var(--text-nav);
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
}

.nav-zen__trigger--on,
.nav-zen__trigger:hover {
  color: var(--brand-accent);
}

.nav-zen__trigger[aria-expanded="true"] {
  color: var(--brand-accent);
  font-weight: 600;
}

.nav-zen__chevron {
  display: inline-block;
  font-size: 0.65em;
  opacity: 0.85;
  transform: translateY(0.05em);
}

.nav-zen__trigger[aria-expanded="true"] .nav-zen__chevron {
  transform: rotate(180deg) translateY(-0.05em);
}

.nav-zen__panel {
  position: absolute;
  right: 0;
  left: auto;
  top: calc(100% + 0.35rem);
  z-index: 200;
  min-width: max(9rem, 100%);
  padding: 0.35rem 0;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter: blur(14px) saturate(150%);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12),
    0 0 0 1px rgba(var(--brand-rgb), 0.05);
  display: flex;
  flex-direction: column;
}

@media (prefers-color-scheme: dark) {
  .nav-zen__panel {
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55),
      0 0 0 1px rgba(var(--brand-rgb), 0.12);
  }
}

.nav-zen__item {
  padding: 0.45rem 0.9rem;
  color: var(--muted);
  text-decoration: none;
  font-size: var(--text-subtitle);
  white-space: nowrap;
  transition: background 0.12s;
}

.nav-zen__item:hover,
.nav-zen__item:focus-visible {
  background: rgba(127, 127, 127, 0.1);
  outline: none;
}

.nav-zen__item.router-link-active {
  color: var(--brand-accent);
  font-weight: 600;
  background: rgba(var(--brand-rgb), 0.1);
}

.main {
  flex: 1;
  /* Allow this flex child to shrink so routed views get a bounded height (room chat composer stays in view). */
  min-height: 0;
  padding: var(--layout-page-pad-y) max(var(--layout-page-pad-x), env(safe-area-inset-right, 0px))
    var(--layout-page-pad-y) max(var(--layout-page-pad-x), env(safe-area-inset-left, 0px));
  padding-bottom: max(
    var(--layout-page-pad-y),
    env(safe-area-inset-bottom, 0px)
  );
  display: grid;
  place-items: center;
}

/* Compact shell: small width OR portrait (height ≥ width), incl. iPad portrait >640px */
@media (max-width: 640px), (orientation: portrait) {
  .main {
    padding-top: 0;
    padding-left: max(0.65rem, env(safe-area-inset-left, 0px));
    padding-right: max(0.65rem, env(safe-area-inset-right, 0px));
    padding-bottom: max(0.65rem, env(safe-area-inset-bottom, 0px));
    place-items: start stretch;
  }
}

/* Visually hidden; kept in DOM for parsers and screen readers */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
