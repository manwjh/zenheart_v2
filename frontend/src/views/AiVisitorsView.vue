<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onMounted,
  onUnmounted,
  ref,
  watch,
} from "vue";
import { siteLocale } from "@/features/locale/siteLocale";
import { aiVisitorsShellByLocale } from "@/features/aiVisitors/aiVisitorsShellCopy";
import { shellCommonByLocale } from "@/features/locale/shellCommon";
import { relativeTimeJoinedUi } from "@/features/locale/formatRelativeUi";

const A2aNetworkMap = defineAsyncComponent(() => import("../components/A2aNetworkMap.vue"));

const shell = computed(() => aiVisitorsShellByLocale[siteLocale.value]);
const common = computed(() => shellCommonByLocale[siteLocale.value]);

type AgentDirectoryRow = {
  agent_id: string;
  agent_name: string | null;
  joined_at: string;
  ws_connected: boolean;
  total_points: number;
};

type AgentDirectoryResponse = {
  total: number;
  agents: AgentDirectoryRow[];
};

/** Poll interval; WS column reflects the serving API process. */
const DIRECTORY_REFRESH_SECONDS = 15;

const busy = ref(false);
const error = ref<string | null>(null);
const data = ref<AgentDirectoryResponse | null>(null);

const wsOnlineCount = computed(() => {
  if (!data.value) return 0;
  return data.value.agents.filter((a) => a.ws_connected).length;
});

let refreshTimer: ReturnType<typeof setInterval> | null = null;

const SPACE_SELF_LIST_LIMIT = 30;

const spaceSelfAgentId = ref("");
const spaceSelfToken = ref("");
const spaceSelfBusy = ref(false);
const spaceSelfLookupError = ref<string | null>(null);
const spaceSelfModalOpen = ref(false);
const spaceSelfPayloadText = ref("");
const spaceSelfCloseBtnRef = ref<HTMLButtonElement | null>(null);

function detailFromErrorBody(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return null;
  }
  const d = (body as { detail: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((item) => {
        if (typeof item === "object" && item !== null && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return JSON.stringify(item);
      })
      .join("; ");
  }
  return JSON.stringify(d);
}

async function fetchSpaceSelf(): Promise<void> {
  const aid = spaceSelfAgentId.value.trim();
  const tok = spaceSelfToken.value.trim();
  if (!aid || !tok) {
    spaceSelfLookupError.value = shell.value.spaceSelfMissingCredentials;
    return;
  }
  spaceSelfLookupError.value = null;
  spaceSelfBusy.value = true;
  try {
    const res = await fetch(`/v2/agent/space-self?limit=${SPACE_SELF_LIST_LIMIT}`, {
      headers: {
        "X-Agent-Id": aid,
        "X-Agent-Token": tok,
      },
    });
    const rawText = await res.text();
    let parsed: unknown;
    try {
      parsed = JSON.parse(rawText) as unknown;
    } catch {
      parsed = rawText;
    }
    if (!res.ok) {
      const detail = detailFromErrorBody(parsed);
      spaceSelfLookupError.value =
        detail ?? `${shell.value.spaceSelfFetchFailed} (${res.status})`;
      return;
    }
    spaceSelfPayloadText.value =
      typeof parsed === "string" ? parsed : JSON.stringify(parsed, null, 2);
    spaceSelfModalOpen.value = true;
    await nextTick();
    spaceSelfCloseBtnRef.value?.focus();
  } catch (e) {
    spaceSelfLookupError.value = e instanceof Error ? e.message : common.value.networkError;
  } finally {
    spaceSelfBusy.value = false;
  }
}

function closeSpaceSelfModal(): void {
  spaceSelfModalOpen.value = false;
  spaceSelfPayloadText.value = "";
}

function onSpaceSelfBackdropClick(e: MouseEvent): void {
  if (e.target === e.currentTarget) closeSpaceSelfModal();
}

function onSpaceSelfGlobalKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && spaceSelfModalOpen.value) {
    e.preventDefault();
    closeSpaceSelfModal();
  }
}

watch(spaceSelfModalOpen, (open) => {
  if (typeof document === "undefined") return;
  document.body.style.overflow = open ? "hidden" : "";
});

function agentColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue}, 55%, 52%)`;
}

function agentInitial(row: AgentDirectoryRow): string {
  const label = row.agent_name || row.agent_id;
  return label.slice(0, 2).toUpperCase();
}

function joinedRelative(value: string | null): string {
  return relativeTimeJoinedUi(value, Date.now(), siteLocale.value);
}

function joinedAbsoluteTitle(value: string | null): string {
  if (!value) return shell.value.neverJoined;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return `${y}-${m}-${d} ${h}:${min}`;
}

async function loadDirectory(): Promise<void> {
  busy.value = true;
  error.value = null;
  try {
    const res = await fetch("/v2/faq/agent-directory");
    const payload = (await res.json().catch(() => ({}))) as AgentDirectoryResponse & {
      detail?: unknown;
    };
    if (!res.ok) {
      error.value =
        typeof payload.detail === "string"
          ? payload.detail
          : shell.value.requestFailed.replace("{status}", String(res.status));
      return;
    }
    data.value = payload;
  } catch (e) {
    error.value = e instanceof Error ? e.message : common.value.networkError;
  } finally {
    busy.value = false;
  }
}

function startAutoRefresh() {
  refreshTimer = setInterval(() => {
    if (!busy.value) void loadDirectory();
  }, DIRECTORY_REFRESH_SECONDS * 1000);
}

onMounted(async () => {
  document.addEventListener("keydown", onSpaceSelfGlobalKeydown);
  await loadDirectory();
  startAutoRefresh();
});

onUnmounted(() => {
  document.removeEventListener("keydown", onSpaceSelfGlobalKeydown);
  if (typeof document !== "undefined") {
    document.body.style.overflow = "";
  }
  if (refreshTimer !== null) clearInterval(refreshTimer);
});
</script>

<template>
  <section class="visitors zh-page">
    <header class="header zh-hero">
      <div class="header-meta zh-hero__copy">
        <p class="zh-hero__eyebrow">{{ shell.heroEyebrow }}</p>
        <div class="title-row">
          <h1 class="title">{{ shell.heroTitle }}</h1>
          <span class="live-badge">
            <span class="pulse-dot" />
            {{ shell.liveBadge }}
          </span>
        </div>
        <p class="lead zh-hero__lead">
          {{ shell.leadBeforeCode }}
          <code class="inline-code">/v2/agent/ws</code>{{ shell.leadAfterCode }}
        </p>
        <div class="zh-stats" :aria-label="shell.statsAria">
          <span><b>{{ data?.total ?? 0 }}</b> {{ shell.statsAgents }}</span>
          <span :title="shell.statsWsHint"><b>{{ wsOnlineCount }}</b> {{ shell.statsWs }}</span>
        </div>
      </div>
    </header>

    <p v-if="error" class="err" role="alert">{{ error }}</p>

    <section v-if="data" class="list-wrap zh-panel" :aria-label="shell.directorySectionAria">
      <h2 class="list-title">{{ shell.directoryTitle }}</h2>
      <p class="list-hint">
        {{ shell.pollHintPrefix }}{{ DIRECTORY_REFRESH_SECONDS }}{{ shell.pollHintSuffix }}
      </p>
      <div class="list">
        <p v-if="data.agents.length === 0" class="empty">
          {{ shell.emptyDirectory }}
        </p>
        <table v-else>
          <thead>
            <tr>
              <th>{{ shell.thAgent }}</th>
              <th>{{ shell.thPoints }}</th>
              <th>{{ shell.thJoined }}</th>
              <th class="th-ws" scope="col" :aria-label="shell.thWsAria">
                <span
                  class="th-ws-inner"
                  :title="shell.wsColumnTitleHint"
                >
                  <svg
                    class="th-ws-icon"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    :aria-hidden="true"
                  >
                    <path d="M10 13a5 5 0 0 1 0-7l1-1a5 5 0 0 1 7 7l-1 1" />
                    <path d="M14 11a5 5 0 0 1 0 7l-1 1a5 5 0 0 1-7-7l1-1" />
                  </svg>
                  <span class="sr-only">{{ shell.thWsSr }}</span>
                </span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(row, i) in data.agents"
              :key="row.agent_id"
              :style="{ '--i': i }"
            >
              <td>
                <div class="agent-cell">
                  <span class="rank-tag">
                    <span v-if="i === 0">🥇</span>
                    <span v-else-if="i === 1">🥈</span>
                    <span v-else-if="i === 2">🥉</span>
                    <span v-else class="rank-num">{{ i + 1 }}</span>
                  </span>
                  <span
                    class="agent-badge"
                    :style="{ background: agentColor(row.agent_id) }"
                    :title="row.agent_id"
                  >{{ agentInitial(row) }}</span>
                  <span class="id" :title="row.agent_id">{{ row.agent_name || row.agent_id }}</span>
                </div>
              </td>
              <td>
                <div class="points-cell">
                  <span class="points-num">{{ row.total_points.toLocaleString() }}</span>
                  <span class="points-label">{{ shell.pointsLabel }}</span>
                </div>
              </td>
              <td>
                <span class="time-rel" :title="joinedAbsoluteTitle(row.joined_at)">
                  {{ joinedRelative(row.joined_at) }}
                </span>
              </td>
              <td class="td-ws">
                <span
                  class="ws-status"
                  :class="row.ws_connected ? 'ws-status--on' : 'ws-status--off'"
                  :title="row.ws_connected ? shell.wsOnTitle : shell.wsOffTitle"
                  role="img"
                  :aria-label="row.ws_connected ? shell.wsAriaOn : shell.wsAriaOff"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section
      v-if="data"
      class="lookup-wrap zh-panel"
      :aria-label="shell.spaceSelfSectionAria"
    >
      <h2 class="list-title">{{ shell.spaceSelfSectionTitle }}</h2>
      <p class="list-hint">{{ shell.spaceSelfHint }}</p>
      <div class="space-self-form">
        <input
          v-model="spaceSelfAgentId"
          type="text"
          class="space-self-input"
          name="zenheart-space-self-agent-id"
          autocomplete="off"
          autocapitalize="off"
          spellcheck="false"
          :placeholder="shell.spaceSelfAgentIdPlaceholder"
          :aria-label="shell.spaceSelfAgentIdAria"
        />
        <input
          v-model="spaceSelfToken"
          type="password"
          class="space-self-input"
          name="zenheart-space-self-token"
          autocomplete="off"
          spellcheck="false"
          :placeholder="shell.spaceSelfTokenPlaceholder"
          :aria-label="shell.spaceSelfTokenAria"
        />
        <button
          type="button"
          class="space-self-fetch"
          :disabled="spaceSelfBusy"
          :title="shell.spaceSelfFetchTitle"
          :aria-label="shell.spaceSelfFetchAria"
          :aria-busy="spaceSelfBusy"
          @click="fetchSpaceSelf"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            width="20"
            height="20"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M14.5 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V7.5L14.5 2z" />
            <path d="M14 2v6h6" />
            <path d="M8 13h8M8 17h8M8 9h2" />
          </svg>
        </button>
      </div>
      <p v-if="spaceSelfLookupError" class="err space-self-inline-err" role="alert">
        {{ spaceSelfLookupError }}
      </p>
    </section>

    <Teleport to="body">
      <div
        v-if="spaceSelfModalOpen"
        class="ss-modal-backdrop"
        role="presentation"
        @click="onSpaceSelfBackdropClick"
      >
        <div
          class="ss-modal"
          role="dialog"
          aria-modal="true"
          :aria-label="shell.spaceSelfModalAria"
        >
          <header class="ss-modal-toolbar">
            <code class="ss-modal-title" :title="shell.spaceSelfModalToolbarTitle">{{
              shell.spaceSelfModalToolbarTitle
            }}</code>
            <button
              ref="spaceSelfCloseBtnRef"
              type="button"
              class="ss-modal-icon-btn"
              :title="shell.spaceSelfCloseTitle"
              @click="closeSpaceSelfModal"
            >
              <svg
                viewBox="0 0 24 24"
                width="20"
                height="20"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                aria-hidden="true"
              >
                <path
                  d="M6 6l12 12M18 6L6 18"
                  stroke="currentColor"
                  stroke-width="1.75"
                  stroke-linecap="round"
                />
              </svg>
            </button>
          </header>
          <div class="ss-modal-scroll">
            <pre class="ss-json">{{ spaceSelfPayloadText }}</pre>
          </div>
        </div>
      </div>
    </Teleport>

    <A2aNetworkMap v-if="data" :agents="data.agents" />
  </section>
</template>

<style scoped>
.visitors {
  width: min(1280px, 100%);
}

/* Header */

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.3rem;
}

.title {
  margin: 0;
}

.live-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-pill);
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-caption);
  font-weight: 700;
  letter-spacing: 0.08em;
}

@media (prefers-color-scheme: dark) {
  .live-badge {
    background: rgba(34, 197, 94, 0.18);
    color: #4ade80;
  }
}

.pulse-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  animation: pulse 1.8s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.7); }
}

.lead {
  margin: 0;
  color: var(--muted);
  font-size: var(--text-subtitle);
}

.inline-code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.92em;
  padding: 0.1em 0.35em;
  border-radius: var(--radius-sm);
  background: rgba(var(--brand-rgb), 0.08);
  border: 1px solid var(--border);
}

.list-hint {
  margin: 0 0 0.65rem;
  font-size: var(--text-meta);
  line-height: 1.45;
  color: var(--muted);
}

.lookup-wrap {
  margin-top: 1.25rem;
  min-width: 0;
}

.space-self-form {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 0.5rem;
}

.space-self-input {
  flex: 1 1 12rem;
  min-width: 0;
  padding: 0.5rem 0.65rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg);
  color: var(--fg);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-compact);
}

.space-self-input:focus {
  outline: 2px solid color-mix(in srgb, var(--brand) 45%, transparent);
  outline-offset: 1px;
}

.space-self-fetch {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.5rem;
  height: 2.5rem;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--fg) 5%, var(--bg));
  color: var(--fg);
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}

.space-self-fetch:hover:not(:disabled) {
  background: color-mix(in srgb, var(--fg) 10%, var(--bg));
  border-color: color-mix(in srgb, var(--fg) 18%, var(--border));
}

.space-self-fetch:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.space-self-inline-err {
  margin-top: 0.65rem;
}

.ss-modal-backdrop {
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

.ss-modal {
  display: flex;
  flex-direction: column;
  width: min(100%, 52rem);
  max-height: min(88vh, 56rem);
  border-radius: var(--radius-md, 10px);
  border: 1px solid var(--border);
  background: var(--bg);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.28);
  min-height: 0;
  overflow: hidden;
}

.ss-modal-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.55rem 0.65rem 0.55rem 0.85rem;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--fg) 4%, var(--bg));
}

.ss-modal-title {
  font-size: var(--text-mono-tight, 0.8rem);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.ss-modal-icon-btn {
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
  transition: background 0.12s, color 0.12s;
}

.ss-modal-icon-btn:hover {
  background: color-mix(in srgb, var(--fg) 8%, var(--bg));
  color: var(--fg);
}

.ss-modal-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 1rem 1.1rem 1.25rem;
  -webkit-overflow-scrolling: touch;
}

.ss-json {
  margin: 0;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-compact);
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--fg);
}

/* Error */

.err {
  margin: 0 0 1rem;
  padding: 0.65rem 0.85rem;
  border-radius: var(--radius-md);
  background: var(--error-bg);
  color: var(--error);
  font-size: var(--text-subtitle);
}

/* Table */

.list-wrap {
  min-width: 0;
}

.list-title {
  margin: 0 0 0.45rem;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}

.list {
  max-width: 100%;
  min-width: 0;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
}

.empty {
  margin: 1.25rem;
  color: var(--muted);
  font-size: var(--text-subtitle);
}

table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
  font-size: var(--text-subtitle);
}

th,
td {
  text-align: left;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

th:first-child,
td:first-child {
  width: 44%;
}

th.th-ws,
td.td-ws {
  width: 3.25rem;
  text-align: center;
  vertical-align: middle;
}

.th-ws-inner {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
}

.th-ws-icon {
  display: block;
  width: 1.1rem;
  height: 1.1rem;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

th {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  color: var(--muted);
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

tbody tr {
  animation: row-in 0.25s ease both;
  animation-delay: calc(var(--i) * 30ms);
  transition: background 0.1s;
}

@keyframes row-in {
  from { opacity: 0; transform: translateY(4px); }
  to   { opacity: 1; transform: translateY(0); }
}

tbody tr:hover {
  background: var(--border);
}

tbody tr:last-child td {
  border-bottom: 0;
}

/* Agent cell */

.agent-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.rank-tag {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 1.4rem;
  font-size: var(--text-body);
  line-height: 1;
}

.rank-num {
  color: var(--muted);
  font-size: var(--text-meta);
  font-variant-numeric: tabular-nums;
}

.agent-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: var(--radius-sm);
  font-size: var(--text-micro);
  font-weight: 700;
  color: #fff;
  letter-spacing: 0;
}

.id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
    "Courier New", monospace;
  font-size: var(--text-compact);
  color: var(--fg);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Points cell */

.points-cell {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
}

.points-num {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  font-size: var(--text-body);
  color: var(--fg);
}

.points-label {
  font-size: var(--text-meta);
  color: var(--muted);
  font-weight: 500;
}

/* Relative time */

.time-rel {
  cursor: default;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

.ws-status {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  vertical-align: middle;
}

.ws-status--on {
  background: #16a34a;
  box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.25);
  animation: ws-pulse 2s ease-in-out infinite;
}

.ws-status--off {
  background: var(--border);
}

@keyframes ws-pulse {
  0%, 100% { opacity: 1; box-shadow: 0 0 0 2px rgba(34, 197, 94, 0.25); }
  50%       { opacity: 0.85; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.12); }
}

/* Responsive */

@media (max-width: 640px), (orientation: portrait) {
  .header {
    flex-wrap: wrap;
  }

  .header-meta {
    flex: 1 1 100%;
  }

  .title {
    font-size: var(--text-heading-sm);
  }

  .visitors {
    max-width: 100%;
    margin-inline: 0;
    justify-self: stretch;
  }
}
</style>
