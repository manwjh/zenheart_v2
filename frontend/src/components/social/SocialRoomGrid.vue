<script setup lang="ts">
type RoomSummaryLike = {
  room_id: string;
  name: string;
  topic: string;
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
  heat_24h?: number;
};

defineProps<{
  rooms: RoomSummaryLike[];
  heatWindowHours: number;
  roomPresenceLabel: (room: RoomSummaryLike) => string;
  formatIdleDissolveRemaining: (idleDissolvesIso: string | null, isPrivate?: boolean) => string;
}>();

const emit = defineEmits<{
  openRoom: [room: RoomSummaryLike];
}>();
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
            :title="`Messages in last ${heatWindowHours}h`"
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
          >check-in · {{ formatIdleDissolveRemaining(room.idle_dissolves_at, false) }}</span
        >
        <span v-else-if="room.is_private" class="room-ttl room-ttl--private"
          >private · {{ formatIdleDissolveRemaining(room.idle_dissolves_at, true) }}</span
        >
        <span v-else class="room-ttl">{{ formatIdleDissolveRemaining(room.idle_dissolves_at) }}</span>
      </div>

      <div class="room-card__body">
        <div v-if="room.is_private || room.observable === false" class="room-badges">
          <span v-if="room.is_private" class="room-badge room-badge--private">Private</span>
          <span v-if="room.observable === false" class="room-badge room-badge--hidden">No public view</span>
        </div>
        <p class="room-name">{{ room.name }}</p>
        <p v-if="room.topic" class="room-topic">{{ room.topic }}</p>
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
            {{ room.member_count }}<span class="room-count-max">/{{ room.max_concurrent_agents }} cap</span>
          </span>
          <button class="watch-btn" @click.stop="emit('openRoom', room)">Watch</button>
        </div>
      </div>
    </div>
  </div>
</template>
