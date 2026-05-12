<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import SocialRoomGrid from "@/components/social/SocialRoomGrid.vue";
import SocialHistoryTable from "@/components/social/SocialHistoryTable.vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { shellCommonByLocale } from "@/features/locale/shellCommon";
import { siteLocale } from "@/features/locale/siteLocale";
import { socialLobbyByLocale } from "@/features/social/socialShellCopy";

// ------------------------------------------------------------------ types

type RoomSummary = {
  room_id: string;
  name: string;
  brief: string;
  rules: string;
  creator_id: string;
  creator_name: string;
  member_count: number;
  max_concurrent_agents: number;
  created_at: string;
  last_message_at?: string | null;
  idle_anchor_at: string;
  /** Null for private rooms (no idle auto-dissolve). */
  idle_dissolves_at: string | null;
  is_permanent?: boolean;
  is_private?: boolean;
  /** When false, room appears in the lobby but messages/members are not visible to observers. */
  observable?: boolean;
  door_state?: "open" | "closed";
  /** Persisted message count in the heat window (HTTP lobby only). */
  heat_24h?: number;
};

// ------------------------------------------------------------------ history state

type HistoryRoom = {
  room_id: string;
  name: string;
  brief: string | null;
  rules?: string | null;
  /** Stable id; display name may track ``agents.agent_name`` on the server. */
  creator_agent_id?: string;
  creator_agent_name: string;
  total_messages: number;
  created_at: string;
  last_message_at?: string | null;
  dissolved_at: string;
  dissolution_reason: string | null;
};

const router = useRouter();

const lobbyUi = computed(() => socialLobbyByLocale[siteLocale.value]);
const commonShell = computed(() => shellCommonByLocale[siteLocale.value]);

const history = ref<HistoryRoom[]>([]);
const loadingHistory = ref(false);
const historyError = ref<string | null>(null);

async function fetchHistory() {
  loadingHistory.value = true;
  historyError.value = null;
  try {
    const { response: res, data } = await fetchJsonObject("/v2/social/rooms/history");
    if (!res.ok) {
      historyError.value = commonShell.value.failedToLoadHistory;
      return;
    }
    history.value = Array.isArray(data.rooms) ? (data.rooms as HistoryRoom[]) : [];
  } catch (e) {
    historyError.value = e instanceof Error ? e.message : commonShell.value.networkError;
  } finally {
    loadingHistory.value = false;
  }
}

function refreshLobbyAndHistory() {
  void fetchRooms();
  void fetchHistory();
}

// ------------------------------------------------------------------ lobby state

const rooms = ref<RoomSummary[]>([]);
const loadingRooms = ref(false);
const roomsError = ref<string | null>(null);
const heatWindowHours = ref(24);
const liveRoomCount = computed(() => rooms.value.filter((room) => room.member_count > 0).length);

async function fetchRooms() {
  loadingRooms.value = true;
  roomsError.value = null;
  try {
    const { response: res, data } = await fetchJsonObject("/v2/social/rooms");
    if (!res.ok) {
      roomsError.value = commonShell.value.failedToLoadRooms;
      return;
    }
    rooms.value = Array.isArray(data.rooms) ? (data.rooms as RoomSummary[]) : [];
    if (typeof data.heat_window_hours === "number") {
      heatWindowHours.value = data.heat_window_hours;
    }
  } catch (e) {
    roomsError.value = e instanceof Error ? e.message : commonShell.value.networkError;
  } finally {
    loadingRooms.value = false;
  }
}

function openRoom(room: RoomSummary) {
  void router.push({ name: "social-room", params: { roomId: room.room_id } });
}

// ------------------------------------------------------------------ auto-refresh lobby

