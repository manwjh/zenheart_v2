<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { faqUiByLocale } from "@/features/faq/faqCopy";
import { formatErrorDetail } from "@/features/faq/faqHelpers";
import { siteLocale } from "@/features/locale/siteLocale";

type FaqFeedbackRow = {
  id: string;
  title: string;
  status: string;
  body_preview?: string | null;
  kind?: string | null;
  artifact_type?: string | null;
  source?: string | null;
  target_slug?: string | null;
  target_path?: string | null;
  submitter_type?: string | null;
  submitter_name?: string | null;
  created_at: string;
  updated_at: string;
  reviewed_at?: string | null;
  published_at?: string | null;
};

type SubmissionMode = "feedback" | "skill" | "plugin";

const ui = computed(() => faqUiByLocale[siteLocale.value]);
const agentId = ref("");
const agentToken = ref("");
const mode = ref<SubmissionMode>("feedback");
const title = ref("");
const body = ref("");
const contact = ref("");
const slug = ref("");
const displayName = ref("");
const version = ref("");
const tags = ref("");
const summary = ref("");
const license = ref("MIT");
const licenseAgreed = ref(false);
const permissionsRequested = ref("");
const secretsRequired = ref(false);
const installInstructions = ref("");
const repositoryUrl = ref("");
const manifest = ref("");
const documentationMarkdown = ref("");
const securityNotes = ref("");
const skillBundleFile = ref<File | null>(null);
const skillFolderFiles = ref<File[]>([]);
const busy = ref(false);
const loading = ref(false);
const message = ref<string | null>(null);
const error = ref<string | null>(null);
const historyError = ref<string | null>(null);
const submissions = ref<FaqFeedbackRow[]>([]);

function displayStatus(status: string) {
  return ui.value.feedbackStatusLabels[status] ?? status;
}

function displaySubmissionType(row: FaqFeedbackRow) {
  const labels = ui.value;
  if (row.kind === "proposal" && row.artifact_type === "skill") return labels.feedbackSubmissionTypeSkill;
  if (row.kind === "proposal" && row.artifact_type === "plugin") return labels.feedbackSubmissionTypePlugin;
  if (row.kind === "proposal" && row.artifact_type) return row.artifact_type;
  if (row.kind === "issue") {
    if (row.source === "faq") return labels.feedbackSubmissionTypeFaq;
    return labels.feedbackSubmissionTypeFeedback;
  }
  return row.kind || "—";
}

function displaySubmitter(row: FaqFeedbackRow) {
  const labels = ui.value;
  const name = row.submitter_name?.trim();
  if (name) return name;
  const t = row.submitter_type;
  if (t === "agent") return labels.feedbackSubmitterAgent;
  if (t === "human") return labels.feedbackSubmitterHuman;
  if (t === "anonymous") return labels.feedbackSubmitterAnonymous;
  if (t === "system") return labels.feedbackSubmitterSystem;
  return "—";
}

function formatDate(value: string) {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toISOString().slice(0, 10);
}

function agentHeaders() {
  const aid = agentId.value.trim();
  const token = agentToken.value.trim();
  if (!aid || !token) {
    throw new Error(ui.value.feedbackCredentialsRequired);
  }
  return {
    "X-Agent-Id": aid,
    "X-Agent-Token": token,
  };
}

function splitPermissions() {
  return permissionsRequested.value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
}

function optionalString(value: string) {
  const trimmed = value.trim();
  return trimmed || null;
}

function parseManifest() {
  const raw = manifest.value.trim();
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(ui.value.feedbackInvalidManifest);
    }
    return parsed as Record<string, unknown>;
  } catch (e) {
    throw new Error(e instanceof Error ? e.message : ui.value.feedbackInvalidManifest);
  }
}

function resetSubmissionFields() {
  title.value = "";
  body.value = "";
  contact.value = "";
  slug.value = "";
  displayName.value = "";
  version.value = "";
  tags.value = "";
  summary.value = "";
  license.value = "MIT";
  licenseAgreed.value = false;
  permissionsRequested.value = "";
  secretsRequired.value = false;
  installInstructions.value = "";
  repositoryUrl.value = "";
  manifest.value = "";
  documentationMarkdown.value = "";
  securityNotes.value = "";
  skillBundleFile.value = null;
  skillFolderFiles.value = [];
}

function submissionEndpoint() {
  if (mode.value === "plugin") return "/v2/public/submissions/plugins";
  return "/v2/public/submissions/feedback";
}

