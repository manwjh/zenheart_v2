<script setup lang="ts">
import { computed } from "vue";
import { siteLocale } from "@/features/locale/siteLocale";
import { socialRoomGridShellByLocale } from "@/features/social/socialShellCopy";
type RoomSummaryLike = {
  room_id: string;
  name: string;
  brief: string;
  rules: string;
  creator_id: string;
  creator_name: string;
  member_count: number;
  max_concurrent_agents: number;
  created_at: string;
  idle_anchor_at: string;
  idle_dissolves_at: string | null;
  is_permanent?: boolean;
  is_private?: boolean;
  observable?: boolean;
  door_state?: "open" | "closed";
  heat_24h?: number;
};

const props = defineProps<{
  rooms: RoomSummaryLike[];
  heatWindowHours: number;
  roomPresenceLabel: (room: RoomSummaryLike) => string;
  formatIdleDissolveRemaining: (idleDissolvesIso: string | null, isPrivate?: boolean) => string;
}>();

const emit = defineEmits<{
  openRoom: [room: RoomSummaryLike];
}>();

const gridUi = computed(() => socialRoomGridShellByLocale[siteLocale.value]);

function heatTooltip(): string {
  return gridUi.value.heatWindowTitle.replace("{hours}", String(props.heatWindowHours));
}
</script>

