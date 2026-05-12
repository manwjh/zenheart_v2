<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { closeFaqDocModal, faqDocModalSlug } from "@/features/faq/faqDocModal";
import { faqDocRawPath, fetchFaqMarkdownAsHtml } from "@/features/faq/useFaqMarkdownPreview";

/**
 * Global FAQ markdown preview: rendered body + toolbar download / open raw / close.
 * Opens when `faqDocModalSlug` is set (see `openFaqDocModal` in `faqDocModal.ts`).
 */

const html = ref("");
const loading = ref(false);
const error = ref<string | null>(null);
const closeBtnRef = ref<HTMLButtonElement | null>(null);

const slug = computed(() => faqDocModalSlug.value);

const rawUrl = computed(() => (slug.value ? faqDocRawPath(slug.value) : ""));
const downloadName = computed(() => (slug.value ? `${slug.value}.md` : "document.md"));

function onGlobalKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && slug.value) {
    e.preventDefault();
    closeFaqDocModal();
  }
}

watch(
  slug,
  async (next, _prev, onCleanup) => {
    if (!next) {
      html.value = "";
      error.value = null;
      loading.value = false;
      return;
    }
    const ac = new AbortController();
    onCleanup(() => ac.abort());
    loading.value = true;
    error.value = null;
    html.value = "";
    try {
      html.value = await fetchFaqMarkdownAsHtml(next, ac.signal);
    } catch (e) {
      if (ac.signal.aborted) return;
      error.value = e instanceof Error ? e.message : "Failed to load document.";
    } finally {
      if (!ac.signal.aborted) loading.value = false;
    }
    await nextTick();
    closeBtnRef.value?.focus();
  },
  { flush: "post" },
);

watch(slug, (next) => {
  if (typeof document === "undefined") return;
  document.body.style.overflow = next ? "hidden" : "";
});

onMounted(() => {
  document.addEventListener("keydown", onGlobalKeydown);
});
onUnmounted(() => {
  document.removeEventListener("keydown", onGlobalKeydown);
  document.body.style.overflow = "";
});

function onBackdropClick(e: MouseEvent): void {
  if (e.target === e.currentTarget) closeFaqDocModal();
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="slug"
      class="faq-md-modal-backdrop"
      role="presentation"
      @click="onBackdropClick"
    >
      <div
        id="faq-markdown-preview-modal"
        class="faq-md-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="slug ?? undefined"
      >
        <header class="faq-md-modal-toolbar">
          <code class="faq-md-modal-slug" :title="slug ?? undefined">{{ slug }}</code>
          <div class="faq-md-modal-actions">
            <a
              class="faq-md-modal-icon-btn"
              :href="rawUrl"
              :download="downloadName"
              :title="'Download ' + downloadName"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M12 3v12m0 0l4-4m-4 4L8 11" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M5 15v3a2 2 0 002 2h10a2 2 0 002-2v-3" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>
              </svg>
            </a>
            <a
              class="faq-md-modal-icon-btn"
              :href="rawUrl"
              target="_blank"
              rel="noopener noreferrer"
              title="Open raw Markdown in a new tab"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M14 3h7v7M10 14L21 3M21 3v6M21 3h-6" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M18 13v6a2 2 0 01-2 2H6a2 2 0 01-2-2V8a2 2 0 012-2h6" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </a>
            <button
              ref="closeBtnRef"
              type="button"
              class="faq-md-modal-icon-btn"
              title="Close"
              @click="closeFaqDocModal"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>
              </svg>
            </button>
          </div>
        </header>
        <div class="faq-md-modal-scroll">
          <p v-if="loading" class="faq-md-modal-status">Loading...</p>
          <p v-else-if="error" class="faq-md-modal-status faq-md-modal-status--err" role="alert">
            {{ error }}
          </p>
          <div v-else class="markdown-body" v-html="html" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.faq-md-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 400;
  display: grid;
  place-items: center;
  padding: max(0.75rem, env(safe-area-inset-top, 0px)) max(0.75rem, env(safe-area-inset-right, 0px))
    max(0.75rem, env(safe-area-inset-bottom, 0px)) max(0.75rem, env(safe-area-inset-left, 0px));
  background: rgba(0, 0, 0, 0.45);
  backdrop-filter: blur(4px);
}

.faq-md-modal {
  display: flex;
  flex-direction: column;
  width: min(100%, 44rem);
  max-height: min(88vh, 52rem);
  border-radius: var(--radius-md, 10px);
  border: 1px solid var(--border);
  background: var(--bg);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.28);
  min-height: 0;
  overflow: hidden;
}

.faq-md-modal-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.65rem 0.55rem 0.85rem;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--fg) 4%, var(--bg));
}

.faq-md-modal-slug {
  font-size: var(--text-mono-tight, 0.8rem);
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.faq-md-modal-actions {
  display: flex;
  align-items: center;
  gap: 0.15rem;
  flex-shrink: 0;
}

.faq-md-modal-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.35rem;
  height: 2.35rem;
  margin: 0;
  padding: 0;
  border: none;
  border-radius: var(--radius-md, 8px);
  background: transparent;
  color: var(--muted);
  cursor: pointer;
  text-decoration: none;
  transition: background 0.12s, color 0.12s;
}

.faq-md-modal-icon-btn:hover {
  background: color-mix(in srgb, var(--fg) 8%, var(--bg));
  color: var(--fg);
}

.faq-md-modal-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1rem 1.1rem 1.25rem;
  -webkit-overflow-scrolling: touch;
}

.faq-md-modal-status {
  margin: 0;
  font-size: var(--text-ui);
  color: var(--muted);
}

.faq-md-modal-status--err {
  color: var(--error);
}

.markdown-body {
  font-size: var(--text-emphasis);
  line-height: 1.7;
  color: inherit;
  min-width: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.markdown-body :deep(p) {
  margin: 0 0 0.8rem;
}

.markdown-body :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.markdown-body :deep(code) {
  font-size: var(--text-compact);
  font-family: "SF Mono", ui-monospace, Consolas, monospace;
  padding: 0.1em 0.38em;
  border-radius: var(--radius-xs, 4px);
  background: rgba(0, 0, 0, 0.06);
}

@media (prefers-color-scheme: dark) {
  .markdown-body :deep(code) {
    background: rgba(255, 255, 255, 0.08);
  }
}
</style>
