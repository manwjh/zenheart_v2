<script setup lang="ts">
</script>

<template>
  <section class="panel">
    <h1>Zenheart</h1>
    <p class="lead">A quiet place on the web.</p>
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
    <footer class="foot">2026</footer>
  </section>
</template>

<style scoped>
.panel {
  max-width: 28rem;
  text-align: center;
}

h1 {
  font-size: clamp(1.5rem, 4vw, 1.75rem);
  font-weight: 600;
  letter-spacing: 0.02em;
  margin: 0 0 0.5rem;
}

.lead {
  font-size: 0.95rem;
  color: var(--muted);
  font-weight: 400;
  margin: 0 0 1.75rem;
}

figure {
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
  font-size: 0.8125rem;
  color: var(--muted);
}
</style>
