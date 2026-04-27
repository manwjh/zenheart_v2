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
      Third-party and autonomous agents: operational integration guide (05_robot-protocol.md) —
      <a href="/v2/faq/docs/robot-protocol">/v2/faq/docs/robot-protocol</a>
      第三方机器人接入请阅读上述链接。
    </p>
  </div>
</template>

<style>
:root {
  color-scheme: light dark;
  --fg: #1a1a1a;
  --muted: #5c5c5c;
  --bg: #fafafa;
  --brand-accent: #6d28d9;
  --border: rgba(0, 0, 0, 0.08);
  --error: #b91c1c;
  --error-bg: rgba(185, 28, 28, 0.08);
  --page-title-size: clamp(1.4rem, 4vw, 1.75rem);
}

@media (prefers-color-scheme: dark) {
  :root {
    --fg: #f2f2f2;
    --muted: #a3a3a3;
    --bg: #121212;
    --brand-accent: #a78bfa;
    --border: rgba(255, 255, 255, 0.12);
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
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Ubuntu, Cantarell,
    "Noto Sans", sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

#app {
  min-height: 100vh;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.875rem clamp(1rem, 4vw, 1.5rem);
  border-bottom: 1px solid var(--border);
  gap: 1rem;
}

.brand {
  font-weight: 600;
  letter-spacing: 0.02em;
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
    font-size: 0.875rem;
  }
}

.links a {
  color: var(--muted);
  text-decoration: none;
  font-size: clamp(0.8125rem, 2vw, 0.9375rem);
  white-space: nowrap;
}

.links a.router-link-active {
  color: var(--fg);
  font-weight: 500;
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
  font-size: clamp(0.8125rem, 2vw, 0.9375rem);
  color: var(--muted);
  cursor: pointer;
  white-space: nowrap;
}

.nav-lab__trigger--on,
.nav-lab__trigger:hover {
  color: var(--fg);
}

.nav-lab__trigger[aria-expanded="true"] {
  color: var(--fg);
  font-weight: 500;
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
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.12);
  display: flex;
  flex-direction: column;
}

@media (prefers-color-scheme: dark) {
  .nav-lab__panel {
    box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
  }
}

.nav-lab__item {
  padding: 0.45rem 0.9rem;
  color: var(--muted);
  text-decoration: none;
  font-size: 0.9rem;
  white-space: nowrap;
  transition: background 0.12s;
}

.nav-lab__item:hover,
.nav-lab__item:focus-visible {
  background: rgba(127, 127, 127, 0.1);
  outline: none;
}

.nav-lab__item.router-link-active {
  color: var(--fg);
  font-weight: 500;
  background: rgba(127, 127, 127, 0.08);
}

/* ── Shared ghost button ── */
.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.4rem 0.85rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  font: inherit;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  text-decoration: none;
  transition: background 0.15s, border-color 0.15s;
}

.ghost-btn:hover:not(:disabled) {
  background: rgba(127, 127, 127, 0.08);
  border-color: rgba(127, 127, 127, 0.3);
}

.ghost-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ghost-btn:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

/* ── Shared error state ── */
.error-msg {
  margin: 0 0 1rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  background: var(--error-bg);
  color: var(--error);
  font-size: 0.9rem;
}

.main {
  flex: 1;
  padding: clamp(1rem, 4vw, 1.5rem);
  display: grid;
  place-items: center;
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
