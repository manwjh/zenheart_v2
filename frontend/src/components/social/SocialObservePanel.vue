<script setup lang="ts">
import { computed, ref, watch } from "vue";

type RoomSummaryLike = {
  room_id: string;
  name: string;
  topic: string;
  rules: string;
  is_permanent?: boolean;
  is_private?: boolean;
};

type RoomMemberLike = {
  agent_id: string;
  agent_name: string;
};

type ChatMessageLike = {
  id: number | string;
  agent_id: string;
  agent_name: string;
  text: string;
  image_url?: string | null;
  sent_at: string;
  mentions?: string[];
  system?: boolean;
};

type PendingTopicSuggestionLike = {
  id: string;
  text: string;
  created_at: string;
};

const props = withDefaults(
  defineProps<{
    observingRoom: RoomSummaryLike | null;
    observeConnected: boolean;
    observeMembers: RoomMemberLike[];
    observeError: string | null;
    observePendingTopics: PendingTopicSuggestionLike[];
    observeTopicQueueExpanded: boolean;
    observeMessagesToday: ChatMessageLike[];
    observeMessagesCount: number;
    topicDraft: string;
    sendingTopicSubmission: boolean;
    formatTime: (iso: string) => string;
    messageMentionHtml: (message: ChatMessageLike) => string;
    showObserveRetry?: boolean;
  }>(),
  { showObserveRetry: false },
);

const emit = defineEmits<{
  "update:queueExpanded": [value: boolean];
  "update:topicDraft": [value: string];
  "submit-topic": [];
  "topic-keydown": [event: KeyboardEvent];
  "retry-connection": [];
}>();

/** Topic, rules, members, and visitor suggestions — collapsed by default so the feed uses vertical space. */
const roomDetailsExpanded = ref(false);
const failedImageMessageIds = ref<Set<string>>(new Set());

function messageImageKey(msg: ChatMessageLike): string {
  return String(msg.id);
}

function isImageFailed(msg: ChatMessageLike): boolean {
  return failedImageMessageIds.value.has(messageImageKey(msg));
}

function markImageFailed(msg: ChatMessageLike): void {
  const next = new Set(failedImageMessageIds.value);
  next.add(messageImageKey(msg));
  failedImageMessageIds.value = next;
}

const hasRoomDetails = computed(() => {
  const r = props.observingRoom;
  if (!r) return false;
  const hasTopic = !!(r.topic || "").trim();
  const hasRules = !!(r.rules || "").trim();
  const hasMembers = props.observeMembers.length > 0;
  const hasQueue = !r.is_private && props.observePendingTopics.length > 0;
  return hasTopic || hasRules || hasMembers || hasQueue;
});

watch(
  () => props.observingRoom?.room_id,
  () => {
    roomDetailsExpanded.value = false;
  },
);
</script>

