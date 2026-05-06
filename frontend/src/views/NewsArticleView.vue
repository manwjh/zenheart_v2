<script lang="ts">
export default { name: "NewsArticleView" };
</script>

<script setup lang="ts">
import type { ComponentPublicInstance } from "vue";
import { computed, nextTick, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import NewsArticleDetail from "@/components/news/NewsArticleDetail.vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import {
  buildNewsShareImageFilename,
  captureNewsArticleDomToPngWithDeadline,
  deliverNewsArticlePng,
  waitForCaptureImages,
} from "@/features/news/captureNewsShareImage";
import { consumeNewsOpenFromList } from "@/features/news/newsFromListNavigation";
import { toIsoDate } from "@/features/news/newsHelpers";
import type { NewsArticleDetailPayload } from "@/features/news/newsTypes";
import { renderNewsMarkdown } from "@/features/news/renderNewsMarkdown";
import { runNewsArticleShare } from "@/features/news/runNewsArticleShare";
import { useArticleCover } from "@/features/news/useArticleCover";
import { useNewsArticleLike } from "@/features/news/useNewsArticleLike";
import { useNewsComments } from "@/features/news/useNewsComments";

const props = defineProps<{
  articleId: string;
}>();

const router = useRouter();

type ArticleDetailExposed = { shareCaptureRoot: HTMLElement | null };
const articleDetailRef = ref<(ComponentPublicInstance & ArticleDetailExposed) | null>(null);

const selectedArticle = ref<NewsArticleDetailPayload | null>(null);
const loadingDetail = ref(true);
const detailError = ref<string | null>(null);
const { markCoverFailed, showCover, resetFailedCovers } = useArticleCover();

const { likingIds, likeArticle } = useNewsArticleLike((articleId, likeCount) => {
  if (selectedArticle.value?.id === articleId) {
    selectedArticle.value = { ...selectedArticle.value, like_count: likeCount };
  }
});

const articleTitleRef = ref<HTMLElement | null>(null);
const headerTitleVisible = ref(false);
let titleObserver: IntersectionObserver | null = null;
/** Ignores stale responses when `articleId` changes quickly. */
let loadSeq = 0;

function setArticleTitleRef(el: unknown) {
  articleTitleRef.value = el instanceof HTMLElement ? el : null;
}

const isWechatBrowser =
  typeof navigator !== "undefined" &&
  /micromessenger/i.test(navigator.userAgent || "");

const toastVisible = ref(false);
const toastText = ref("");
const toastKind = ref<"error" | "info">("error");
const copiedState = ref(false);
const longImageBusy = ref(false);
let toastTimer: ReturnType<typeof setTimeout> | null = null;
let shareCopyTimer: ReturnType<typeof setTimeout> | null = null;

function flashCopied() {
  copiedState.value = true;
  if (shareCopyTimer) clearTimeout(shareCopyTimer);
  shareCopyTimer = setTimeout(() => {
    copiedState.value = false;
    shareCopyTimer = null;
  }, 2500);
}

const {
  comments,
  loadingComments,
  commentForm,
  commentSubmitting,
  commentSuccess,
  commentError,
  fetchComments,
  submitComment,
  commentBodyHtml,
  resetCommentState,
} = useNewsComments(selectedArticle);

const detailHtml = computed(() => {
  if (!selectedArticle.value) return "";
  return renderNewsMarkdown(selectedArticle.value.markdown_content);
});

async function loadArticle(articleId: string) {
  const seq = ++loadSeq;

  if (
    isWechatBrowser &&
    typeof window !== "undefined" &&
    window.parent === window
  ) {
    const sharePath = `/v2/share/news/${articleId}`;
    if (window.location.pathname !== sharePath) {
      window.location.replace(`${window.location.origin}${sharePath}`);
      return;
    }
  }

  loadingDetail.value = true;
  detailError.value = null;
  selectedArticle.value = null;
  resetCommentState();
  try {
    const { response: res, data } = await fetchJsonObject(`/v2/news/articles/${articleId}`);
    if (seq !== loadSeq) return;
    if (!res.ok) {
      detailError.value =
        res.status === 404 ? "Article not found." : "Failed to load article detail.";
      return;
    }
    selectedArticle.value = data as NewsArticleDetailPayload;
    void fetchComments(articleId);
  } catch (error) {
    if (seq !== loadSeq) return;
    detailError.value =
      error instanceof Error ? error.message : "Network error.";
  } finally {
    if (seq === loadSeq) {
      loadingDetail.value = false;
    }
  }
}

function goBackToList() {
  if (consumeNewsOpenFromList(props.articleId)) {
    void router.back();
    return;
  }
  void router.push({ name: "news" });
}

async function shareArticle() {
  if (!selectedArticle.value) return;
  await runNewsArticleShare(selectedArticle.value, {
    isWechatBrowser,
    flashCopied,
    showErrorToast,
  });
}