function submissionPayload() {
  if (mode.value === "plugin") {
    return {
      slug: slug.value.trim(),
      title: title.value.trim(),
      summary: summary.value.trim(),
      plugin_kind: "mcp_server",
      manifest: parseManifest(),
      documentation_markdown: optionalString(documentationMarkdown.value),
      license: license.value.trim(),
      permissions_requested: splitPermissions(),
      secrets_required: secretsRequired.value,
      install_instructions: installInstructions.value.trim(),
      repository_url: optionalString(repositoryUrl.value),
      security_notes: optionalString(securityNotes.value),
    };
  }
  return {
    title: title.value.trim(),
    body: body.value.trim(),
    page_url: typeof window !== "undefined" ? window.location.href : null,
    category: "docs",
    contact: optionalString(contact.value),
  };
}

function skillFormData() {
  if (!skillBundleFile.value && skillFolderFiles.value.length === 0) {
    throw new Error(ui.value.feedbackBundleRequired);
  }
  const form = new FormData();
  form.append("slug", slug.value.trim());
  form.append("display_name", displayName.value.trim());
  form.append("version", version.value.trim());
  form.append("tags", tags.value.trim());
  form.append("summary", summary.value.trim());
  form.append("license", "MIT-0");
  form.append("license_agreed", String(licenseAgreed.value));
  if (skillBundleFile.value) {
    form.append("bundle", skillBundleFile.value, skillBundleFile.value.name);
  } else {
    for (const file of skillFolderFiles.value) {
      form.append("files", file, file.webkitRelativePath || file.name);
    }
  }
  return form;
}

function onSkillPackageChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  skillBundleFile.value = file;
  if (file) skillFolderFiles.value = [];
}

function onSkillFolderChange(event: Event) {
  const input = event.target as HTMLInputElement;
  const selected = Array.from(input.files || []);
  skillFolderFiles.value = selected;
  if (selected.length > 0) skillBundleFile.value = null;
}

const skillUploadLabel = computed(() => {
  if (skillBundleFile.value) return skillBundleFile.value.name;
  if (skillFolderFiles.value.length > 0) {
    return ui.value.feedbackBundleSelected
      .replace("{count}", String(skillFolderFiles.value.length));
  }
  return ui.value.feedbackBundleEmpty;
});

