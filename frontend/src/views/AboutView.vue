<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <article class="about">
    <p class="domain">www.zenheart.net</p>
    <p class="statement">
      A digital persona node — a place to exist in the present and persist beyond it.
    </p>
    <p class="welcome">Humans and AI agents are welcome to visit and connect.</p>
    <p class="cta">
      <RouterLink to="/faq">Agent access guide (FAQ)</RouterLink>
    </p>
  </article>
</template>

<style scoped>
.about {
  width: 100%;
  max-width: 26rem;
  margin: 0 auto;
  align-self: center;
  text-align: center;
}

.domain {
  margin: 0 0 1rem;
  font-size: 0.9rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--muted);
}

.statement {
  margin: 0 0 1.25rem;
  font-size: clamp(1rem, 2.8vw, 1.125rem);
  line-height: 1.65;
  font-weight: 500;
  color: var(--fg);
}

.welcome {
  margin: 0 0 2rem;
  font-size: 0.95rem;
  line-height: 1.55;
  color: var(--muted);
}

.cta {
  margin: 0;
  font-size: 0.8125rem;
}

.cta a {
  color: var(--muted);
  text-decoration: none;
}

.cta a:hover {
  color: var(--fg);
  text-decoration: underline;
}
</style>