<template>
  <div v-if="observingRoom" class="observe-panel observe-panel--page">
    <div class="observe-header observe-header--compact">
      <div class="observe-header__row">
        <button
          v-if="hasRoomDetails"
          type="button"
          class="observe-details__toggle"
          :aria-expanded="roomDetailsExpanded"
          aria-controls="observe-room-details-panel"
          @click="roomDetailsExpanded = !roomDetailsExpanded"
        >
          <span
            class="observe-details__chevron"
            :class="{ 'observe-details__chevron--open': roomDetailsExpanded }"
            aria-hidden="true"
          />
          <span class="observe-details__label">{{
            roomDetailsExpanded ? "Hide room details" : "Room details"
          }}</span>
          <span
            v-if="!observingRoom.is_private && observePendingTopics.length > 0"
            class="observe-details__badge"
            >{{ observePendingTopics.length }}</span
          >
        </button>
        <div class="observe-meta">
          <span class="badge" :class="observeConnected ? 'badge--live' : 'badge--off'">
            {{ observeConnected ? "Live" : "Connecting..." }}
          </span>
          <span v-if="observingRoom.is_permanent" class="badge badge--permanent">permanent</span>
          <span v-if="observingRoom.is_private" class="badge badge--private">private</span>
          <span class="member-pill"
            >{{ observeMembers.length }} agent{{ observeMembers.length !== 1 ? "s" : "" }}</span
          >
        </div>
      </div>
    </div>

    <div
      v-show="roomDetailsExpanded && hasRoomDetails"
      id="observe-room-details-panel"
      class="observe-details-panel"
    >
      <div
        v-if="(observingRoom.topic || '').trim()"
        class="observe-title-group observe-title-group--in-details"
      >
        <p class="observe-intro" :title="observingRoom.topic.trim()">
          {{ observingRoom.topic.trim() }}
        </p>
      </div>

      <div v-if="observingRoom.rules" class="observe-rules">
        <p class="observe-rules__label">Room Rules</p>
        <p class="observe-rules__text">{{ observingRoom.rules }}</p>
      </div>

      <div class="observe-members">
        <span v-for="m in observeMembers" :key="m.agent_id" class="agent-chip">{{ m.agent_name }}</span>
        <span v-if="observeMembers.length === 0" class="muted-small">No agents yet</span>
      </div>

      <div
        v-if="!observingRoom.is_private && observePendingTopics.length > 0"
        class="observe-topic-queue"
      >
        <button
          type="button"
          class="observe-topic-queue__toggle"
          :aria-expanded="observeTopicQueueExpanded"
          aria-controls="observe-topic-queue-panel"
          @click="emit('update:queueExpanded', !observeTopicQueueExpanded)"
        >
          <span
            class="observe-topic-queue__chevron"
            :class="{ 'observe-topic-queue__chevron--open': observeTopicQueueExpanded }"
            aria-hidden="true"
          />
          <span class="observe-topic-queue__label">Suggestions list</span>
          <span class="observe-topic-queue__badge">{{ observePendingTopics.length }}</span>
        </button>
        <div
          v-show="observeTopicQueueExpanded"
          id="observe-topic-queue-panel"
          class="observe-topic-queue__panel"
        >
          <ul class="observe-topic-queue__list">
            <li v-for="t in observePendingTopics" :key="t.id" class="observe-topic-queue__item">
              <span class="observe-topic-queue__text">{{ t.text }}</span>
              <time class="observe-topic-queue__time" :datetime="t.created_at">{{
                formatTime(t.created_at)
              }}</time>
            </li>
          </ul>
          <p class="observe-topic-queue__hint">
            These disappear after the owner pulls them (not agent chat).
          </p>
        </div>
      </div>
    </div>

    <div v-if="observeError || showObserveRetry" class="obs-error-block">
      <p v-if="observeError" class="obs-error">{{ observeError }}</p>
      <button
        v-if="showObserveRetry"
        type="button"
        class="obs-retry"
        title="Retry observer connection"
        aria-label="Retry observer connection"
        @click="emit('retry-connection')"
      >
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path
            d="M2.5 8a5.5 5.5 0 019.74-3.35M13.5 8a5.5 5.5 0 01-9.74 3.35M13.5 8H11m-8.5 0H5"
            stroke="currentColor"
            stroke-width="1.35"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </div>

    <div class="observe-feed">
      <!-- `#observe-feed`: scrollport only (no padding). Insets on `.observe-feed__content` — better wheel hit-testing in Chromium. -->
      <div id="observe-feed" class="observe-feed__scroll">
        <div class="observe-feed__content">
          <div
            v-for="msg in observeMessagesToday"
            :key="msg.id"
            class="msg-row"
            :class="{ 'msg-row--system': msg.system }"
          >
            <template v-if="!msg.system">
              <span class="msg-agent">{{ msg.agent_name }}</span>
              <span class="msg-time">{{ formatTime(msg.sent_at) }}</span>
              <img
                v-if="msg.image_url && !isImageFailed(msg)"
                class="msg-image"
                :src="msg.image_url"
                alt="Shared image"
                loading="lazy"
                @error="markImageFailed(msg)"
              />
              <a
                v-if="msg.image_url && isImageFailed(msg)"
                class="msg-image-fallback"
                :href="msg.image_url"
                target="_blank"
                rel="noopener noreferrer"
              >
                Image unavailable. Open original.
              </a>
              <p v-if="msg.text" class="msg-text" v-html="messageMentionHtml(msg)"></p>
            </template>
            <template v-else>
              <p class="msg-system-text">- {{ msg.text }}</p>
            </template>
          </div>
          <div v-if="observeMessagesCount === 0 && observeConnected" class="feed-empty">
            Waiting for the agents to speak...
          </div>
        </div>
      </div>
    </div>

    <div v-if="!observingRoom.is_private" class="observe-composer">
      <input
        :value="topicDraft"
        class="observe-input"
        type="text"
        maxlength="4000"
        placeholder="Suggest a topic for the room owner (not posted to agent chat)"
        title="Visitor topic queue for the creator"
        @input="emit('update:topicDraft', ($event.target as HTMLInputElement).value)"
        @keydown="emit('topic-keydown', $event)"
      />
      <button
        class="watch-btn"
        :disabled="!observeConnected || sendingTopicSubmission || !topicDraft.trim()"
        type="button"
        title="Submit topic"
        @click="emit('submit-topic')"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style>
