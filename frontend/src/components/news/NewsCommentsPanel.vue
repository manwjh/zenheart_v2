<script setup lang="ts">
import { computed } from "vue";
import { toIsoDate } from "@/features/news/newsHelpers";
import type { NewsCommentRow } from "@/features/news/useNewsComments";
import { newsShellByLocale } from "@/features/news/newsShellCopy";
import { siteLocale } from "@/features/locale/siteLocale";

const props = defineProps<{
  comments: NewsCommentRow[];
  loadingComments: boolean;
  commentSubmitting: boolean;
  commentSuccess: boolean;
  commentError: string | null;
  commentBody: string;
  commentName: string;
  commentBodyHtml: (body: string) => string;
}>();

const emit = defineEmits<{
  submit: [];
  "update:commentName": [value: string];
  "update:commentBody": [value: string];
}>();

const canSubmit = computed(() => !props.commentSubmitting && props.commentBody.trim().length > 0);

const newsUi = computed(() => newsShellByLocale[siteLocale.value]);
</script>

<template>
  <div class="comment-section">
    <h3 class="comment-heading">
      {{ newsUi.commentsHeading }}
      <span v-if="comments.length" class="comment-count">{{ comments.length }}</span>
    </h3>

    <div v-if="loadingComments" class="comment-loading">{{ newsUi.commentsLoading }}</div>
    <div v-else-if="comments.length" class="comment-list">
      <div v-for="c in comments" :key="c.id" class="comment-item">
        <div class="comment-meta">
          <span class="comment-author">{{ c.from_name || newsUi.commentAnonymous }}</span>
          <span class="comment-date">{{ toIsoDate(c.created_at) }}</span>
        </div>
        <p v-if="c.status === 'pending'" class="comment-body comment-body--pending">
          <strong>{{ newsUi.commentPendingReview }}</strong>
        </p>
        <p v-else class="comment-body" v-html="commentBodyHtml(c.body)"></p>
      </div>
    </div>
    <p v-else class="comment-empty">{{ newsUi.commentEmptyPrompt }}</p>

    <div class="comment-form-wrap">
      <div v-if="commentSuccess" class="comment-success">
        <svg width="15" height="15" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M3 8L6.5 11.5L13 4.5" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        {{ newsUi.commentSuccessPending }}
      </div>
      <form v-else class="comment-form" @submit.prevent="emit('submit')">
        <input
          :value="commentName"
          class="comment-input"
          type="text"
          :placeholder="newsUi.commentNamePh"
          maxlength="120"
          :disabled="commentSubmitting"
          @input="emit('update:commentName', ($event.target as HTMLInputElement).value)"
        />
        <textarea
          :value="commentBody"
          class="comment-textarea"
          :placeholder="newsUi.composePlaceholder"
          maxlength="2000"
          rows="3"
          required
          :disabled="commentSubmitting"
          @input="emit('update:commentBody', ($event.target as HTMLTextAreaElement).value)"
        />
        <div class="comment-form-footer">
          <p v-if="commentError" class="comment-err">{{ commentError }}</p>
          <button class="comment-submit" type="submit" :disabled="!canSubmit">
            {{ commentSubmitting ? newsUi.commentPostingVerb : newsUi.commentPostVerb }}
          </button>
        </div>
      </form>
    </div>
  </div>
</template>

<style scoped>
.comment-section {
  margin-top: 2.5rem;
  padding-top: 1.75rem;
  border-top: 1px solid var(--border);
}
.comment-heading {
  margin: 0 0 1.25rem;
  font-size: var(--text-body);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
.comment-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.4rem;
  height: 1.4rem;
  padding: 0 0.35rem;
  border-radius: var(--radius-pill);
  background: rgba(127, 127, 127, 0.12);
  font-size: var(--text-meta);
  font-weight: 500;
  color: var(--muted);
}
.comment-loading { font-size: var(--text-ui); color: var(--muted); margin-bottom: 1.25rem; }
.comment-empty { font-size: var(--text-ui); color: var(--muted); margin: 0 0 1.5rem; }
.comment-list { display: flex; flex-direction: column; gap: 1rem; margin-bottom: 1.75rem; }
.comment-item { padding: 0.875rem 1rem; border: 1px solid var(--border); border-radius: var(--radius-lg); background: rgba(127,127,127,0.03); }
.comment-meta { display: flex; align-items: baseline; gap: 0.5rem; margin-bottom: 0.4rem; }
.comment-author { font-size: var(--text-compact); font-weight: 600; }
.comment-date { font-size: var(--text-meta); color: var(--muted); }
.comment-body--pending { color: var(--text-muted, rgba(0, 0, 0, 0.55)); }
.comment-body { margin: 0; font-size: var(--text-ui); line-height: 1.6; color: var(--fg); white-space: pre-wrap; word-break: break-word; }
.comment-body :deep(.text-mention) { font-weight: 700; }
.comment-body :deep(.text-mention--valid) {
  color: #047857;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: rgba(4, 120, 101, 0.14);
  padding: 0.1em 0.32em;
  border-radius: 0.35em;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
@media (prefers-color-scheme: dark) {
  .comment-body :deep(.text-mention--valid) { color: #5eead4; background: rgba(45, 212, 191, 0.2); }
}
.comment-form-wrap { margin-top: 0.25rem; }
.comment-success {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius-lg);
  border: 1px solid rgba(60, 180, 100, 0.3);
  background: rgba(60, 180, 100, 0.07);
  color: rgb(40, 150, 80);
  font-size: var(--text-ui);
  font-weight: 500;
}
.comment-form { display: flex; flex-direction: column; gap: 0.6rem; }
.comment-input, .comment-textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--fg);
  font-size: var(--text-ui);
  font-family: inherit;
  transition: border-color 0.15s ease;
  resize: none;
}
.comment-input:focus, .comment-textarea:focus { outline: none; border-color: rgba(127, 127, 127, 0.5); }
.comment-input:disabled, .comment-textarea:disabled { opacity: 0.5; }
.comment-textarea { line-height: 1.55; }
.comment-form-footer { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
.comment-err { margin: 0; font-size: var(--text-compact); color: var(--error, #e05050); flex: 1; }
.comment-submit {
  min-width: 5.5rem;
  padding: 0.5rem 1.15rem;
  border: 1px solid rgba(59, 130, 246, 0.55);
  border-radius: var(--radius-md);
  background: rgba(59, 130, 246, 0.16);
  color: var(--fg);
  font-size: var(--text-compact);
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.12s ease;
}
.comment-submit:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.24);
  border-color: rgba(59, 130, 246, 0.75);
  transform: translateY(-1px);
}
.comment-submit:disabled { opacity: 0.4; cursor: default; }

@media (max-width: 480px) {
  .comment-section {
    margin-top: 2rem;
    padding-top: 1.35rem;
  }
  .comment-item {
    padding: 0.65rem 0.75rem;
  }
  .comment-meta {
    flex-wrap: wrap;
    gap: 0.25rem 0.5rem;
  }
  .comment-success {
    flex-wrap: wrap;
    font-size: var(--text-compact);
  }
}
</style>
