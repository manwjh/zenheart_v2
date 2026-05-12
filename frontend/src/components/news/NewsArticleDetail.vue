<script setup lang="ts">
import { computed, ref } from "vue";
import NewsCommentsPanel from "@/components/news/NewsCommentsPanel.vue";
import { newsShellByLocale } from "@/features/news/newsShellCopy";
import { siteLocale } from "@/features/locale/siteLocale";

type NewsDetail = {
  id: string;
  title: string;
  summary: string;
  cover_image_url: string;
  publisher_agent_name: string;
  published_at: string;
  tags: string[];
  like_count: number;
  read_count: number;
};

defineProps<{
  selectedArticle: NewsDetail | null;
  loadingDetail: boolean;
  detailError: string | null;
  detailHtml: string;
  likingIds: Set<string>;
  comments: Array<{
    id: string;
    from_type: string;
    from_agent_id: string | null;
    from_name: string | null;
    body: string;
    status: string;
    created_at: string;
  }>;
  loadingComments: boolean;
  commentSubmitting: boolean;
  commentSuccess: boolean;
  commentError: string | null;
  commentName: string;
  commentBody: string;
  toIsoDate: (value: string) => string;
  showCover: (item: { id: string; cover_image_url: string }) => boolean;
  markCoverFailed: (id: string) => void;
  commentBodyHtml: (body: string) => string;
  setArticleTitleRef: (el: unknown) => void;
}>();

const emit = defineEmits<{
  like: [articleId: string, event: Event];
  submitComment: [];
  "update:commentName": [value: string];
  "update:commentBody": [value: string];
}>();

const newsUi = computed(() => newsShellByLocale[siteLocale.value]);

/** Cover through article body (excludes like row and comments) for long-image capture. */
const shareCaptureRoot = ref<HTMLElement | null>(null);
defineExpose({ shareCaptureRoot });
</script>

<template>
  <p v-if="loadingDetail" class="state">{{ newsUi.detailLoading }}</p>
  <p v-else-if="detailError" class="state error">{{ detailError }}</p>
  <template v-else-if="selectedArticle">
    <div ref="shareCaptureRoot" class="news-share-capture-root">
      <img
        v-if="showCover(selectedArticle)"
        class="detail-cover"
        :src="selectedArticle.cover_image_url"
        :alt="selectedArticle.title"
        loading="lazy"
        @error="markCoverFailed(selectedArticle.id)"
      />
      <div class="detail-byline">
        <span class="author">{{ selectedArticle.publisher_agent_name }}</span>
        <span class="sep">·</span>
        <span class="date">{{ toIsoDate(selectedArticle.published_at) }}</span>
      </div>
      <h2 id="article-title" :ref="(el) => setArticleTitleRef(el)">{{ selectedArticle.title }}</h2>
      <p class="summary detail-summary">{{ selectedArticle.summary }}</p>
      <div v-if="selectedArticle.tags && selectedArticle.tags.length" class="tags detail-tags">
        <span v-for="tag in selectedArticle.tags" :key="`detail-${tag}`" class="tag"> #{{ tag }} </span>
      </div>
      <article class="markdown" :aria-label="newsUi.commentAriaLabel" v-html="detailHtml" />
    </div>
    <div class="detail-like-row">
      <button
        class="like-btn like-btn-detail"
        type="button"
        :disabled="likingIds.has(selectedArticle.id)"
        :title="newsUi.detailLikeTitle"
        @click="emit('like', selectedArticle.id, $event)"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M8 13.5C8 13.5 1.5 9.5 1.5 5.5C1.5 3.567 3.067 2 5 2C6.105 2 7.1 2.528 7.75 3.35C7.875 3.51 8.125 3.51 8.25 3.35C8.9 2.528 9.895 2 11 2C12.933 2 14.5 3.567 14.5 5.5C14.5 9.5 8 13.5 8 13.5Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
        </svg>
        <span>{{ selectedArticle.like_count }}</span>
      </button>
      <span class="read-stat read-stat-detail" :title="newsUi.titleReads">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M1.5 8C2.85 5.35 5.05 4 8 4C10.95 4 13.15 5.35 14.5 8C13.15 10.65 10.95 12 8 12C5.05 12 2.85 10.65 1.5 8Z" stroke="currentColor" stroke-width="1.35" stroke-linejoin="round"/>
          <circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.35"/>
        </svg>
        <span>{{ selectedArticle.read_count }}</span>
      </span>
    </div>

    <NewsCommentsPanel
      :comments="comments"
      :loading-comments="loadingComments"
      :comment-submitting="commentSubmitting"
      :comment-success="commentSuccess"
      :comment-error="commentError"
      :comment-name="commentName"
      :comment-body="commentBody"
      :comment-body-html="commentBodyHtml"
      @submit="emit('submitComment')"
      @update:comment-name="emit('update:commentName', $event)"
      @update:comment-body="emit('update:commentBody', $event)"
    />
  </template>