async function shareLongImage() {
  if (!selectedArticle.value || longImageBusy.value) return;
  const articleIdAtStart = props.articleId;
  const articleSnapshot = selectedArticle.value;
  await nextTick();
  const root = articleDetailRef.value?.shareCaptureRoot;
  if (!(root instanceof HTMLElement)) {
    showErrorToast("Content not ready.");
    return;
  }
  if (articleIdAtStart !== props.articleId || selectedArticle.value?.id !== articleSnapshot.id) {
    return;
  }
  longImageBusy.value = true;
  try {
    await waitForCaptureImages(root);
    if (articleIdAtStart !== props.articleId || selectedArticle.value?.id !== articleSnapshot.id) {
      return;
    }
    const blob = await captureNewsArticleDomToPngWithDeadline(root);
    const filename = buildNewsShareImageFilename(articleSnapshot);
    const outcome = await deliverNewsArticlePng(blob, filename, articleSnapshot.title);
    if (outcome === "cancelled") return;
    if (articleIdAtStart !== props.articleId || selectedArticle.value?.id !== articleSnapshot.id) {
      return;
    }
    if (outcome === "shared") {
      showInfoToast("Image shared.");
    } else if (outcome === "clipboard") {
      showInfoToast("Image copied to clipboard.");
    } else {
      showInfoToast("Image downloaded.");
    }
  } catch (error) {
    if (articleIdAtStart !== props.articleId || selectedArticle.value?.id !== articleSnapshot.id) {
      return;
    }
    const msg =
      error instanceof Error
        ? error.message
        : typeof error === "string"
          ? error
          : "Could not create image.";
    showErrorToast(msg);
  } finally {
    longImageBusy.value = false;
  }
}

function showErrorToast(message: string) {
  toastKind.value = "error";
  toastText.value = message;
  toastVisible.value = true;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastVisible.value = false;
  }, 3200);
}

function showInfoToast(message: string) {
  toastKind.value = "info";
  toastText.value = message;
  toastVisible.value = true;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastVisible.value = false;
  }, 2800);
}

watch(selectedArticle, (val) => {
  titleObserver?.disconnect();
  headerTitleVisible.value = false;
  if (!val) return;
  nextTick(() => {
    const titleEl = articleTitleRef.value;
    if (!titleEl) return;
    titleObserver = new IntersectionObserver(
      ([entry]) => {
        headerTitleVisible.value = !entry.isIntersecting;
      },
      { root: null, threshold: 0, rootMargin: "-72px 0px 0px 0px" }
    );
    titleObserver.observe(titleEl);
  });
});

watch(
  () => props.articleId,
  (id) => {
    resetFailedCovers();
    if (id && isWechatBrowser && typeof window !== "undefined" && window.parent !== window) {
      const next = `${window.location.origin}/v2/share/news/${id}`;
      try {
        if (window.parent.location.href.split("#")[0] !== next) {
          window.parent.history.replaceState(null, "", next);
        }
      } catch {
        // cross-origin
      }
    }
    if (id) void loadArticle(id);
  },
  { immediate: true }
);

onUnmounted(() => {
  titleObserver?.disconnect();
  if (toastTimer) clearTimeout(toastTimer);
  if (shareCopyTimer) clearTimeout(shareCopyTimer);
});
</script>

<template>
  <section class="article-page" aria-labelledby="article-title">
    <div class="article-toolbar">
      <button class="btn-nav btn-back" type="button" title="Back to news list" @click="goBackToList">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>News</span>
      </button>

      <span
        class="header-title"
        :class="{ visible: headerTitleVisible && !!selectedArticle }"
        aria-hidden="true"
      >
        {{ selectedArticle?.title ?? "" }}
      </span>

      <div class="toolbar-actions">
        <button
          class="btn-nav btn-long-image"
          type="button"
          title="Save or share image"
          :disabled="!selectedArticle || loadingDetail || longImageBusy"
          @click="shareLongImage"
        >
          <svg
            v-if="longImageBusy"
            class="btn-long-image-spinner"
            width="16"
            height="16"
            viewBox="0 0 16 16"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <circle
              cx="8"
              cy="8"
              r="6"
              stroke="currentColor"
              stroke-width="1.75"
              stroke-linecap="round"
              fill="none"
              stroke-dasharray="28"
              stroke-dashoffset="8"
              opacity="0.9"
            />
          </svg>
          <svg
            v-else
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <rect x="2.5" y="3.5" width="11" height="9" rx="1.25" stroke="currentColor" stroke-width="1.5" />
            <path
              d="M2.5 11.5L5.5 8.5L8.25 11.25L10.75 8.75L13.5 11.5"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <circle cx="5.25" cy="6.25" r="1" fill="currentColor" />
          </svg>
          <span>Image</span>
        </button>
        <button
          class="btn-nav btn-share"
          type="button"
          :title="copiedState ? 'Copied' : 'Share article'"
          :disabled="!selectedArticle"
          @click="shareArticle"
        >
          <svg v-if="copiedState" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <path d="M3 8L6.5 11.5L13 4.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <circle cx="12" cy="3" r="1.5" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="12" cy="13" r="1.5" stroke="currentColor" stroke-width="1.5"/>
            <circle cx="4" cy="8" r="1.5" stroke="currentColor" stroke-width="1.5"/>
            <path d="M10.5 3.75L5.5 7.25M10.5 12.25L5.5 8.75" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
          <span class="btn-share-label">{{ copiedState ? "Copied" : "Share" }}</span>
        </button>
      </div>
    </div>

    <div
      v-if="toastVisible"
      class="article-toast"
      :class="{ 'article-toast--info': toastKind === 'info' }"
      role="status"
      aria-live="assertive"
    >
      {{ toastText }}
    </div>

    <div class="article-inner">
      <NewsArticleDetail
        ref="articleDetailRef"
        :selected-article="selectedArticle"
        :loading-detail="loadingDetail"
        :detail-error="detailError"
        :detail-html="detailHtml"
        :liking-ids="likingIds"
        :comments="comments"
        :loading-comments="loadingComments"
        :comment-submitting="commentSubmitting"
        :comment-success="commentSuccess"
        :comment-error="commentError"
        :comment-name="commentForm.name"
        :comment-body="commentForm.body"
        :to-iso-date="toIsoDate"
        :show-cover="showCover"
        :mark-cover-failed="markCoverFailed"
        :comment-body-html="commentBodyHtml"
        :set-article-title-ref="setArticleTitleRef"
        @like="likeArticle"
        @submit-comment="submitComment"
        @update:comment-name="commentForm.name = $event"
        @update:comment-body="commentForm.body = $event"
      />
    </div>
  </section>
