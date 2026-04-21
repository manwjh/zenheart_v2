<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";

type AgentVisitorRow = {
  agent_id: string;
  agent_name: string | null;
  visit_count: number;
  first_seen_at: string;
  last_seen_at: string;
};

type AgentVisitors24hResponse = {
  window_hours: number;
  since: string;
  until: string;
  total_visits: number;
  unique_agents: number;
  visitors: AgentVisitorRow[];
};

const REFRESH_INTERVAL = 30;

const busy = ref(false);
const error = ref<string | null>(null);
const data = ref<AgentVisitors24hResponse | null>(null);
const countdown = ref(REFRESH_INTERVAL);
const lastRefreshed = ref<Date | null>(null);

let countdownTimer: ReturnType<typeof setInterval> | null = null;

const maxVisits = computed(() => {
  if (!data.value || data.value.visitors.length === 0) return 1;
  return Math.max(...data.value.visitors.map((v) => v.visit_count));
});

function agentColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  }
  const hue = hash % 360;
  return `hsl(${hue}, 55%, 52%)`;
}

function agentInitial(row: AgentVisitorRow): string {
  const label = row.agent_name || row.agent_id;
  return label.slice(0, 2).toUpperCase();
}

function relativeTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffMs = Date.now() - date.getTime();
  const diffS = Math.floor(diffMs / 1000);
  if (diffS < 60) return `${diffS}s ago`;
  const diffM = Math.floor(diffS / 60);
  if (diffM < 60) return `${diffM}m ago`;
  const diffH = Math.floor(diffM / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  return `${diffD}d ago`;
}

function absoluteTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function visitBarWidth(count: number): number {
  return Math.max(4, Math.round((count / maxVisits.value) * 100));
}

async function loadVisitors(): Promise<void> {
  busy.value = true;
  error.value = null;
  countdown.value = REFRESH_INTERVAL;
  try {
    const res = await fetch("/v2/faq/ai-visitors-24h");
    const payload = (await res.json().catch(() => ({}))) as AgentVisitors24hResponse & {
      detail?: unknown;
    };
    if (!res.ok) {
      error.value =
        typeof payload.detail === "string"
          ? payload.detail
          : `Request failed (${res.status})`;
      return;
    }
    data.value = payload;
    lastRefreshed.value = new Date();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "Network error";
  } finally {
    busy.value = false;
  }
}

function startCountdown() {
  countdownTimer = setInterval(() => {
    countdown.value -= 1;
    if (countdown.value <= 0) {
      loadVisitors();
    }
  }, 1000);
}

onMounted(async () => {
  await loadVisitors();
  startCountdown();
});

onUnmounted(() => {
  if (countdownTimer !== null) clearInterval(countdownTimer);
});
</script>

<template>
  <section class="visitors">
    <header class="header">
      <div class="header-meta">
        <div class="title-row">
          <h1 class="title">AI Visitors</h1>
          <span class="live-badge">
            <span class="pulse-dot" />
            LIVE
          </span>
        </div>
        <p class="lead">AI agents that visited in the past 24 hours, sorted by most recent.</p>
      </div>
      <div class="controls">
        <span class="countdown" :class="{ dim: busy }">
          {{ busy ? "…" : `↻ ${countdown}s` }}
        </span>
        <button class="refresh" type="button" :disabled="busy" @click="loadVisitors">
          Refresh
        </button>
      </div>
    </header>

    <p v-if="error" class="err" role="alert">{{ error }}</p>

    <section v-if="data" class="stats" aria-label="24-hour overview">
      <div class="card">
        <div class="k">Total visits</div>
        <div class="v">{{ data.total_visits }}</div>
      </div>
      <div class="card">
        <div class="k">Unique agents</div>
        <div class="v">{{ data.unique_agents }}</div>
      </div>
      <div class="card">
        <div class="k">Window</div>
        <div class="v">{{ data.window_hours }}h</div>
      </div>
      <div class="card card-wide">
        <div class="k">Last refreshed</div>
        <div class="v v-sm">
          {{ lastRefreshed ? lastRefreshed.toLocaleTimeString("en-US", { hour12: false }) : "—" }}
        </div>
      </div>
    </section>

    <section v-if="data" class="list" aria-label="visitor detail">
      <p v-if="data.visitors.length === 0" class="empty">
        No AI agent visits recorded in the past 24 hours.
      </p>
      <table v-else>
        <thead>
          <tr>
            <th>agent</th>
            <th>visits</th>
            <th>first seen</th>
            <th>last seen</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, i) in data.visitors" :key="row.agent_id" :style="{ '--i': i }">
            <td class="agent-cell">
              <span
                class="agent-badge"
                :style="{ background: agentColor(row.agent_id) }"
                :title="row.agent_id"
              >
                {{ agentInitial(row) }}
              </span>
              <span class="id" :title="row.agent_id">{{ row.agent_name || row.agent_id }}</span>
            </td>
            <td class="visits-cell">
              <span class="visits-num">{{ row.visit_count }}</span>
              <span class="visits-bar-bg">
                <span
                  class="visits-bar-fill"
                  :style="{ width: visitBarWidth(row.visit_count) + '%' }"
                />
              </span>
            </td>
            <td>
              <span class="time-rel" :title="absoluteTime(row.first_seen_at)">
                {{ relativeTime(row.first_seen_at) }}
              </span>
            </td>
            <td>
              <span class="time-rel" :title="absoluteTime(row.last_seen_at)">
                {{ relativeTime(row.last_seen_at) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<style scoped>
.visitors {
  width: 100%;
  max-width: 60rem;
  margin: 0 auto;
  align-self: start;
}

/* Header */

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.25rem;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.3rem;
}

.title {
  margin: 0;
  font-size: 1.5rem;
  letter-spacing: -0.01em;
}

.live-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  padding: 0.15rem 0.5rem;
  border-radius: 999px;
  background: rgba(34, 197, 94, 0.12);
  color: #16a34a;
  font-size: 0.65rem;
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
  font-size: 0.9rem;
}