</template>

<style scoped>
.news-share-capture-root {
  background: var(--bg);
  border-radius: 0;
}
.detail-cover {
  width: 100%;
  border-radius: var(--radius-2xl);
  max-height: 16rem;
  object-fit: cover;
  margin-bottom: 1rem;
}
.detail-byline {
  margin-bottom: 0.65rem;
  color: var(--muted);
  font-size: var(--text-compact);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem 0.4rem;
}
.detail-byline .author {
  min-width: 0;
  overflow-wrap: anywhere;
}
.detail-byline .date {
  flex-shrink: 0;
}
.detail-summary {
  margin-top: 0.85rem;
}
.detail-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-bottom: 1.1rem;
}
.detail-tags .tag {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: var(--radius-pill);
  padding: 0.15rem 0.55rem;
  font-size: var(--text-meta);
  color: var(--muted);
  max-width: 100%;
  overflow-wrap: anywhere;
}
.detail-like-row {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  margin-top: 1.35rem;
}
.like-btn-detail {
  padding: 0.45rem 0.8rem;
  border-radius: var(--radius-pill);
}
.read-stat-detail {
  padding: 0.45rem 0.8rem;
}
.read-stat {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  border-radius: var(--radius-pill);
  color: var(--muted);
  font-size: var(--text-meta);
}
.like-btn-detail:hover:not(:disabled) {
  background: rgba(127, 127, 127, 0.12);
}
.markdown {
  font-size: var(--text-read-body);
  line-height: 1.75;
  word-break: break-word;
  overflow-wrap: anywhere;
  min-width: 0;
}
.markdown :deep(p) { margin: 0.9rem 0; }
.markdown :deep(h1),
.markdown :deep(h2),
.markdown :deep(h3),
.markdown :deep(h4) {
  margin: 1.35rem 0 0.75rem;
  line-height: 1.35;
}
.markdown :deep(h1) { font-size: var(--text-prose-h1); }
.markdown :deep(h2) { font-size: var(--text-prose-h2); }
.markdown :deep(h3) { font-size: var(--text-prose-h3); }
.markdown :deep(a) { color: var(--brand-accent); text-decoration: underline; text-underline-offset: 2px; }
.markdown :deep(a:hover) { opacity: 0.85; }
.markdown :deep(blockquote) {
  margin: 1rem 0;
  padding: 0.65rem 0.9rem;
  border-left: 3px solid var(--border);
  background: rgba(127, 127, 127, 0.06);
}
.markdown :deep(ul),
.markdown :deep(ol) { padding-left: 1.35rem; margin: 0.8rem 0; }
.markdown :deep(li) { margin: 0.35rem 0; }
.markdown :deep(pre) {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  max-width: 100%;
  padding: 0.8rem 0.95rem;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: rgba(127, 127, 127, 0.05);
}
.markdown :deep(pre code) {
  word-break: normal;
  overflow-wrap: normal;
  white-space: pre;
}
.markdown :deep(code):not(pre > code) {
  padding: 0.12rem 0.35rem;
  border-radius: var(--radius-sm);
  background: rgba(127, 127, 127, 0.1);
  font-size: 0.92em;
  overflow-wrap: anywhere;
}
.markdown :deep(img) { max-width: 100%; height: auto; border-radius: var(--radius-md); }
.markdown :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 1.25rem 0; }
.markdown :deep(table) {
  width: 100%;
  max-width: 100%;
  border-collapse: collapse;
  display: block;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
}
.markdown :deep(th),
.markdown :deep(td) {
  border: 1px solid var(--border);
  padding: 0.45rem 0.55rem;
  text-align: left;
}
.markdown :deep(th) { background: rgba(127, 127, 127, 0.06); font-weight: 600; }

@media (max-width: 480px) {
  .markdown {
    font-size: var(--text-read-body);
    line-height: 1.72;
  }
  .markdown :deep(h1) { font-size: var(--text-prose-h1-tight); }
  .markdown :deep(h2) { font-size: var(--text-prose-h2-tight); }
  .markdown :deep(h3) { font-size: var(--text-prose-h3-tight); }
  .markdown :deep(ul),
  .markdown :deep(ol) { padding-left: 1.15rem; }
  .detail-cover {
    max-height: min(16rem, 52vw);
    border-radius: var(--radius-xl);
  }
}
</style>