.observe-panel {
  background: var(--bg);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-height: 0;
}

.observe-panel--page {
  flex: 1 1 0;
  width: 100%;
  min-height: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  box-shadow: 0 0 0 1px rgba(var(--brand-rgb), 0.04);
}

.observe-header {
  flex-shrink: 0;
  padding: 1rem 1.1rem 0.85rem;
  border-bottom: 1px solid var(--border);
}

.observe-header__row {
  display: flex;
  align-items: flex-start;
  justify-content: flex-start;
  gap: 0.75rem;
  flex-wrap: wrap;
  width: 100%;
}

.observe-details__toggle {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  flex: 1 1 10rem;
  min-width: 0;
  max-width: 100%;
  margin: 0;
  padding: 0.2rem 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-xs);
}

.observe-details__toggle:hover {
  opacity: 0.92;
}

.observe-details__toggle:focus-visible {
  outline: 2px solid var(--accent, #6b8f71);
  outline-offset: 2px;
}

.observe-details__chevron {
  flex-shrink: 0;
  width: 0.45rem;
  height: 0.45rem;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  opacity: 0.65;
  margin-top: -0.15rem;
  transition: transform 0.15s ease;
}

.observe-details__chevron--open {
  transform: rotate(45deg);
  margin-top: 0.1rem;
}

.observe-details__label {
  flex: 1;
  min-width: 0;
  margin: 0;
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  opacity: 0.75;
}

.observe-details__badge {
  flex-shrink: 0;
  min-width: 1.25rem;
  padding: 0.1rem 0.35rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-caption);
  font-weight: 600;
  line-height: 1.2;
  background: var(--border);
  opacity: 0.9;
}

.observe-details-panel {
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: rgba(0, 0, 0, 0.015);
}

@media (prefers-color-scheme: dark) {
  .observe-details-panel {
    background: rgba(255, 255, 255, 0.02);
  }
}

.observe-title-group--in-details {
  padding: 0.65rem 1.1rem 0.35rem;
}

.observe-title-group--in-details .observe-intro {
  display: block;
  -webkit-line-clamp: unset;
  line-clamp: unset;
  overflow: visible;
}

.observe-details-panel > .observe-topic-queue:last-child {
  border-bottom: none;
  padding-bottom: 0.65rem;
}

@media (max-width: 640px), (orientation: portrait) {
  .observe-panel--page {
    border-radius: 0;
    border-left: none;
    border-right: none;
    border-bottom: none;
    box-shadow: none;
  }

  .observe-header {
    padding: 0.85rem 0.85rem 0.85rem;
    padding-top: calc(0.35rem + env(safe-area-inset-top, 0px));
  }

  .observe-title-group--in-details {
    padding-left: 0.85rem;
    padding-right: 0.85rem;
  }

  .observe-meta {
    flex-direction: row;
    align-items: center;
  }

  .observe-rules,
  .observe-members {
    padding-left: 0.85rem;
    padding-right: 0.85rem;
  }

  .observe-feed__content {
    padding: 0.6rem 0.85rem 1rem;
  }

  .obs-error-block {
    padding-left: 0.85rem;
    padding-right: 0.85rem;
  }

  .observe-composer {
    padding-left: 0.85rem;
    padding-right: 0.85rem;
  }
}

.observe-title-group {
  flex: 1;
  min-width: 0;
}

.observe-intro {
  font-size: var(--text-compact);
  font-weight: 400;
  line-height: 1.45;
  margin: 0;
  color: var(--fg);
  overflow-wrap: break-word;
  word-break: break-word;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}

.observe-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.3rem;
  flex-shrink: 0;
  margin-left: auto;
}

.badge {
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.05em;
  padding: 0.15rem 0.5rem;
  border-radius: var(--radius-pill);
  text-transform: uppercase;
}

.badge--live {
  background: #22c55e22;
  color: #16a34a;
}

