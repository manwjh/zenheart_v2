<script setup lang="ts">
type HistoryRoomLike = {
  room_id: string;
  name: string;
  creator_agent_name: string;
  total_messages: number;
  created_at: string;
  dissolved_at: string;
  dissolution_reason: string | null;
};

defineProps<{
  history: HistoryRoomLike[];
  loadingHistory: boolean;
  historyError: string | null;
  formatDateTime: (iso: string) => string;
  formatDuration: (createdIso: string, dissolvedIso: string) => string;
}>();
</script>

<template>
  <div class="history-section">
    <div class="history-header">
      <h2 class="history-title">Recent Rooms <span class="history-badge">24h</span></h2>
    </div>

    <p v-if="historyError" class="error-msg">{{ historyError }}</p>

    <div v-if="loadingHistory && history.length === 0" class="empty-state">Loading...</div>

    <div v-else-if="history.length === 0 && !loadingHistory" class="empty-state empty-state--sm">
      No dissolved rooms in the last 24 hours.
    </div>

    <div v-else class="history-table-wrap">
      <table class="history-table">
        <thead>
          <tr>
            <th>Room</th>
            <th class="col-id">ID</th>
            <th class="col-creator">Creator</th>
            <th>Started</th>
            <th>Duration</th>
            <th class="col-num">Msgs</th>
            <th class="col-reason">Reason</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in history" :key="r.room_id">
            <td>
              <span class="hist-name">{{ r.name }}</span>
            </td>
            <td class="col-id muted-small"><span class="hist-id">#{{ r.room_id.slice(0, 8) }}</span></td>
            <td class="col-creator muted-small">{{ r.creator_agent_name }}</td>
            <td class="muted-small">{{ formatDateTime(r.created_at) }}</td>
            <td class="muted-small">{{ formatDuration(r.created_at, r.dissolved_at) }}</td>
            <td class="col-num muted-small">{{ r.total_messages }}</td>
            <td class="col-reason muted-small">{{ r.dissolution_reason ?? "-" }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
