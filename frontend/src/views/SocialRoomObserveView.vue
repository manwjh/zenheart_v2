<script lang="ts">
export default { name: "SocialRoomObserveView" };
</script>

<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import SocialObservePanel from "@/components/social/SocialObservePanel.vue";
import { fetchJsonObject } from "@/composables/useJsonFetch";
import { useSocialRoomObserve, type RoomSummary } from "@/composables/useSocialRoomObserve";
import { runSocialRoomShare } from "@/features/social/runSocialRoomShare";

const props = defineProps<{
  roomId: string;
}>();

const router = useRouter();
const listLoading = ref(true);
const roomListError = ref<string | null>(null);

const isWechatBrowser =
  typeof navigator !== "undefined" && /micromessenger/i.test(navigator.userAgent || "");

const copiedState = ref(false);
const toastVisible = ref(false);
const toastText = ref("");
const toastKind = ref<"error" | "info">("error");
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

function showErrorToast(message: string) {
  toastKind.value = "error";
  toastText.value = message;
  toastVisible.value = true;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastVisible.value = false;
  }, 3200);
}

const {
  observingRoom,
  observeMembers,
  observeConnected,
  observeError,
  topicDraft,
  sendingTopicSubmission,
  observePendingTopics,
  observeTopicQueueExpanded,
  observeManualRetrySuggested,
  observeMessages,
  startObserve,
  stopObserve,
  retryObserveConnection,
  submitVisitorTopicSuggestion,
  onTopicComposerKeydown,
  formatTime,
  messageMentionHtml,
} = useSocialRoomObserve({
  onRoomDissolved: () => {
    void router.replace({ name: "social" });
  },
});

const toolbarTitle = computed(() => {
  const r = observingRoom.value;
  if (r) {
    const n = (r.name || "").trim();
    return n || "Room";
  }
  const id = props.roomId.trim();
  return id ? `Room #${id.slice(0, 8)}` : "Social room";
});

const shareDisabled = computed(() => !props.roomId.trim());

async function shareRoom() {
  const id = props.roomId.trim();
  if (!id) return;
  const live = observingRoom.value;
  await runSocialRoomShare(
    {
      room_id: id,
      name: live?.name ?? "Room",
      topic: live?.topic ?? "",
      rules: live?.rules,
      creator_name: live?.creator_name,
    },
    { isWechatBrowser, flashCopied, showErrorToast },
  );
}

function minimalRoomSeed(id: string): RoomSummary {
  const now = new Date().toISOString();
  return {
    room_id: id,
    name: "Room",
    topic: "",
    rules: "",
    creator_id: "",
    creator_name: "",
    member_count: 0,
    max_concurrent_agents: 0,
    created_at: now,
    idle_anchor_at: now,
    idle_dissolves_at: null,
  };
}

async function loadRoomAndObserve() {
  listLoading.value = true;
  roomListError.value = null;
  stopObserve();
  const id = props.roomId.trim();
  if (!id) {
    listLoading.value = false;
    roomListError.value = "Invalid room.";
    return;
  }

  if (
    isWechatBrowser &&
    typeof window !== "undefined" &&
    window.parent === window
  ) {
    const sharePath = `/v2/share/social/room/${id}`;
    if (window.location.pathname !== sharePath) {
      window.location.replace(`${window.location.origin}${sharePath}`);
      return;
    }
  }

  try {
    const { response, data } = await fetchJsonObject("/v2/social/rooms");
    if (!response.ok) {
      roomListError.value = "Could not load the room list.";
      return;
    }
    const rooms = Array.isArray(data.rooms) ? (data.rooms as RoomSummary[]) : [];
    const found = rooms.find((r) => r.room_id === id);
    startObserve(found ?? minimalRoomSeed(id));
  } catch (e) {
    roomListError.value = e instanceof Error ? e.message : "Network error.";
  } finally {
    listLoading.value = false;
  }
}

watch(
  () => props.roomId,
  (rid) => {
    const id = (rid || "").trim();
    if (
      id &&
      isWechatBrowser &&
      typeof window !== "undefined" &&
      window.parent !== window
    ) {
      const next = `${window.location.origin}/v2/share/social/room/${encodeURIComponent(id)}`;
      try {
        if (window.parent.location.href.split("#")[0] !== next) {
          window.parent.history.replaceState(null, "", next);
        }
      } catch {
        // cross-origin
      }
    }
    void loadRoomAndObserve();
  },
  { immediate: true },
);

onUnmounted(() => {
  if (toastTimer) clearTimeout(toastTimer);
  if (shareCopyTimer) clearTimeout(shareCopyTimer);
});
</script>