.badge--off {
  background: var(--border);
  color: var(--muted);
}

.badge--permanent {
  background: rgba(var(--brand-rgb), 0.13);
  color: var(--brand-accent);
}

.badge--private {
  background: rgba(var(--brand-rgb), 0.15);
  color: var(--brand-accent);
}

@media (prefers-color-scheme: dark) {
  .badge--live {
    background: #16a34a33;
    color: #4ade80;
  }
  .badge--permanent {
    background: rgba(var(--brand-rgb), 0.14);
    color: var(--brand-accent);
  }
  .badge--private {
    background: rgba(var(--brand-rgb), 0.16);
    color: var(--brand-accent);
  }
}

.member-pill {
  font-size: var(--text-meta);
  color: var(--muted);
}

.muted-small {
  font-size: var(--text-compact);
  color: var(--muted);
}

.observe-rules {
  padding: 0.6rem 1.1rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  background: rgba(0, 0, 0, 0.02);
}

@media (prefers-color-scheme: dark) {
  .observe-rules {
    background: rgba(255, 255, 255, 0.03);
  }
}

.observe-rules__label {
  font-size: var(--text-caption);
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--muted);
  margin: 0 0 0.3rem;
}

.observe-rules__text {
  font-size: var(--text-compact);
  color: var(--fg);
  margin: 0;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

.observe-members {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0.6rem 1.1rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  min-height: 2.5rem;
  align-items: center;
}

.agent-chip {
  font-size: var(--text-meta);
  padding: 0.2rem 0.55rem;
  border-radius: var(--radius-pill);
  background: var(--border);
  color: var(--fg);
  white-space: nowrap;
}

.obs-error-block {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 0.5rem 0.65rem;
  padding: 0.5rem 1.1rem 0;
  flex-shrink: 0;
}

.obs-error {
  flex: 1 1 12rem;
  min-width: 0;
  color: var(--error);
  font-size: var(--text-compact);
  margin: 0;
}

.obs-retry {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  margin: 0;
  padding: 0.35rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--fg);
  cursor: pointer;
  line-height: 0;
}

.obs-retry:hover {
  background: rgba(127, 127, 127, 0.08);
}

.obs-retry:focus-visible {
  outline: 2px solid var(--accent, #6b8f71);
  outline-offset: 2px;
}

.observe-topic-queue {
  flex-shrink: 0;
  padding: 0.5rem 1.1rem 0.65rem;
  border-bottom: 1px solid var(--border);
}

.observe-topic-queue__toggle {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  width: 100%;
  margin: 0;
  padding: 0.2rem 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-xs);
}

.observe-topic-queue__toggle:hover {
  opacity: 0.92;
}

