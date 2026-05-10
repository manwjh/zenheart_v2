<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { formatErrorDetail } from "@/features/faq/faqHelpers";
import { siteLocale } from "@/features/locale/siteLocale";

type DocItem = { slug: string; title: string };

type FaqFeedbackRow = {
  id: string;
  title: string;
  status: string;
  doc_slug?: string | null;
  created_at: string;
  updated_at: string;
  reviewed_at?: string | null;
};

const props = defineProps<{
  docs: DocItem[];
}>();

const ui = computed(() => faqUiByLocale[siteLocale.value]);
const title = ref("");
const body = ref("");
const docSlug = ref("");
const contact = ref("");
const busy = ref(false);
const loading = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);
const historyError = ref<string | null>(null);
const submissions = ref<FaqFeedbackRow[]>([]);

const statusLabel: Record<string, string> = {
  pending: "Pending",
  claimed: "Claimed",
  changes_requested: "Changes requested",
  accepted: "Accepted",
  rejected: "Rejected",
  published: "Published",
};

const statusLabelZh: Record<string, string> = {
  pending: "待审核",
  claimed: "评审中",
  changes_requested: "需修改",
  accepted: "已接受",
  rejected: "已拒绝",
  published: "已发布",
};

function displayStatus(status: string) {
  if (siteLocale.value === "zh") return statusLabelZh[status] ?? status;
  return statusLabel[status] ?? status;
}

function formatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}

async function loadHistory() {
  loading.value = true;
  historyError.value = null;
  try {
    const { response, data } = await fetchJsonObject("/v2/faq/feedback?limit=50");
    if (!response.ok) {
      historyError.value = formatErrorDetail(data.detail) || response.statusText;
      return;
    }
    const raw = data.submissions;
    submissions.value = Array.isArray(raw) ? (raw as FaqFeedbackRow[]) : [];
  } catch (e) {
    historyError.value = e instanceof Error ? e.message : ui.value.networkError;
  } finally {
    loading.value = false;
  }
}

async function submitFeedback() {
  message.value = null;
  error.value = null;
  busy.value = true;
  try {
    const { response, data } = await fetchJsonObject("/v2/faq/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: title.value.trim(),
        body: body.value.trim(),
        doc_slug: docSlug.value || null,
        page_url: typeof window !== "undefined" ? window.location.href : null,
        contact: contact.value.trim() || null,
      }),
    });
    if (!response.ok) {
      error.value = formatErrorDetail(data.detail) || response.statusText;
      return;
    }
    message.value =
      typeof data.message === "string" ? data.message : ui.value.feedbackSubmitted;
    title.value = "";
    body.value = "";
    docSlug.value = "";
    contact.value = "";
    await loadHistory();
  } catch (e) {
    error.value = e instanceof Error ? e.message : ui.value.networkError;
  } finally {
    busy.value = false;
  }
}

onMounted(loadHistory);
</script>

<template>
  <section id="feedback" class="card">
    <header class="card-header">
      <h2 class="card-title">{{ ui.feedbackTitle }}</h2>
      <p class="card-desc">{{ ui.feedbackDesc }}</p>
    </header>

    <div class="card-body feedback-grid">
      <form class="feedback-form" @submit.prevent="submitFeedback">
        <label class="field">
          <span class="label">{{ ui.feedbackFieldTitle }}</span>
          <input
            v-model="title"
            class="input"
            type="text"
            minlength="3"
            maxlength="200"
            required
            :placeholder="ui.feedbackTitlePlaceholder"
          />
        </label>

        <label class="field">
          <span class="label">{{ ui.feedbackFieldDoc }}</span>
          <select v-model="docSlug" class="input">
            <option value="">{{ ui.feedbackDocAny }}</option>
            <option v-for="doc in props.docs" :key="doc.slug" :value="doc.slug">
              {{ doc.title }}
            </option>
          </select>
        </label>

        <label class="field">
          <span class="label">{{ ui.feedbackFieldBody }}</span>
          <textarea
            v-model="body"
            class="textarea"
            rows="5"
            minlength="10"
            maxlength="8000"
            required
            :placeholder="ui.feedbackBodyPlaceholder"
          />
        </label>

        <label class="field">
          <span class="label">{{ ui.feedbackFieldContact }}</span>
          <input
            v-model="contact"
            class="input"
            type="text"
            maxlength="320"
            :placeholder="ui.feedbackContactPlaceholder"
          />
        </label>

        <div class="form-footer">
          <button class="submit-btn" type="submit" :disabled="busy">
            {{ busy ? ui.feedbackSubmitting : ui.feedbackSubmit }}
          </button>
          <p v-if="message" class="status ok" role="status">{{ message }}</p>
          <p v-if="error" class="status err" role="alert">{{ error }}</p>
        </div>
      </form>

      <div class="feedback-history">
        <div class="feedback-history-head">
          <h3 class="feedback-history-title">{{ ui.feedbackHistoryTitle }}</h3>
          <button class="action-btn" type="button" :disabled="loading" @click="loadHistory">
            {{ loading ? ui.feedbackLoading : ui.feedbackRefresh }}
          </button>
        </div>
        <p class="feedback-history-note">{{ ui.feedbackHistoryNote }}</p>
        <p v-if="historyError" class="status err" role="alert">{{ historyError }}</p>
        <div v-if="!loading && submissions.length === 0" class="feedback-empty">
          {{ ui.feedbackHistoryEmpty }}
        </div>
        <ul v-else class="feedback-list" role="list">
          <li v-for="row in submissions" :key="row.id" class="feedback-item">
            <div class="feedback-item-main">
              <span class="feedback-item-title">{{ row.title }}</span>
              <span v-if="row.doc_slug" class="feedback-doc">{{ row.doc_slug }}</span>
            </div>
            <div class="feedback-item-meta">
              <span class="feedback-status" :data-status="row.status">
                {{ displayStatus(row.status) }}
              </span>
              <span>{{ formatDate(row.updated_at || row.created_at) }}</span>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<style scoped>