.controls {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-shrink: 0;
}

.countdown {
  font-size: 0.78rem;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  min-width: 4rem;
  text-align: right;
}

.countdown.dim {
  opacity: 0.4;
}

.refresh {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: transparent;
  color: inherit;
  padding: 0.45rem 0.75rem;
  font-size: 0.875rem;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.refresh:hover:not(:disabled) {
  background: var(--border);
}

.refresh:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Error */

.err {
  margin: 0 0 1rem;
  padding: 0.65rem 0.85rem;
  border-radius: 8px;
  background: rgba(185, 28, 28, 0.08);
  color: #b91c1c;
  font-size: 0.9rem;
}

@media (prefers-color-scheme: dark) {
  .err {
    background: rgba(239, 68, 68, 0.12);
    color: #f87171;
  }
}

/* Stats cards */

.stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.75rem 0.9rem;
  background: transparent;
  transition: border-color 0.15s;
}

.card:hover {
  border-color: rgba(128, 128, 128, 0.3);
}

.k {
  color: var(--muted);
  font-size: 0.76rem;
  font-weight: 500;
  letter-spacing: 0.03em;
  text-transform: uppercase;
}

.v {
  margin-top: 0.3rem;
  font-size: 1.5rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.v-sm {
  font-size: 0.95rem;
  font-weight: 500;
  letter-spacing: 0;
}

/* Table */

.list {
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}

.empty {
  margin: 1.25rem;
  color: var(--muted);
  font-size: 0.9rem;
}

table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.9rem;
}

th,
td {
  text-align: left;
  padding: 0.6rem 0.85rem;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

th {
  color: var(--muted);
  font-size: 0.74rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
}

tbody tr {
  animation: row-in 0.25s ease both;
  animation-delay: calc(var(--i) * 30ms);
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
  gap: 0.55rem;
}

.agent-badge {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border-radius: 5px;
  font-size: 0.6rem;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0;
}

.id {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono",
    "Courier New", monospace;
  font-size: 0.82rem;
  color: var(--fg);
}

/* Visits cell */

.visits-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.visits-num {
  min-width: 1.5rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.visits-bar-bg {
  flex: 1;
  min-width: 48px;
  max-width: 100px;
  height: 5px;
  border-radius: 999px;
  background: var(--border);
  overflow: hidden;
}

.visits-bar-fill {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: #22c55e;
  transition: width 0.4s ease;
}

/* Relative time */

.time-rel {
  cursor: default;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* Responsive */

@media (max-width: 640px) {
  .header {
    flex-wrap: wrap;
  }

  .header-meta {
    flex: 1 1 100%;
  }

  .controls {
    align-self: flex-end;
  }

  .stats {
    grid-template-columns: repeat(2, 1fr);
  }

  .card-wide {
    grid-column: span 2;
  }

  .visits-bar-bg {
    display: none;
  }

  .title {
    font-size: 1.25rem;
  }
}

@media (max-width: 480px) {
  .stats {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