</template>

<style scoped>
.article-page {
  width: min(100%, 46rem);
  max-width: 100%;
  min-width: 0;
  align-self: start;
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  background: var(--bg);
  box-shadow: 0 0 0 1px rgba(var(--brand-rgb), 0.04);
  overflow-x: clip;
}

.article-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem max(var(--layout-chrome-pad-x), env(safe-area-inset-left, 0px))
    0.75rem max(var(--layout-chrome-pad-x), env(safe-area-inset-right, 0px));
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter: blur(10px) saturate(150%);
  border-bottom: 1px solid var(--border);
  border-radius: var(--radius-card) var(--radius-card) 0 0;
}

.article-inner {
  padding: 1.35rem max(var(--layout-page-pad-x), env(safe-area-inset-right, 0px))
    calc(var(--layout-room-inner-pad-bottom) + env(safe-area-inset-bottom, 0px))
    max(var(--layout-page-pad-x), env(safe-area-inset-left, 0px));
}

.header-title {
  flex: 1;
  min-width: 0;
  text-align: center;
  font-size: var(--text-ui);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  opacity: 0;
  transform: translateY(4px);
  transition:
    opacity 0.22s ease,
    transform 0.22s ease;
  pointer-events: none;
}

.header-title.visible {
  opacity: 1;
  transform: translateY(0);
}

.btn-nav {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.35rem 0.65rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: inherit;
  font-size: var(--text-compact);
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  transition:
    background 0.15s ease,
    border-color 0.15s ease;
}

.btn-nav:hover {
  background: rgba(var(--brand-rgb), 0.1);
  border-color: rgba(var(--brand-rgb), 0.28);
}

.btn-nav:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}

.btn-nav:disabled {
  opacity: 0.4;
  cursor: default;
}

.toolbar-actions {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}

.btn-share {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
}

.btn-long-image-spinner {
  animation: long-image-spin 0.75s linear infinite;
}

@keyframes long-image-spin {
  to {
    transform: rotate(360deg);
  }
}

.article-toast {
  flex-shrink: 0;
  margin: 0 max(var(--layout-page-pad-x), env(safe-area-inset-right, 0px)) 0
    max(var(--layout-page-pad-x), env(safe-area-inset-left, 0px));
  padding: 0.45rem 0.75rem;
  border-radius: var(--radius-md);
  font-size: var(--text-compact);
  line-height: 1.35;
  text-align: center;
  color: var(--fg);
  background: rgba(220, 80, 80, 0.12);
  border: 1px solid rgba(220, 80, 80, 0.35);
}

.article-toast--info {
  background: rgba(var(--brand-rgb), 0.1);
  border: 1px solid rgba(var(--brand-rgb), 0.28);
}

.article-inner :deep(h2#article-title) {
  margin: 0 0 0.75rem;
  font-size: var(--text-article-title);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.28;
}

@media (max-width: 640px), (orientation: portrait) {
  .article-page {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
    border-radius: 0;
    border-left: none;
    border-right: none;
    box-shadow: none;
  }

  .article-toolbar {
    border-radius: 0;
  }

  .article-inner {
    padding: 1.1rem
      max(0.85rem, var(--layout-chrome-pad-x), env(safe-area-inset-right, 0px))
      calc(var(--layout-room-inner-pad-bottom-sm) + env(safe-area-inset-bottom, 0px))
      max(0.85rem, var(--layout-chrome-pad-x), env(safe-area-inset-left, 0px));
  }
}

@media (max-width: 640px) {
  .btn-nav span {
    display: none;
  }

  .btn-nav {
    padding: 0.35rem 0.5rem;
  }
}
</style>