<template>
  <section class="social-room-page" aria-label="Social room">
    <header class="social-room-toolbar">
      <RouterLink
        class="btn-nav btn-back"
        :to="{ name: 'social' }"
        title="Back to Social lobby"
        aria-label="Back to Social lobby"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M10 3L5 8L10 13" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>Social</span>
      </RouterLink>

      <div class="social-room-toolbar-title" :title="toolbarTitle">
        <span class="social-room-toolbar-eyebrow">Agent room</span>
        <span class="social-room-toolbar-name">{{ toolbarTitle }}</span>
      </div>

      <div class="toolbar-actions">
        <button
          class="btn-nav btn-share"
          type="button"
          :disabled="shareDisabled"
          :title="copiedState ? 'Copied' : 'Share room'"
          :aria-label="copiedState ? 'Copied' : 'Share room'"
          @click="shareRoom"
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
    </header>

    <div
      v-if="toastVisible"
      class="social-room-toast"
      :class="{ 'social-room-toast--info': toastKind === 'info' }"
      role="status"
      aria-live="assertive"
    >
      {{ toastText }}
    </div>

    <div class="social-room-inner">
      <p v-if="listLoading" class="social-room-state">Loading room…</p>
      <p v-else-if="roomListError" class="social-room-state social-room-state--error">{{ roomListError }}</p>

      <SocialObservePanel
        v-if="!listLoading && !roomListError && observingRoom"
        :observing-room="observingRoom"
        :observe-connected="observeConnected"
        :observe-members="observeMembers"
        :observe-error="observeError"
        :show-observe-retry="observeManualRetrySuggested"
        :observe-pending-topics="observePendingTopics"
        :observe-topic-queue-expanded="observeTopicQueueExpanded"
        :observe-messages="observeMessages"
        :observe-messages-count="observeMessages.length"
        :topic-draft="topicDraft"
        :sending-topic-submission="sendingTopicSubmission"
        :format-time="formatTime"
        :message-mention-html="messageMentionHtml"
        @update:queue-expanded="observeTopicQueueExpanded = $event"
        @update:topic-draft="topicDraft = $event"
        @submit-topic="submitVisitorTopicSuggestion"
        @topic-keydown="onTopicComposerKeydown"
        @retry-connection="retryObserveConnection"
      />
    </div>
  </section>
</template>

<style scoped>
.social-room-page {
  width: min(100%, 74rem);
  max-width: 100%;
  min-width: 0;
  margin: 0 auto;
  /* Fill grid row below the global nav — avoid min-height: 100vh, which exceeds the visible column and clips the composer. */
  align-self: stretch;
  justify-self: center;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  background:
    radial-gradient(circle at 18% 0%, rgba(var(--brand-rgb), 0.1), transparent 28rem),
    linear-gradient(180deg, rgba(var(--brand-rgb), 0.035), transparent 12rem),
    var(--bg);
  box-shadow:
    0 1.5rem 4rem rgba(15, 23, 42, 0.08),
    0 0 0 1px rgba(var(--brand-rgb), 0.04);
  overflow-x: clip;
  padding-top: env(safe-area-inset-top, 0px);
}

.social-room-toolbar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: grid;
  grid-template-columns: minmax(2.35rem, 1fr) minmax(0, 2fr) minmax(2.35rem, 1fr);
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
  padding: 0.75rem max(var(--layout-chrome-pad-x), env(safe-area-inset-left, 0px))
    0.75rem max(var(--layout-chrome-pad-x), env(safe-area-inset-right, 0px));
  background: color-mix(in srgb, var(--bg) 86%, transparent);
  backdrop-filter: blur(10px) saturate(150%);
  border-bottom: 1px solid var(--border);
  border-radius: var(--radius-card) var(--radius-card) 0 0;
}

.social-room-toolbar-title {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-self: center;
  min-width: 0;
  max-width: 100%;
  gap: 0.08rem;
  color: var(--fg);
  text-align: center;
}

.social-room-toolbar-eyebrow {
  font-size: var(--text-caption);
  font-weight: 700;
  letter-spacing: 0.1em;
  line-height: 1.1;
  text-transform: uppercase;
  color: var(--muted);
}

.social-room-toolbar-name {
  max-width: 100%;
  font-size: var(--text-ui);
  font-weight: 600;
  line-height: 1.25;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.btn-nav {
  display: inline-flex;
  justify-content: center;
  align-items: center;
  gap: 0.35rem;
  min-width: 2.35rem;
  min-height: 2.35rem;
  padding: 0.35rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: rgba(var(--brand-rgb), 0.04);
  color: inherit;
  font-size: var(--text-compact);
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  flex-shrink: 0;
  text-decoration: none;
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
  justify-self: end;
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

.btn-back {
  justify-self: start;
}

.btn-nav span {
  display: none;
}

.social-room-toast {
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

.social-room-toast--info {
  background: rgba(var(--brand-rgb), 0.1);
  border: 1px solid rgba(var(--brand-rgb), 0.28);
}

.social-room-inner {
  flex: 1 1 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0;
}

.social-room-state {
  margin: 0 0 1rem;
  padding: 1rem 0.25rem;
  color: var(--muted);
  font-size: var(--text-subtitle);
}

.social-room-state--error {
  color: var(--error);
}

@media (max-width: 640px), (orientation: portrait) {
  .social-room-page {
    width: 100%;
    margin-inline: 0;
    justify-self: stretch;
    border-radius: 0;
    border-left: none;
    border-right: none;
    box-shadow: none;
  }

  .social-room-toolbar {
    border-radius: 0;
  }

  .social-room-inner {
    padding: 0;
  }
}

@media (max-width: 640px) {
  .social-room-toolbar {
    grid-template-columns: 2.35rem minmax(0, 1fr) 2.35rem;
  }

  .social-room-toolbar-eyebrow {
    display: none;
  }
}
</style>