.feedback-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(18rem, 0.9fr); gap: 1rem; align-items: start; }
.feedback-form { display: flex; flex-direction: column; gap: 0.85rem; }
.feedback-history { border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); border-radius: var(--radius-lg); padding: 0.9rem; background: rgba(0, 0, 0, 0.018); }
.feedback-history-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.35rem; }
.feedback-history-title { margin: 0; font-size: var(--text-emphasis); font-weight: 600; }
.feedback-history-note { margin: 0 0 0.75rem; color: var(--muted, #5c5c5c); font-size: var(--text-compact); line-height: 1.5; }
.feedback-empty { padding: 1.25rem 0.5rem; color: var(--muted, #5c5c5c); font-size: var(--text-ui); }
.feedback-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.feedback-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.75rem; padding: 0.7rem 0.75rem; border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); border-radius: var(--radius-md); background: color-mix(in srgb, var(--bg) 94%, var(--fg) 6%); }
.feedback-item-main { min-width: 0; display: flex; flex-direction: column; gap: 0.25rem; }
.feedback-item-title { font-weight: 600; font-size: var(--text-ui); overflow: hidden; text-overflow: ellipsis; }
.feedback-doc { align-self: flex-start; font-family: "SF Mono", ui-monospace, Consolas, monospace; font-size: var(--text-meta); color: var(--muted, #5c5c5c); }
.feedback-item-meta { flex-shrink: 0; display: flex; flex-direction: column; align-items: flex-end; gap: 0.25rem; font-size: var(--text-meta); color: var(--muted, #5c5c5c); }
.feedback-status { padding: 0.12rem 0.45rem; border-radius: var(--radius-pill); border: 1px solid var(--border, rgba(0, 0, 0, 0.1)); color: var(--fg); background: rgba(0, 0, 0, 0.035); }
.feedback-status[data-status="accepted"],
.feedback-status[data-status="published"] { color: #15803d; border-color: rgba(21, 128, 61, 0.35); background: rgba(21, 128, 61, 0.08); }
.feedback-status[data-status="rejected"] { color: #b91c1c; border-color: rgba(185, 28, 28, 0.3); background: rgba(185, 28, 28, 0.07); }
.feedback-status[data-status="changes_requested"] { color: #a16207; border-color: rgba(161, 98, 7, 0.35); background: rgba(161, 98, 7, 0.08); }
.action-btn { border: 1px solid var(--border, rgba(0, 0, 0, 0.12)); border-radius: var(--radius-md); background: transparent; color: inherit; font: inherit; font-size: var(--text-meta); line-height: 1; padding: 0.42rem 0.62rem; cursor: pointer; }
.action-btn:disabled { opacity: 0.6; cursor: default; }
@media (max-width: 860px) {
  .feedback-grid { grid-template-columns: 1fr; }
  .feedback-item { flex-direction: column; }
  .feedback-item-meta { align-items: flex-start; }
}
</style>
