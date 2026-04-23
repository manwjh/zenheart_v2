<script setup lang="ts">
withDefaults(
  defineProps<{
    eyebrow?: string;
    docUrl: string;
    linkText: string;
  }>(),
  { eyebrow: undefined }
);
</script>

<template>
  <aside class="feature-intro" aria-label="AI agent information">
    <p v-if="eyebrow" class="feature-intro__eyebrow">{{ eyebrow }}</p>
    <div class="feature-intro__block">
      <p class="feature-intro__label">To the AI agent</p>
      <p class="feature-intro__text">
        <slot />
        <a
          class="feature-intro__link"
          :href="docUrl"
          target="_blank"
          rel="noopener noreferrer"
        >{{ linkText }}</a>
      </p>
    </div>
  </aside>
</template>

<style scoped>
.feature-intro {
  margin: 0 0 1.1rem;
  padding: 1rem 1.15rem;
  border-radius: 12px;
  border: 1px solid var(--border);
  background: rgba(127, 127, 127, 0.05);
}

.feature-intro__eyebrow {
  margin: 0 0 0.5rem;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--muted);
}

.feature-intro__block {
  padding-left: 0.5rem;
  border-left: 3px solid rgba(99, 102, 241, 0.45);
}

.feature-intro__label {
  margin: 0 0 0.25rem;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: var(--muted);
}

.feature-intro__text {
  margin: 0;
  font-size: 0.9rem;
  line-height: 1.55;
  color: var(--fg);
}

.feature-intro__link {
  color: inherit;
  font-weight: 600;
  text-decoration: underline;
  text-underline-offset: 2px;
  word-break: break-all;
}

.feature-intro__link:hover {
  opacity: 0.85;
}
</style>
