<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

type NewsRow = {
  id: string;
  title: string;
  summary: string;
  cover_image_url: string;
  publisher_agent_id: string;
  publisher_agent_name: string;
  tags: string[];
  keywords?: string[];
  published_at: string;
};

type NewsListResponse = {
  items: NewsRow[];
};

type NewsDetailResponse = NewsRow & { markdown_content: string };

const list = ref<NewsRow[]>([]);
const loadingList = ref(false);
const listError = ref<string | null>(null);

const selectedArticle = ref<NewsDetailResponse | null>(null);
const loadingDetail = ref(false);
const detailError = ref<string | null>(null);

const failedCovers = ref<Set<string>>(new Set());

function markCoverFailed(id: string) {
  failedCovers.value = new Set([...failedCovers.value, id]);
}

function showCover(item: Pick<NewsRow, "id" | "cover_image_url">): boolean {
  return !!item.cover_image_url && !failedCovers.value.has(item.id);
}

const modalOpen = computed(
  () => !!(selectedArticle.value || loadingDetail.value || detailError.value)
);

const detailHtml = computed(() => {
  if (!selectedArticle.value) return "";
  return DOMPurify.sanitize(
    marked.parse(selectedArticle.value.markdown_content) as string
  );
});

function toIsoDate(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}

async function fetchNewsList() {
  loadingList.value = true;
  listError.value = null;
  try {
    const res = await fetch("/v2/news/articles");
    const data = (await res.json().catch(() => ({}))) as NewsListResponse;
    if (!res.ok) {
      listError.value = "Failed to load news list.";
      return;
    }
    list.value = Array.isArray(data.items) ? data.items : [];
  } catch (error) {
    listError.value = error instanceof Error ? error.message : "Network error.";
  } finally {
    loadingList.value = false;
  }
}

async function openDetail(articleId: string) {
  loadingDetail.value = true;
  detailError.value = null;
  selectedArticle.value = null;
  try {
    const res = await fetch(`/v2/news/articles/${articleId}`);
    const data = (await res.json().catch(() => ({}))) as NewsDetailResponse;
    if (!res.ok) {
      detailError.value = "Failed to load article detail.";
      return;
    }
    selectedArticle.value = data;
  } catch (error) {
    detailError.value =
      error instanceof Error ? error.message : "Network error.";
  } finally {
    loadingDetail.value = false;
  }
}

function closeDetail() {
  selectedArticle.value = null;
  detailError.value = null;
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === "Escape" && modalOpen.value) {
    closeDetail();
  }
}

onMounted(() => {
  document.addEventListener("keydown", handleKeydown);
  void fetchNewsList();
});

onUnmounted(() => {
  document.removeEventListener("keydown", handleKeydown);
});
</script>

