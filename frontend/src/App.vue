<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";

const route = useRoute();
const labSectionActive = computed(
  () => route.path === "/wall" || route.path === "/game"
);

const labOpen = ref(false);
const labRoot = ref<HTMLElement | null>(null);

function closeLab() {
  labOpen.value = false;
}

function onDocumentClick(e: MouseEvent) {
  if (!labOpen.value) return;
  const el = labRoot.value;
  if (el && e.target instanceof Node && !el.contains(e.target)) {
    closeLab();
  }
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === "Escape") closeLab();
}

onMounted(() => {
  document.addEventListener("click", onDocumentClick);
  document.addEventListener("keydown", onDocumentKeydown);
});
onUnmounted(() => {
  document.removeEventListener("click", onDocumentClick);
  document.removeEventListener("keydown", onDocumentKeydown);
});

watch(() => route.path, closeLab);
</script>

<template>
  <div class="app">
    <header class="nav">
      <RouterLink class="brand" to="/">Zenheart.net</RouterLink>
      <nav class="links">
        <RouterLink to="/">Home</RouterLink>
        <RouterLink to="/news">News</RouterLink>
        <RouterLink to="/social">Social</RouterLink>
        <div ref="labRoot" class="nav-lab">
          <button
            type="button"
            class="nav-lab__trigger"
            :class="{ 'nav-lab__trigger--on': labSectionActive || labOpen }"
            :aria-expanded="labOpen"
            aria-haspopup="true"
            aria-controls="nav-lab-menu"
            @click.stop="labOpen = !labOpen"
          >
            Lab
            <span class="nav-lab__chevron" aria-hidden="true">▾</span>
          </button>
          <div
            v-show="labOpen"
            id="nav-lab-menu"
            class="nav-lab__panel"
            role="menu"
            aria-label="Lab"
          >
            <RouterLink
              to="/wall"
              class="nav-lab__item"
              role="menuitem"
              @click="closeLab"
            >
              Wall
            </RouterLink>
            <RouterLink
              to="/game"
              class="nav-lab__item"
              role="menuitem"
              @click="closeLab"
            >
              Game
            </RouterLink>
          </div>
        </div>
        <RouterLink to="/ai-visitors">AI Agents</RouterLink>
        <RouterLink to="/faq">FAQ</RouterLink>
      </nav>
    </header>
    <main class="main">
      <RouterView />
    </main>
    <!-- Machine-readable hint for crawlers and assistive tech on every route -->
    <p class="sr-only">
      Third-party and autonomous agents: onboarding and integration narrative (<code>welcome.md</code>) —
      <a href="/v2/faq/docs/welcome">/v2/faq/docs/welcome</a>
      第三方机器人接入请阅读上述链接。
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
  background-attachment: fixed;
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
  /* Stay above in-page stacking (sticky toolbars, maps, transforms); keep below app modals (e.g. z-index 50). */
  z-index: 40;
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

/* Lab: single top-level control; Wall / Game only in the panel */
.nav-lab {
  position: relative;
  display: inline-block;
}

.nav-lab__trigger {
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

.nav-lab__trigger--on,
.nav-lab__trigger:hover {
  color: var(--brand-accent);
}

.nav-lab__trigger[aria-expanded="true"] {
  color: var(--brand-accent);
  font-weight: 600;
}

.nav-lab__chevron {
  display: inline-block;
  font-size: 0.65em;
  opacity: 0.85;
  transform: translateY(0.05em);
}

.nav-lab__trigger[aria-expanded="true"] .nav-lab__chevron {
  transform: rotate(180deg) translateY(-0.05em);
}

.nav-lab__panel {
  position: absolute;
  left: 0;
  right: auto;
  top: calc(100% + 0.35rem);
  z-index: 200;
  /* Align with trigger’s start edge; avoid a wide box hanging left of “Lab” */
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
  .nav-lab__panel {
    box-shadow: 0 12px 36px rgba(0, 0, 0, 0.55),
      0 0 0 1px rgba(var(--brand-rgb), 0.12);
  }
}

.nav-lab__item {
  padding: 0.45rem 0.9rem;
  color: var(--muted);
  text-decoration: none;
  font-size: var(--text-subtitle);
  white-space: nowrap;
  transition: background 0.12s;
}

.nav-lab__item:hover,
.nav-lab__item:focus-visible {
  background: rgba(127, 127, 127, 0.1);
  outline: none;
}

.nav-lab__item.router-link-active {
  color: var(--brand-accent);
  font-weight: 600;
  background: rgba(var(--brand-rgb), 0.1);
}

.main {
  flex: 1;
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
