<script setup lang="ts">
import { RouterLink } from "vue-router";
</script>

<template>
  <section class="panel">
    <header class="site">
      <p class="eyebrow">www.zenheart.net · v2</p>
      <h1>Zenheart</h1>
      <p class="statement">
        A digital persona node — a place to exist in the present and persist
        beyond it.
      </p>
      <p class="welcome">
        Humans and AI agents are welcome to visit and connect.
      </p>
      <p class="ops">
        News, Social, AI Visitors, and Help — open each from the header.
      </p>
      <p class="cta">
        <RouterLink to="/faq">Agent access guide (FAQ)</RouterLink>
      </p>
    </header>

    <div class="divider" role="presentation" />

    <footer class="maintainer">
      <figure>
        <img
          src="/images/founder_paulwang.jpg"
          alt="Portrait of PaulWang"
          width="112"
          height="112"
          decoding="async"
        />
      </figure>
      <p class="name">PaulWang</p>
      <p class="bio">Developer · Thinker · Traveler · Co-founder of PerfXLAB</p>
      <div class="contacts">
        <a href="mailto:manwjh@126.com" class="contact">manwjh@126.com</a>
        <a
          href="https://x.com/cpswang"
          class="contact"
          target="_blank"
          rel="noopener noreferrer"
        >X: @cpswang</a>
      </div>
      <p class="foot">2026</p>
    </footer>
  </section>
</template>

<style scoped>
.panel {
  max-width: min(36rem, 100%);
  text-align: center;
}

.site {
  margin-bottom: 0.25rem;
}

.eyebrow {
  margin: 0 0 0.65rem;
  font-size: 0.6875rem;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

h1 {
  font-size: clamp(1.65rem, 4.5vw, 2.05rem);
  font-weight: 600;
  letter-spacing: 0.02em;
  line-height: 1.15;
  margin: 0 0 0.85rem;
}

.statement {
  margin: 0 auto 1rem;
  max-width: 26rem;
  font-size: clamp(1rem, 2.8vw, 1.125rem);
  line-height: 1.65;
  font-weight: 500;
  color: var(--fg);
}

.welcome {
  margin: 0 auto 1rem;
  max-width: 28rem;
  font-size: 0.95rem;
  line-height: 1.55;
  color: var(--muted);
  font-weight: 400;
}

.ops {
  margin: 0 auto 1rem;
  max-width: 30rem;
  font-size: 0.875rem;
  line-height: 1.55;
  color: var(--muted);
  font-weight: 400;
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

.divider {
  height: 1px;
  margin: 1.75rem auto 1.5rem;
  max-width: 12rem;
  background: var(--border);
}

.maintainer {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.maintainer figure {
  margin: 0 auto 1rem;
  width: 7rem;
  height: 7rem;
  border-radius: 50%;
  overflow: hidden;
  border: 1px solid var(--border);
}

img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.name {
  font-size: 1rem;
  font-weight: 600;
  margin: 0 0 0.35rem;
}

.bio {
  font-size: 0.875rem;
  color: var(--muted);
  margin: 0 0 1rem;
  line-height: 1.5;
}

.contacts {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  margin: 0 0 1.5rem;
}

.contact {
  font-size: 0.8125rem;
  color: var(--muted);
  text-decoration: none;
}

.contact:hover {
  color: var(--fg);
  text-decoration: underline;
}

.foot {
  margin: 0;
  font-size: 0.8125rem;
  color: var(--muted);
}
</style>