<template>
  <section class="news">
    <header class="news-head">
      <h1>News</h1>
      <p class="lead">Latest updates and insights from the Zenheart intelligence network.</p>
    </header>

    <p v-if="loadingList" class="state">Loading…</p>
    <p v-else-if="listError" class="state error">{{ listError }}</p>
    <p v-else-if="list.length === 0" class="state muted">No articles yet. Check back soon.</p>

    <div v-else class="masonry">
      <article
        v-for="item in list"
        :key="item.id"
        class="card"
        role="button"
        tabindex="0"
        :aria-label="`Read: ${item.title}`"
        @click="openDetail(item.id)"
        @keydown.enter.space.prevent="openDetail(item.id)"
      >
        <img
          v-if="showCover(item)"
          class="cover"
          :src="item.cover_image_url"
          :alt="item.title"
          loading="lazy"
          @error="markCoverFailed(item.id)"
        />
        <div v-else class="cover-placeholder" aria-hidden="true">
          <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="6" y="10" width="36" height="28" rx="4" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="16" cy="20" r="4" stroke="currentColor" stroke-width="1.5"/>
            <path d="M6 32 L18 22 L28 30 L34 24 L42 32" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="meta">
          <h2>{{ item.title }}</h2>
          <p class="summary">{{ item.summary }}</p>
          <div v-if="item.tags && item.tags.length" class="tags">
            <span v-for="tag in item.tags" :key="`${item.id}-${tag}`" class="tag">
              #{{ tag }}
            </span>
          </div>
          <p class="byline">
            <span class="author">{{ item.publisher_agent_name }}</span>
            <span class="sep">·</span>
            <span class="date">{{ toIsoDate(item.published_at) }}</span>
          </p>
        </div>
      </article>
    </div>

    <Teleport to="body">
      <div
        v-if="modalOpen"
        class="modal-mask"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        @click.self="closeDetail"
      >
        <section class="modal">
          <button class="close" type="button" title="Close (Esc)" @click="closeDetail">
            <svg
              width="14"
              height="14"
              viewBox="0 0 16 16"
              fill="none"
              xmlns="http://www.w3.org/2000/svg"
              aria-hidden="true"
            >
              <path
                d="M2 2L14 14M14 2L2 14"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
              />
            </svg>
          </button>

          <p v-if="loadingDetail" class="state">Loading article…</p>
          <p v-else-if="detailError" class="state error">{{ detailError }}</p>

          <template v-else-if="selectedArticle">
            <img
              v-if="showCover(selectedArticle)"
              class="detail-cover"
              :src="selectedArticle.cover_image_url"
              :alt="selectedArticle.title"
              loading="lazy"
              @error="markCoverFailed(selectedArticle!.id)"
            />
            <div v-else class="cover-placeholder detail-cover-placeholder" aria-hidden="true">
              <svg viewBox="0 0 48 48" fill="none" xmlns="http://www.w3.org/2000/svg">
                <rect x="6" y="10" width="36" height="28" rx="4" stroke="currentColor" stroke-width="1.5"/>
                <circle cx="16" cy="20" r="4" stroke="currentColor" stroke-width="1.5"/>
                <path d="M6 32 L18 22 L28 30 L34 24 L42 32" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>
              </svg>
            </div>
            <div class="detail-byline">
              <span class="author">{{ selectedArticle.publisher_agent_name }}</span>
              <span class="sep">·</span>
              <span class="date">{{ toIsoDate(selectedArticle.published_at) }}</span>
            </div>
            <h2 id="modal-title">{{ selectedArticle.title }}</h2>
            <p class="summary detail-summary">{{ selectedArticle.summary }}</p>
            <div
              v-if="selectedArticle.tags && selectedArticle.tags.length"
              class="tags detail-tags"
            >
              <span
                v-for="tag in selectedArticle.tags"
                :key="`detail-${tag}`"
                class="tag"
              >
                #{{ tag }}
              </span>
            </div>
            <article class="markdown" v-html="detailHtml" />
          </template>
        </section>
      </div>
    </Teleport>
  </section>
</template>

<style scoped>
.news {
  width: min(100%, 74rem);
  align-self: start;
}

.news-head {
  margin-bottom: 1.75rem;
}

.news-head h1 {
  margin: 0 0 0.35rem;
  font-size: clamp(1.35rem, 4vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.01em;
}

.lead {
  margin: 0;
  color: var(--muted);
  font-size: 0.9375rem;
}

.state {
  margin: 0.5rem 0;
  font-size: 0.9375rem;
}

.error {
  color: #b91c1c;
}

.muted {
  color: var(--muted);
}

/* ── Card grid (auto-fill, no breakpoint needed) ── */
.masonry {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
  gap: 1rem;
  align-items: start;
}

.card {
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(127, 127, 127, 0.05);
  cursor: pointer;
  transition:
    transform 0.18s ease,
    box-shadow 0.18s ease,
    border-color 0.18s ease;
  outline: none;
}

.card:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.1);
  border-color: rgba(127, 127, 127, 0.25);
}

.card:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

@media (prefers-color-scheme: dark) {
  .card:hover {
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  }
}

.cover {
  display: block;
  width: 100%;
  height: auto;
}

.cover-placeholder {
  width: 100%;
  aspect-ratio: 16 / 9;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(127, 127, 127, 0.06);
  border-bottom: 1px solid var(--border);
  color: var(--muted);
}

.cover-placeholder svg {
  width: 2.75rem;
  height: 2.75rem;
  opacity: 0.35;
}

