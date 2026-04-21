<script setup lang="ts">
import { ref } from "vue";
import { RouterLink, RouterView } from "vue-router";

const helpDetails = ref<HTMLDetailsElement | null>(null);

function closeHelpMenu() {
  if (helpDetails.value) {
    helpDetails.value.open = false;
  }
}
</script>

<template>
  <div class="app">
    <header class="nav">
      <RouterLink class="brand" to="/">Zenheart</RouterLink>
      <nav class="links">
        <RouterLink to="/">Home</RouterLink>
        <RouterLink to="/news">News</RouterLink>
        <RouterLink to="/social">Social</RouterLink>
        <RouterLink to="/ai-visitors">AI Visitors</RouterLink>
        <details ref="helpDetails" class="nav-group">
          <summary class="nav-group__label">Help</summary>
          <div class="nav-group__menu" role="menu">
            <RouterLink to="/about" role="menuitem" @click="closeHelpMenu">
              About
            </RouterLink>
            <RouterLink to="/faq" role="menuitem" @click="closeHelpMenu">
              FAQ
            </RouterLink>
          </div>
        </details>
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
}

@media (prefers-color-scheme: dark) {
  :root {
    --fg: #f2f2f2;
    --muted: #a3a3a3;
    --bg: #121212;
    --border: rgba(255, 255, 255, 0.12);
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

  .links a,
  .nav-group__label {
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

.nav-group {
  position: relative;
  list-style: none;
}

.nav-group::marker,
.nav-group::-webkit-details-marker {
  display: none;
}

.nav-group__label {
  cursor: pointer;
  list-style: none;
  color: var(--muted);
  font-size: 0.9375rem;
  user-select: none;
}

.nav-group__label::-webkit-details-marker {
  display: none;
}

.nav-group:has(.router-link-active) .nav-group__label {
  color: var(--fg);
  font-weight: 500;
}

.nav-group[open] .nav-group__label {
  color: var(--fg);
}

.nav-group__menu {
  position: absolute;
  top: calc(100% + 0.35rem);
  right: 0;
  min-width: 9rem;
  padding: 0.35rem 0;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 0.5rem;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
  z-index: 20;
}

@media (prefers-color-scheme: dark) {
  .nav-group__menu {
    box-shadow: 0 6px 24px rgba(0, 0, 0, 0.45);
  }
}

.nav-group__menu a {
  padding: 0.45rem 0.85rem;
  color: var(--muted);
  text-decoration: none;
  font-size: 0.9375rem;
  white-space: nowrap;
}

.nav-group__menu a:hover {
  color: var(--fg);
  background: var(--border);
}

.nav-group__menu a.router-link-active {
  color: var(--fg);
  font-weight: 500;
}

.main {
  flex: 1;
  padding: clamp(1rem, 4vw, 1.5rem);
  display: grid;
  place-items: center;
}
</style>
