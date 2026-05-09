<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <div class="lab-layout">
    <nav class="lab-layout__tabs" aria-label="Lab sections">
      <RouterLink to="/lab/wall" class="lab-layout__tab" active-class="lab-layout__tab--active">
        Wall
      </RouterLink>
      <RouterLink to="/lab/game" class="lab-layout__tab" active-class="lab-layout__tab--active">
        Game
      </RouterLink>
    </nav>
    <RouterView />
  </div>
</template>

<style scoped>
.lab-layout {
  width: min(100%, 74rem);
  margin: 0 auto;
  align-self: start;
  min-width: 0;
}

.lab-layout__tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.75rem;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}

.lab-layout__tab {
  padding: 0.35rem 0.75rem;
  border-radius: var(--radius-md, 0.5rem);
  border: 1px solid var(--border);
  color: var(--muted);
  text-decoration: none;
  font-size: var(--text-subtitle);
  font-weight: 500;
  white-space: nowrap;
  transition: background 0.12s, color 0.12s, border-color 0.12s;
}

.lab-layout__tab:hover,
.lab-layout__tab:focus-visible {
  color: var(--brand-accent);
  border-color: rgba(var(--brand-rgb), 0.35);
  outline: none;
}

.lab-layout__tab--active {
  color: var(--brand-accent);
  font-weight: 600;
  border-color: rgba(var(--brand-rgb), 0.45);
  background: rgba(var(--brand-rgb), 0.08);
}

@media (max-width: 640px), (orientation: portrait) {
  .lab-layout {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
  }
}
</style>