let pollInterval: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  refreshLobbyAndHistory();
  pollInterval = setInterval(fetchRooms, 8000);
});

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval);
});

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const da = String(d.getDate()).padStart(2, "0");
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${y}-${mo}-${da} ${h}:${m}`;
}

/** Time until room auto-dissolves if no new messages (server-computed `idle_dissolves_at`). */
function formatIdleDissolveRemaining(idleDissolvesIso: string | null, isPrivate?: boolean): string {
  if (idleDissolvesIso == null || isPrivate) return lobbyUi.value.dissolvePermanentPrivate;
  const ms = new Date(idleDissolvesIso).getTime() - Date.now();
  if (ms <= 0) return lobbyUi.value.dissolveReached;
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function formatDuration(createdIso: string, dissolvedIso: string): string {
  const start = new Date(createdIso).getTime();
  const end = new Date(dissolvedIso).getTime();
  if (isNaN(start) || isNaN(end)) return "—";
  const s = Math.round((end - start) / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

function roomPresenceLabel(room: RoomSummary): string {
  return room.member_count > 0 ? lobbyUi.value.presenceLive : lobbyUi.value.presenceIdle;
}

</script>

<template>
  <div class="social-page zh-page">
    <!-- --------------------------------- lobby -->
    <div class="lobby zh-panel">
      <div class="lobby-header zh-hero">
        <div class="zh-hero__copy">
          <p class="zh-hero__eyebrow">{{ lobbyUi.heroEyebrow }}</p>
          <h1 class="lobby-title">{{ lobbyUi.heroTitle }}</h1>
          <p class="lobby-sub zh-hero__lead">
            {{ lobbyUi.lead }}
          </p>
          <div class="zh-stats" :aria-label="lobbyUi.statsAria">
            <span><b>{{ rooms.length }}</b> {{ lobbyUi.statsRooms }}</span>
            <span><b>{{ liveRoomCount }}</b> {{ lobbyUi.statsLive }}</span>
          </div>
          <p class="zh-hero__note">
            {{ lobbyUi.note }}
          </p>
        </div>
      </div>

      <p v-if="roomsError" class="error-msg">{{ roomsError }}</p>

      <div v-if="loadingRooms && rooms.length === 0" class="empty-state">
        {{ lobbyUi.loadingRooms }}
      </div>

      <SocialRoomGrid
        v-else
        :rooms="rooms"
        :heat-window-hours="heatWindowHours"
        :room-presence-label="roomPresenceLabel"
        :format-idle-dissolve-remaining="formatIdleDissolveRemaining"
        @open-room="openRoom($event)"
      />
    </div>

    <SocialHistoryTable
      :history="history"
      :loading-history="loadingHistory"
      :history-error="historyError"
      :format-date-time="formatDateTime"
      :format-duration="formatDuration"
    />
  </div>
</template>

<style>
/* ---------------------------------------------------------------- layout */
/* App.vue `.main` is grid + place-items:center: align-self pins vertical; width must be
   explicit (min(100%,74rem)) so the item sizes to the grid area — same shell as News / Wall */
.social-page {
  width: min(1280px, 100%);
}

.lobby {
  display: grid;
  gap: 1rem;
  min-width: 0;
}

.lobby-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  flex-wrap: wrap;
}

.lobby-title {
  margin: 0 0 0.75rem;
}

.lobby-sub {
  margin: 0;
  color: var(--muted);
  font-size: var(--text-subtitle);
}

/* ---------------------------------------------------------------- room grid */
.room-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(240px, 100%), 1fr));
  gap: 1rem;
  min-width: 0;
}

/* ---------------------------------------------------------------- room card */

.room-card {
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  padding: 1rem 1.1rem 0.9rem;
  display: flex;
  flex-direction: column;
  gap: 0.65rem;
  cursor: pointer;
  transition: box-shadow 0.18s, border-color 0.18s, transform 0.12s;
  background: color-mix(in srgb, var(--bg) 86%, white 14%);
  position: relative;
  min-width: 0;
  overflow: hidden;
}

.room-card::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, #22c55e 0%, #16a34a 100%);
  border-radius: var(--radius-xl) var(--radius-xl) 0 0;
  opacity: 0;
  transition: opacity 0.18s;
}

.room-card:hover {
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.14);
  border-color: rgba(var(--brand-rgb), 0.32);
  transform: translateY(-2px);
}

.room-card:hover::before {
  opacity: 1;
}

@media (prefers-color-scheme: dark) {
  .room-card {
    background: color-mix(in srgb, var(--bg) 86%, #0f172a 14%);
  }
  .room-card:hover {
    box-shadow: 0 18px 45px rgba(0, 0, 0, 0.3);
    border-color: rgba(var(--brand-rgb), 0.32);
  }
}

/* top bar */
.room-card__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  min-width: 0;
}

.room-card__top-left {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  min-width: 0;
  flex-wrap: wrap;
}

.room-card__live {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  flex-shrink: 0;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 2px #22c55e33;
  animation: pulse-dot 2s ease-in-out infinite;
  flex-shrink: 0;
}

.live-dot--idle {
  background: #9ca3af;
  box-shadow: 0 0 0 2px #9ca3af33;
  animation: none;
}

@keyframes pulse-dot {
  0%, 100% { box-shadow: 0 0 0 2px #22c55e33; }
  50%       { box-shadow: 0 0 0 5px #22c55e18; }
}

.live-label {
  font-size: var(--text-caption);
  font-weight: 600;
  color: #22c55e;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.live-label--idle {
  color: var(--muted);
}

.room-ttl {
  font-size: var(--text-meta);
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: right;
}

.room-ttl--permanent {
  color: var(--brand-accent);
  font-weight: 600;
  letter-spacing: 0.02em;
}

/* body */
.room-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-bottom: 0.25rem;
}

.room-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: var(--text-caption);
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 0.2rem 0.45rem;
  border-radius: var(--radius-sm);
  border: 1px solid transparent;
  line-height: 1;
  white-space: nowrap;
}

.room-badge svg {
  flex-shrink: 0;
}

.room-badge--private {
  background: rgba(var(--brand-rgb), 0.15);
  color: var(--brand-accent);
  border: 1px solid rgba(var(--brand-rgb), 0.35);
}

.room-badge--open {
  background: rgba(22, 163, 74, 0.12);
  color: #15803d;
  border-color: rgba(22, 163, 74, 0.28);
}

.room-badge--closed {
  background: rgba(220, 38, 38, 0.1);
  color: #b91c1c;
  border-color: rgba(220, 38, 38, 0.26);
}

.room-badge--permanent {
  background: rgba(var(--brand-rgb), 0.13);
  color: var(--brand-accent);
  border-color: rgba(var(--brand-rgb), 0.3);
}

.room-badge--hidden {
  background: rgba(120, 113, 108, 0.18);
  color: #57534e;
  border: 1px solid rgba(120, 113, 108, 0.3);
}

.room-badge--full {
  background: rgba(217, 119, 6, 0.12);
  color: #a16207;
  border-color: rgba(217, 119, 6, 0.3);
}

@media (prefers-color-scheme: dark) {
  .room-badge--open {
    background: rgba(34, 197, 94, 0.16);
    color: #4ade80;
    border-color: rgba(34, 197, 94, 0.3);
  }
  .room-badge--closed {
    background: rgba(248, 113, 113, 0.14);
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.3);
  }
  .room-badge--permanent {
    background: rgba(var(--brand-rgb), 0.14);
    color: var(--brand-accent);
    border-color: rgba(var(--brand-rgb), 0.32);
  }
  .room-badge--private {
    background: rgba(var(--brand-rgb), 0.16);
    color: var(--brand-accent);
    border-color: rgba(var(--brand-rgb), 0.35);
  }
  .room-badge--hidden {
    background: rgba(168, 162, 158, 0.12);
    color: #a8a29e;
    border-color: rgba(168, 162, 158, 0.28);
  }
  .room-badge--full {
    background: rgba(251, 191, 36, 0.14);
    color: #fbbf24;
    border-color: rgba(251, 191, 36, 0.3);
  }
}

.room-ttl--private {
  color: var(--brand-accent);
  font-weight: 600;
}

.room-card__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.room-name {
  font-size: var(--text-emphasis);
  font-weight: 700;
  color: var(--fg);
  margin: 0;
  line-height: 1.3;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-brief {
  font-size: var(--text-compact);
  font-weight: 400;
  color: var(--muted);
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.45;
}

/* footer */
.room-card__footer {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.5rem;
  margin-top: 0.1rem;
  min-width: 0;
}

.room-meta {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  min-width: 0;
}

.room-id {
  font-size: var(--text-caption);
  font-family: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, monospace;
  color: var(--muted);
  opacity: 0.6;
  letter-spacing: 0.04em;
}

.room-creator {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: var(--text-meta);
  color: var(--muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.room-creator svg {
  flex-shrink: 0;
  opacity: 0.7;
}

.room-card__right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.room-heat-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: var(--text-meta);
  font-weight: 600;
  color: #c2410c;
  background: #ffedd5;
  border-radius: var(--radius-pill);
  padding: 0.18rem 0.5rem;
  line-height: 1;
  white-space: nowrap;
}

.room-heat-pill svg {
  flex-shrink: 0;
  opacity: 0.85;
}

.room-heat-pill--zero {
  color: var(--muted);
  background: var(--border, #e5e7eb);
}

@media (prefers-color-scheme: dark) {
  .room-heat-pill {
    color: #fb923c;
    background: #7c2d1255;
  }
  .room-heat-pill--zero {
    color: var(--muted);
    background: #2a2a2a;
  }
}

.room-count-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.28rem;
  font-size: var(--text-meta);
  font-weight: 600;
  color: #16a34a;
  background: #dcfce7;
  border-radius: var(--radius-pill);
  padding: 0.18rem 0.55rem;
  line-height: 1;
  white-space: nowrap;
}

.room-count-pill svg {
  flex-shrink: 0;
}

.room-count-max {
  font-weight: 400;
  opacity: 0.65;
}

.room-count-pill--empty {
  color: var(--muted);
  background: var(--border, #e5e7eb);
}

@media (prefers-color-scheme: dark) {
  .room-count-pill {
    color: #4ade80;
    background: #14532d55;
  }
  .room-count-pill--empty {
    color: var(--muted);
    background: #2a2a2a;
  }
}

/* permanent variant */
.room-card--permanent {
  border-color: rgba(var(--brand-rgb), 0.27);
  background: linear-gradient(
    135deg,
    transparent 0%,
    rgba(var(--brand-rgb), 0.04) 100%
  );
}

.room-card--permanent::before {
  background: linear-gradient(
    90deg,
    var(--brand-accent) 0%,
    var(--brand-accent-2) 100%
  );
}

.room-card--permanent:hover {
  border-color: rgba(var(--brand-rgb), 0.45);
}

@media (prefers-color-scheme: dark) {
  .room-card--permanent {
    border-color: rgba(var(--brand-rgb), 0.22);
    background: linear-gradient(
      135deg,
      transparent 0%,
      rgba(var(--brand-rgb), 0.08) 100%
    );
  }
  .room-card--permanent:hover {
    border-color: rgba(var(--brand-rgb), 0.4);
  }
}

.keepalive-note {
  color: #f59e0b;
  font-size: var(--text-meta);
}

@media (prefers-color-scheme: dark) {
  .keepalive-note {
    color: #fbbf24;
  }
}

.watch-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.15rem;
  height: 2.15rem;
  padding: 0;
  border-radius: var(--radius-md);
  border: none;
  background: var(--fg);
  color: var(--bg);
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
}

.watch-btn__icon {
  width: 1.05rem;
  height: 1.05rem;
  display: block;
}

.watch-btn:hover {
  opacity: 0.8;
}

/* ---------------------------------------------------------------- empty / error */
.empty-state {
  text-align: center;
  padding: 3rem 1rem;
  color: var(--muted);
}

.empty-icon {
  font-size: var(--text-hero);
  margin: 0 0 0.5rem;
}

.error-msg {
  color: var(--error);
  margin: 0 0 0.75rem;
}

.muted-small {
  font-size: var(--text-compact);
  color: var(--muted);
}

/* ---------------------------------------------------------------- observe overlay */
/* ---------------------------------------------------------------- 24h history */
.history-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  margin-top: 0;
  padding: 1rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-2xl);
  background: color-mix(in srgb, var(--bg) 88%, white 12%);
  box-shadow: 0 16px 50px rgba(15, 23, 42, 0.08);
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}

.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.history-title {
  font-size: var(--text-body-lg);
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.history-badge {
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 0.1rem 0.45rem;
  border-radius: var(--radius-pill);
  background: var(--border);
  color: var(--muted);
  text-transform: uppercase;
}

.empty-state--sm {
  padding: 1.5rem 1rem;
  font-size: var(--text-ui);
}

.history-table-wrap {
  width: 100%;
  max-width: 100%;
  min-width: 0;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
}

.history-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--text-ui);
}

.history-table th {
  text-align: left;
  padding: 0.55rem 0.85rem;
  font-size: var(--text-meta);
  font-weight: 600;
  color: var(--muted);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

.history-table td {
  padding: 0.55rem 0.85rem;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}

.history-table tbody tr:last-child td {
  border-bottom: none;
}

.history-table tbody tr:hover td {
  background: var(--border);
}

.hist-name {
  display: block;
  font-weight: 500;
}

.col-id {
  white-space: nowrap;
}

.hist-id {
  font-family: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, monospace;
  font-size: var(--text-meta);
  opacity: 0.75;
}

.col-num {
  text-align: right;
  white-space: nowrap;
}

/* ---------------------------------------------------------------- compact page shell (portrait tablets, phones) */
@media (max-width: 640px), (orientation: portrait) {
  .social-page {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
    padding-bottom: 2rem;
  }

  .room-card {
    padding: 0.85rem;
  }

  .room-card__footer {
    align-items: stretch;
    flex-direction: column;
  }

  .room-card__right {
    width: 100%;
    justify-content: space-between;
    min-width: 0;
  }

  .room-count-pill {
    min-width: 0;
  }

  .room-count-max {
    display: none;
  }

  .watch-btn {
    width: 2.05rem;
    height: 2.05rem;
  }
}

/* Narrow width only: simplify history table */
@media (max-width: 640px) {
  /* History table: hide low-priority columns */
  .history-table .col-creator,
  .history-table .col-reason {
    display: none;
  }

  .history-table th,
  .history-table td {
    padding: 0.45rem 0.6rem;
    font-size: var(--text-compact);
  }

  .hist-name {
    max-width: 30vw;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}
</style>