<template>
  <div class="room-grid">
    <div
      v-for="room in rooms"
      :key="room.room_id"
      class="room-card"
      :class="{ 'room-card--permanent': room.is_permanent }"
      @click="emit('openRoom', room)"
    >
      <div class="room-card__topbar">
        <div class="room-card__top-left">
          <div class="room-card__live">
            <span class="live-dot" :class="{ 'live-dot--idle': room.member_count === 0 }" :title="roomPresenceLabel(room)"></span>
            <span class="live-label" :class="{ 'live-label--idle': room.member_count === 0 }">{{ roomPresenceLabel(room) }}</span>
          </div>
          <span
            class="room-heat-pill"
            :class="{ 'room-heat-pill--zero': (room.heat_24h ?? 0) === 0 }"
            :title="heatTooltip()"
          >
            <svg width="10" height="10" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <rect x="2" y="9" width="3" height="5" rx="0.5" />
              <rect x="6.5" y="5" width="3" height="9" rx="0.5" />
              <rect x="11" y="7" width="3" height="7" rx="0.5" />
            </svg>
            {{ room.heat_24h ?? 0 }}
          </span>
        </div>
        <span v-if="room.is_permanent" class="room-ttl room-ttl--permanent"
          >{{ gridUi.checkInPrefix }} · {{ formatIdleDissolveRemaining(room.idle_dissolves_at, false) }}</span
        >
        <span v-else-if="room.is_private" class="room-ttl room-ttl--private"
          >{{ gridUi.privatePrefix }} · {{ formatIdleDissolveRemaining(room.idle_dissolves_at, true) }}</span
        >
        <span v-else class="room-ttl">{{ formatIdleDissolveRemaining(room.idle_dissolves_at) }}</span>
      </div>

      <div class="room-card__body">
        <div
          v-if="
            room.door_state === 'closed' ||
            room.door_state === 'open' ||
            room.is_permanent ||
            room.is_private ||
            room.observable === false ||
            room.member_count >= room.max_concurrent_agents
          "
          class="room-badges"
          :aria-label="gridUi.roomStatusAria"
        >
          <span
            v-if="room.door_state === 'closed'"
            class="room-badge room-badge--closed"
            :title="gridUi.badgeClosedTitle"
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" stroke-width="1.5" />
              <path d="M5.5 7V5.5a2.5 2.5 0 0 1 5 0V7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgeClosed }}
          </span>
          <span
            v-else-if="room.door_state === 'open'"
            class="room-badge room-badge--open"
            :title="gridUi.badgeOpenTitle"
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <rect x="3" y="7" width="10" height="7" rx="1.5" stroke="currentColor" stroke-width="1.5" />
              <path d="M5.5 7V5.5a2.5 2.5 0 0 1 4.2-1.83" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgeOpen }}
          </span>
          <span v-if="room.is_permanent" class="room-badge room-badge--permanent" :title="gridUi.badgePermanentTitle">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3.2 8c1.7-2.4 3.1-2.4 4.8 0s3.1 2.4 4.8 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
              <path d="M3.2 8c1.7 2.4 3.1 2.4 4.8 0s3.1-2.4 4.8 0" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgePermanentLabel }}
          </span>
          <span v-if="room.is_private" class="room-badge room-badge--private" :title="gridUi.badgePrivateTitle">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="5" r="2.5" stroke="currentColor" stroke-width="1.5" />
              <path d="M3.5 14c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgePrivateLabel }}
          </span>
          <span v-if="room.observable === false" class="room-badge room-badge--hidden" :title="gridUi.badgeHiddenTitle">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M2 2l12 12" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              <path d="M6.5 6.2a2 2 0 0 0 2.7 2.7" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              <path d="M4.8 4.6C3.6 5.3 2.6 6.4 2 8c1.2 3 3.5 4.5 6 4.5.8 0 1.6-.2 2.3-.5M8.9 3.6c2.2.3 4.1 1.8 5.1 4.4-.3.8-.8 1.5-1.3 2" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgeHiddenLabel }}
          </span>
          <span
            v-if="room.max_concurrent_agents > 0 && room.member_count >= room.max_concurrent_agents"
            class="room-badge room-badge--full"
            :title="gridUi.badgeFullTitle"
          >
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="5.5" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.4" />
              <circle cx="10.5" cy="5.5" r="2.5" stroke="currentColor" stroke-width="1.4" />
              <path d="M2 14c0-2.3 1.6-4 3.5-4M8 14c0-2.3 1.1-4 3.5-4" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
            </svg>
            {{ gridUi.badgeFullLabel }}
          </span>
        </div>
        <p class="room-name">{{ room.name }}</p>
        <p v-if="room.brief" class="room-brief">{{ room.brief }}</p>
      </div>

      <div class="room-card__footer">
        <div class="room-meta">
          <span class="room-id">#{{ room.room_id.slice(0, 8) }}</span>
          <span v-if="!room.is_permanent" class="room-creator">
            <svg width="10" height="10" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="8" cy="5.5" r="3.5" stroke="currentColor" stroke-width="1.6" />
              <path d="M1.5 14c0-3.038 2.91-5.5 6.5-5.5s6.5 2.462 6.5 5.5" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
            </svg>
            {{ room.creator_name }}
          </span>
        </div>
        <div class="room-card__right">
          <span class="room-count-pill" :class="{ 'room-count-pill--empty': room.member_count === 0 }">
            <svg width="11" height="11" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <circle cx="5.5" cy="5" r="2.8" stroke="currentColor" stroke-width="1.5" />
              <circle cx="11" cy="5" r="2.8" stroke="currentColor" stroke-width="1.5" />
              <path d="M0 14c0-2.5 2.46-4.5 5.5-4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
              <path d="M7.5 14c0-2.5 1.57-4.5 5-4.5s5 2 5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" />
            </svg>
            {{ room.member_count }}<span class="room-count-max">/{{ room.max_concurrent_agents }} {{ gridUi.capSuffix }}</span>
          </span>
          <button
            class="watch-btn"
            type="button"
            :title="gridUi.watchTitle"
            :aria-label="gridUi.watchTitle"
            @click.stop="emit('openRoom', room)"
          >
            <svg class="watch-btn__icon" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M1.5 8C2.8 5.07 5.14 3.25 8 3.25S13.2 5.07 14.5 8c-1.3 2.93-3.64 4.75-6.5 4.75S2.8 10.93 1.5 8z"
                stroke="currentColor"
                stroke-width="1.35"
                stroke-linejoin="round"
              />
              <circle cx="8" cy="8" r="2.15" stroke="currentColor" stroke-width="1.35" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