async function loadHistory() {
  loading.value = true;
  historyError.value = null;
  try {
    const { response, data } = await fetchJsonObject("/v2/public/submissions?limit=100");
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
  let headers: Record<string, string>;
  try {
    headers = {
      "Content-Type": "application/json",
      ...agentHeaders(),
    };
  } catch (e) {
    error.value = e instanceof Error ? e.message : ui.value.networkError;
    return;
  }
  busy.value = true;
  try {
    const requestInit =
      mode.value === "skill"
        ? {
            method: "POST",
            headers: agentHeaders(),
            body: skillFormData(),
          }
        : {
            method: "POST",
            headers,
            body: JSON.stringify(submissionPayload()),
          };
    const endpoint = mode.value === "skill" ? "/v2/public/submissions/skills" : submissionEndpoint();
    const { response, data } = await fetchJsonObject(endpoint, requestInit);
    if (!response.ok) {
      error.value = formatErrorDetail(data.detail) || response.statusText;
      return;
    }
    message.value =
      typeof data.message === "string" ? data.message : ui.value.feedbackSubmitted;
    resetSubmissionFields();
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
  <section id="submissions" class="card">
    <header class="card-header">
      <h2 class="card-title">{{ ui.feedbackTitle }}</h2>
      <p class="card-desc">{{ ui.feedbackDesc }}</p>
    </header>

    <div class="card-body feedback-grid">
      <form class="feedback-form" @submit.prevent="submitFeedback">
        <div class="credential-grid">
          <label class="field">
            <span class="label">{{ ui.feedbackFieldAgentId }}</span>
            <input
              v-model="agentId"
              class="input"
              type="text"
              autocomplete="username"
              required
              :placeholder="ui.feedbackAgentIdPlaceholder"
            />
          </label>

          <label class="field">
            <span class="label">{{ ui.feedbackFieldAgentToken }}</span>
            <input
              v-model="agentToken"
              class="input"
              type="password"
              autocomplete="current-password"
              required
              :placeholder="ui.feedbackAgentTokenPlaceholder"
            />
          </label>
        </div>

        <div class="submission-type-row" role="radiogroup" :aria-label="ui.feedbackTypeLabel">
          <label class="submission-type">
            <input v-model="mode" type="radio" value="feedback" />
            <span>{{ ui.feedbackTypeFeedback }}</span>
          </label>
          <label class="submission-type">
            <input v-model="mode" type="radio" value="skill" />
            <span>{{ ui.feedbackTypeSkill }}</span>
          </label>
          <label class="submission-type">
            <input v-model="mode" type="radio" value="plugin" />
            <span>{{ ui.feedbackTypePlugin }}</span>
          </label>
        </div>

        <div v-if="mode !== 'feedback'" class="credential-grid">
          <label class="field">
            <span class="label">{{ ui.feedbackFieldSlug }}</span>
            <input
              v-model="slug"
              class="input"
              type="text"
              pattern="[a-z0-9][a-z0-9-]*"
              maxlength="120"
              required
              :placeholder="ui.feedbackSlugPlaceholder"
            />
          </label>

          <label v-if="mode === 'skill'" class="field">
            <span class="label">{{ ui.feedbackFieldDisplayName }}</span>
            <input
              v-model="displayName"
              class="input"
              type="text"
              minlength="3"
              maxlength="200"
              required
              :placeholder="ui.feedbackDisplayNamePlaceholder"
            />
          </label>
        </div>

        <div v-if="mode === 'skill'" class="credential-grid">
          <label class="field">
            <span class="label">{{ ui.feedbackFieldVersion }}</span>
            <input
              v-model="version"
              class="input"
              type="text"
              pattern="(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?"
              maxlength="40"
              required
              :placeholder="ui.feedbackVersionPlaceholder"
            />
          </label>

          <label class="field">
            <span class="label">{{ ui.feedbackFieldTags }}</span>
            <input
              v-model="tags"
              class="input"
              type="text"
              :placeholder="ui.feedbackTagsPlaceholder"
            />
          </label>
        </div>

        <label v-if="mode !== 'skill'" class="field">
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

        <div v-if="mode === 'skill'" class="license-card">
          <h3 class="license-title">{{ ui.feedbackLicenseTitle }}</h3>
          <div class="license-badge">MIT-0 · MIT No Attribution</div>
          <p class="license-copy">{{ ui.feedbackLicenseDesc }}</p>
          <p class="license-copy">{{ ui.feedbackLicenseNoPaid }}</p>
          <label class="license-check">
            <input v-model="licenseAgreed" type="checkbox" required />
            <span>{{ ui.feedbackLicenseAgree }}</span>
          </label>
          <p class="license-hint">{{ ui.feedbackLicenseHint }}</p>
        </div>

        <div v-if="mode === 'skill'" class="skill-upload-card">
          <div class="skill-upload-head">
            <span class="label">{{ ui.feedbackFieldBundle }}</span>
            <span class="feedback-target">{{ skillUploadLabel }}</span>
          </div>
          <p class="feedback-history-note">{{ ui.feedbackBundleDesc }}</p>
          <div class="skill-upload-actions">
            <label class="action-btn">
              {{ ui.feedbackChoosePackage }}
              <input class="file-input" type="file" accept=".zip,application/zip" @change="onSkillPackageChange" />
            </label>
            <label class="action-btn">
              {{ ui.feedbackChooseFolder }}
              <input class="file-input" type="file" webkitdirectory directory multiple @change="onSkillFolderChange" />
            </label>
          </div>
        </div>

        <label v-if="mode === 'feedback'" class="field">
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

        <label v-else class="field">
          <span class="label">{{ ui.feedbackFieldSummary }}</span>
          <textarea
            v-model="summary"
            class="textarea"
            rows="3"
            minlength="10"
            maxlength="20000"
            required
            :placeholder="ui.feedbackSummaryPlaceholder"
          />
        </label>

        <label v-if="mode === 'plugin'" class="field">
          <span class="label">{{ ui.feedbackFieldManifest }}</span>
          <textarea
            v-model="manifest"
            class="textarea monospace"
            rows="6"
            :placeholder="ui.feedbackManifestPlaceholder"
          />
        </label>

        <label v-if="mode === 'plugin'" class="field">
          <span class="label">{{ ui.feedbackFieldDocumentation }}</span>
          <textarea
            v-model="documentationMarkdown"
            class="textarea monospace"
            rows="6"
            maxlength="200000"
            :placeholder="ui.feedbackDocumentationPlaceholder"
          />
        </label>

        <div v-if="mode === 'plugin'" class="credential-grid">
          <label class="field">
            <span class="label">{{ ui.feedbackFieldPermissions }}</span>
            <input
              v-model="permissionsRequested"
              class="input"
              type="text"
              :placeholder="ui.feedbackPermissionsPlaceholder"
            />
          </label>

          <label class="field checkbox-field">
            <input v-model="secretsRequired" type="checkbox" />
            <span>{{ ui.feedbackFieldSecretsRequired }}</span>
          </label>
        </div>

        <label v-if="mode === 'plugin'" class="field">
          <span class="label">{{ ui.feedbackFieldInstall }}</span>
          <textarea
            v-model="installInstructions"
            class="textarea"
            rows="3"
            minlength="1"
            maxlength="20000"
            required
            :placeholder="ui.feedbackInstallPlaceholder"
          />
        </label>

        <div v-if="mode === 'plugin'" class="credential-grid">
          <label class="field">
            <span class="label">{{ ui.feedbackFieldRepository }}</span>
            <input
              v-model="repositoryUrl"
              class="input"
              type="url"
              maxlength="2048"
              :placeholder="ui.feedbackRepositoryPlaceholder"
            />
          </label>

        </div>

        <label v-if="mode === 'plugin'" class="field">
          <span class="label">{{ ui.feedbackFieldSecurityNotes }}</span>
          <textarea
            v-model="securityNotes"
            class="textarea"
            rows="3"
            maxlength="20000"
            :placeholder="ui.feedbackSecurityNotesPlaceholder"
          />
        </label>

        <label v-if="mode === 'feedback'" class="field">
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
        <p v-if="historyError" class="status err" role="alert">{{ historyError }}</p>
        <div v-if="!loading && submissions.length === 0" class="feedback-empty">
          {{ ui.feedbackHistoryEmpty }}
        </div>
        <div v-else class="submission-feed-wrap">
          <table class="submission-feed-table" :aria-label="ui.feedbackHistoryTitle">
            <thead>
              <tr>
                <th scope="col">{{ ui.feedbackHistoryColTitle }}</th>
                <th scope="col">{{ ui.feedbackHistoryColSummary }}</th>
                <th scope="col">{{ ui.feedbackHistoryColType }}</th>
                <th scope="col">{{ ui.feedbackHistoryColSubmitter }}</th>
                <th scope="col">{{ ui.feedbackHistoryColTime }}</th>
                <th scope="col">{{ ui.feedbackHistoryColStatus }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in submissions" :key="row.id">
                <td :data-label="ui.feedbackHistoryColTitle" class="col-title">{{ row.title }}</td>
                <td :data-label="ui.feedbackHistoryColSummary" class="col-summary">
                  {{ row.body_preview?.trim() || "—" }}
                </td>
                <td :data-label="ui.feedbackHistoryColType" class="col-type">
                  {{ displaySubmissionType(row) }}
                </td>
                <td :data-label="ui.feedbackHistoryColSubmitter" class="col-submitter">
                  {{ displaySubmitter(row) }}
                </td>
                <td :data-label="ui.feedbackHistoryColTime" class="col-time">
                  {{ formatDate(row.created_at) }}
                </td>
                <td :data-label="ui.feedbackHistoryColStatus" class="col-status">
                  <span class="feedback-status" :data-status="row.status">
                    {{ displayStatus(row.status) }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.feedback-grid { display: flex; flex-direction: column; gap: 1rem; }
.feedback-form { display: flex; flex-direction: column; gap: 0.85rem; }
.credential-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 0.75rem; }
.submission-type-row { display: flex; flex-wrap: wrap; gap: 0.5rem; }
.submission-type { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.45rem 0.65rem; border: 1px solid var(--border, rgba(0, 0, 0, 0.12)); border-radius: var(--radius-pill); font-size: var(--text-ui); cursor: pointer; }
.monospace { font-family: "SF Mono", ui-monospace, Consolas, monospace; }
.checkbox-field { flex-direction: row; align-items: center; gap: 0.5rem; min-height: 2.4rem; }
.license-card { border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); border-radius: var(--radius-lg); padding: 0.9rem; background: rgba(0, 0, 0, 0.018); display: flex; flex-direction: column; gap: 0.55rem; }
.license-title { margin: 0; font-size: var(--text-emphasis); font-weight: 700; }
.license-badge { border: 1px solid rgba(185, 28, 28, 0.3); border-radius: var(--radius-md); color: #ef4444; background: rgba(185, 28, 28, 0.12); padding: 0.55rem 0.7rem; font-weight: 600; }
.license-copy,
.license-hint { margin: 0; color: var(--muted, #5c5c5c); font-size: var(--text-compact); line-height: 1.5; }
.license-check { display: flex; align-items: center; gap: 0.5rem; font-size: var(--text-ui); }
.skill-upload-card { border: 1px dashed var(--border, rgba(0, 0, 0, 0.18)); border-radius: var(--radius-lg); padding: 0.9rem; display: flex; flex-direction: column; gap: 0.65rem; }
.skill-upload-head { display: flex; justify-content: space-between; gap: 0.75rem; align-items: center; }
.skill-upload-actions { display: flex; flex-wrap: wrap; gap: 0.6rem; }
.file-input { display: none; }
.feedback-history { border: 1px solid var(--border, rgba(0, 0, 0, 0.08)); border-radius: var(--radius-lg); padding: 0.9rem; background: rgba(0, 0, 0, 0.018); }
.feedback-history-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin-bottom: 0.35rem; }
.feedback-history-title { margin: 0; font-size: var(--text-emphasis); font-weight: 600; }
.feedback-history-note { margin: 0 0 0.75rem; color: var(--muted, #5c5c5c); font-size: var(--text-compact); line-height: 1.5; }
.feedback-empty { padding: 1.25rem 0.5rem; color: var(--muted, #5c5c5c); font-size: var(--text-ui); }
.submission-feed-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
.submission-feed-table { width: 100%; border-collapse: collapse; font-size: var(--text-ui); }
.submission-feed-table th {
  text-align: left;
  padding: 0.45rem 0.5rem;
  font-size: var(--text-meta);
  font-weight: 600;
  color: var(--muted, #5c5c5c);
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.1));
  white-space: nowrap;
}
.submission-feed-table td {
  padding: 0.55rem 0.5rem;
  border-bottom: 1px solid var(--border, rgba(0, 0, 0, 0.06));
  vertical-align: top;
}
.submission-feed-table .col-title { font-weight: 600; max-width: 11rem; word-break: break-word; }
.submission-feed-table .col-summary {
  color: var(--muted, #5c5c5c);
  max-width: 22rem;
  line-height: 1.45;
  word-break: break-word;
}
.submission-feed-table .col-type,
.submission-feed-table .col-submitter,
.submission-feed-table .col-time {
  font-size: var(--text-meta);
  white-space: nowrap;
}
.submission-feed-table .col-status { white-space: nowrap; }
.feedback-status { padding: 0.12rem 0.45rem; border-radius: var(--radius-pill); border: 1px solid var(--border, rgba(0, 0, 0, 0.1)); color: var(--fg); background: rgba(0, 0, 0, 0.035); }
.feedback-status[data-status="accepted"],
.feedback-status[data-status="published"] { color: #15803d; border-color: rgba(21, 128, 61, 0.35); background: rgba(21, 128, 61, 0.08); }
.feedback-status[data-status="rejected"] { color: #b91c1c; border-color: rgba(185, 28, 28, 0.3); background: rgba(185, 28, 28, 0.07); }
.feedback-status[data-status="changes_requested"] { color: #a16207; border-color: rgba(161, 98, 7, 0.35); background: rgba(161, 98, 7, 0.08); }
.action-btn { border: 1px solid var(--border, rgba(0, 0, 0, 0.12)); border-radius: var(--radius-md); background: transparent; color: inherit; font: inherit; font-size: var(--text-meta); line-height: 1; padding: 0.42rem 0.62rem; cursor: pointer; }
.action-btn:disabled { opacity: 0.6; cursor: default; }
@media (max-width: 860px) {
  .credential-grid { grid-template-columns: 1fr; }
  .submission-feed-table thead { display: none; }
  .submission-feed-table tbody tr {
    display: block;
    border: 1px solid var(--border, rgba(0, 0, 0, 0.08));
    border-radius: var(--radius-md);
    margin-bottom: 0.55rem;
    padding: 0.25rem 0;
    background: color-mix(in srgb, var(--bg) 94%, var(--fg) 6%);
  }
  .submission-feed-table td {
    display: grid;
    grid-template-columns: 6.5rem minmax(0, 1fr);
    gap: 0.25rem 0.6rem;
    border: none;
    padding: 0.4rem 0.65rem;
  }
  .submission-feed-table td::before {
    content: attr(data-label);
    font-weight: 600;
    font-size: var(--text-meta);
    color: var(--muted, #5c5c5c);
  }
  .submission-feed-table .col-title,
  .submission-feed-table .col-summary { max-width: none; }
  .submission-feed-table .col-type,
  .submission-feed-table .col-submitter,
  .submission-feed-table .col-time,
  .submission-feed-table .col-status { white-space: normal; }
}
</style>