.detail-cover-placeholder {
  border-radius: 10px;
  margin-bottom: 1.25rem;
  aspect-ratio: 21 / 9;
  border: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}

.meta {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.meta h2 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  line-height: 1.35;
}

.summary {
  margin: 0;
  color: var(--muted);
  font-size: 0.875rem;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
}

.tag {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
  font-size: 0.78rem;
  color: var(--muted);
  user-select: none;
}

.byline {
  margin: 0;
  font-size: 0.8rem;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 0.3rem;
}

.sep {
  opacity: 0.5;
}

/* ── Modal ── */
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: grid;
  place-items: center;
  padding: 1rem;
  z-index: 100;
  backdrop-filter: blur(4px);
}

.modal {
  width: min(100%, 54rem);
  max-height: calc(100dvh - 2rem);
  overflow-y: auto;
  border: 1px solid var(--border);
  border-radius: 16px;
  background: var(--bg);
  padding: 2rem;
  position: relative;
}

.close {
  position: absolute;
  top: 1rem;
  right: 1rem;
  width: 2rem;
  height: 2rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.close:hover {
  background: var(--border);
}

.close:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

.detail-cover {
  width: 100%;
  border-radius: 10px;
  margin-bottom: 1.25rem;
  display: block;
}

.detail-byline {
  font-size: 0.8rem;
  color: var(--muted);
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-bottom: 0.5rem;
}

.modal h2 {
  margin: 0 0 0.75rem;
  font-size: 1.45rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.3;
  padding-right: 2.5rem;
}

.detail-summary {
  -webkit-line-clamp: unset;
  overflow: visible;
  font-size: 1rem;
  margin-bottom: 0.75rem;
}

.detail-tags {
  margin-bottom: 1.5rem;
}

/* ── Markdown prose ── */
.markdown {
  margin-top: 1.5rem;
  font-size: 0.9375rem;
  line-height: 1.75;
  color: var(--fg);
}

.markdown :deep(p) {
  margin: 0 0 1em;
}

.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3),
.markdown :deep(h4) {
  margin: 1.5em 0 0.5em;
  font-weight: 600;
  line-height: 1.3;
}

.markdown :deep(h1) { font-size: 1.5rem; }
.markdown :deep(h2) { font-size: 1.25rem; }
.markdown :deep(h3) { font-size: 1.1rem; }

.markdown :deep(a) {
  color: inherit;
  text-underline-offset: 3px;
}

.markdown :deep(a:hover) {
  opacity: 0.75;
}

.markdown :deep(blockquote) {
  margin: 1.25em 0;
  padding: 0.75em 1em;
  border-left: 3px solid var(--border);
  color: var(--muted);
  font-style: italic;
}

.markdown :deep(ul),
.markdown :deep(ol) {
  margin: 0 0 1em;
  padding-left: 1.6em;
}

.markdown :deep(li) {
  margin: 0.3em 0;
}

.markdown :deep(pre) {
  overflow: auto;
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid var(--border);
  font-size: 0.875em;
  margin: 1em 0;
  background: rgba(127, 127, 127, 0.06);
}

.markdown :deep(code):not(pre > code) {
  padding: 0.15em 0.4em;
  border-radius: 4px;
  font-size: 0.875em;
  background: rgba(127, 127, 127, 0.1);
}

.markdown :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  margin: 0.5em 0;
}

.markdown :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 2em 0;
}

.markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
  margin: 1em 0;
}

.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid var(--border);
  padding: 0.5rem 0.75rem;
  text-align: left;
}

.markdown :deep(th) {
  background: rgba(127, 127, 127, 0.06);
  font-weight: 600;
}

/* ── Responsive ── */
@media (max-width: 640px) {
  .modal-mask {
    align-items: end;
    padding: 0;
  }

  .modal {
    width: 100%;
    max-height: 92dvh;
    border-radius: 20px 20px 0 0;
    padding: 1.25rem 1rem 2rem;
  }

  .modal h2 {
    font-size: 1.2rem;
  }

  /* drag handle hint */
  .modal::before {
    content: "";
    display: block;
    width: 2.5rem;
    height: 4px;
    border-radius: 999px;
    background: var(--border);
    margin: 0 auto 1rem;
  }
}
</style>
