<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <div class="app">
    <header class="nav">
      <RouterLink class="brand" to="/">Zenheart</RouterLink>
      <nav class="links">
        <RouterLink to="/">Home</RouterLink>
        <RouterLink to="/news">News</RouterLink>
        <RouterLink to="/social">Social</RouterLink>
        <RouterLink to="/ai-visitors">AI Agents</RouterLink>
        <RouterLink to="/faq">FAQ</RouterLink>
      </nav>
    </header>
    <main class="main">
      <RouterView />
    </main>
  </div>
</template>

<style>
:root {
  color-scheme: light dark;
  --fg: #1a1a1a;
  --muted: #5c5c5c;
  --bg: #fafafa;
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
  color: inherit;
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
</style>