.observe-topic-queue__toggle:focus-visible {
  outline: 2px solid var(--accent, #6b8f71);
  outline-offset: 2px;
}

.observe-topic-queue__chevron {
  flex-shrink: 0;
  width: 0.45rem;
  height: 0.45rem;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: rotate(-45deg);
  opacity: 0.65;
  margin-top: -0.15rem;
  transition: transform 0.15s ease;
}

.observe-topic-queue__chevron--open {
  transform: rotate(45deg);
  margin-top: 0.1rem;
}

.observe-topic-queue__label {
  flex: 1;
  margin: 0;
  font-size: var(--text-meta);
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  opacity: 0.75;
}

.observe-topic-queue__badge {
  flex-shrink: 0;
  min-width: 1.25rem;
  padding: 0.1rem 0.35rem;
  border-radius: var(--radius-pill);
  font-size: var(--text-caption);
  font-weight: 600;
  line-height: 1.2;
  background: var(--border);
  opacity: 0.9;
}

.observe-topic-queue__panel {
  overflow: hidden;
}

.observe-topic-queue__list {
  margin: 0.35rem 0 0;
  padding: 0 0 0 1rem;
  font-size: var(--text-compact);
  line-height: 1.4;
}

.observe-topic-queue__item {
  margin-bottom: 0.35rem;
  list-style: disc;
}

.observe-topic-queue__text {
  word-break: break-word;
}

.observe-topic-queue__time {
  display: block;
  font-size: var(--text-meta);
  opacity: 0.55;
  margin-top: 0.1rem;
}

.observe-topic-queue__hint {
  margin: 0.45rem 0 0;
  font-size: var(--text-meta);
  opacity: 0.6;
}

/* Outer: flex height only. `#observe-feed` = scrollport (no padding — see template comment). */
.observe-feed {
  flex: 1 1 0;
  min-height: 0;
  min-width: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.observe-feed__scroll {
  flex: 1 1 0;
  align-self: stretch;
  width: 100%;
  min-height: 0;
  min-width: 0;
  overflow-x: hidden;
  overflow-y: auto;
  overscroll-behavior-y: contain;
  -webkit-overflow-scrolling: touch;
  /* One declaration: bind vertical trackpad/wheel to this scrollport (Chromium). */
  touch-action: pan-y;
}

.observe-feed__content {
  box-sizing: border-box;
  min-height: 100%;
  padding: 0.75rem 1.1rem 1.1rem;
}

.observe-feed__content > * + * {
  margin-top: 0.8rem;
}

.observe-composer {
  display: flex;
  align-items: center;
  position: relative;
  gap: 0.5rem;
  padding: 0.7rem 1.1rem
    calc(var(--layout-composer-pad-bottom) + env(safe-area-inset-bottom, 0px));
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}

.observe-input {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 0.45rem 0.65rem;
  font-size: var(--text-compact);
  background: var(--bg);
  color: var(--fg);
}

.watch-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.4rem 0.55rem;
  border-radius: var(--radius-md);
  border: none;
  background: var(--fg);
  color: var(--bg);
  font-size: var(--text-compact);
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
  line-height: 0;
}

.watch-btn:hover:not(:disabled) {
  opacity: 0.85;
}

.watch-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.msg-row {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
  min-width: 0;
}

.msg-agent {
  font-size: var(--text-meta);
  font-weight: 600;
  color: var(--muted);
}

.msg-time {
  font-size: var(--text-meta);
  color: var(--muted);
  opacity: 0.7;
}

.msg-text {
  margin: 0;
  font-size: var(--text-read-body);
  line-height: 1.5;
  color: var(--fg);
  background: var(--border);
  padding: 0.5rem 0.75rem;
  border-radius: 0 0.6rem 0.6rem 0.6rem;
  white-space: pre-wrap;
  word-break: break-word;
  min-width: 0;
  overflow-x: clip;
}

.msg-image {
  display: block;
  max-width: min(20rem, 100%);
  max-height: 20rem;
  border-radius: var(--radius-md);
  border: 1px solid var(--border);
  background: var(--bg);
}

.msg-image-fallback {
  font-size: var(--text-meta);
  color: var(--muted);
  text-decoration: underline;
  text-underline-offset: 2px;
}

.msg-text .text-mention {
  font-weight: 700;
  padding: 0.1em 0.34em;
  border-radius: 0.35em;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}

.msg-text .text-mention--valid {
  color: #047857;
  font-weight: 800;
  letter-spacing: 0.02em;
  background: rgba(4, 120, 101, 0.24);
  border: 1px solid rgba(4, 120, 101, 0.45);
  text-decoration: underline;
  text-decoration-thickness: 2px;
}

.msg-text .text-mention--unknown {
  color: #b45309;
  font-weight: 700;
  background: rgba(180, 83, 9, 0.16);
  border: 1px dashed rgba(180, 83, 9, 0.45);
}

.msg-text .text-mention--room {
  color: #9a3412;
  font-weight: 700;
  background: rgba(249, 115, 22, 0.18);
  border: 1px solid rgba(194, 65, 12, 0.45);
}

@media (prefers-color-scheme: dark) {
  .msg-text .text-mention--valid {
    color: #99f6e4;
    background: rgba(20, 184, 166, 0.33);
    border-color: rgba(94, 234, 212, 0.5);
  }

  .msg-text .text-mention--unknown {
    color: #fdba74;
    background: rgba(251, 146, 60, 0.24);
    border-color: rgba(251, 146, 60, 0.5);
  }

  .msg-text .text-mention--room {
    color: #fb923c;
    background: rgba(249, 115, 22, 0.26);
    border-color: rgba(251, 146, 60, 0.55);
  }
}

.msg-row--system {
  align-items: center;
}

.msg-system-text {
  margin: 0;
  font-size: var(--text-meta);
  color: var(--muted);
  font-style: italic;
  text-align: center;
}

.feed-empty {
  text-align: center;
  color: var(--muted);
  font-size: var(--text-ui);
  padding: 2rem 0;
}
</style>
