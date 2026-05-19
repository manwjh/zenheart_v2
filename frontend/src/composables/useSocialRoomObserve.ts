import { onUnmounted, ref } from "vue";
import { createWebSocketChannel } from "@/composables/useWebSocketChannel";
import { normalizePendingTopicSuggestions, type PendingTopicSuggestion } from "@/features/social/socialHelpers";
import {
  formatTextWithMentionSpansWithHints,
  type MentionHint,
} from "@/utils/mentions";

export type RoomSummary = {
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
  idle_dissolves_at: string | null;
  is_permanent?: boolean;
  is_private?: boolean;
  observable?: boolean;
  door_state?: "open" | "closed";
  heat_24h?: number;
};

type RoomMember = {
  agent_id: string;
  agent_name: string;
  joined_at: string;
};

type ChatMessage = {
  id: number | string;
  agent_id: string;
  agent_name: string;
  text: string;
  image_url?: string | null;
  sent_at: string;
  mentions?: string[];
  system?: boolean;
};

export type UseSocialRoomObserveOptions = {
  /** Called when the server reports the room dissolved (e.g. navigate back to lobby). */
  onRoomDissolved?: (roomId: string) => void;
};

export function useSocialRoomObserve(options: UseSocialRoomObserveOptions = {}) {
  const observingRoom = ref<RoomSummary | null>(null);
  const observeMembers = ref<RoomMember[]>([]);
  const observeMessages = ref<ChatMessage[]>([]);
  const observeConnected = ref(false);
  const observeError = ref<string | null>(null);
  const topicDraft = ref("");
  const sendingTopicSubmission = ref(false);
  const observePendingTopics = ref<PendingTopicSuggestion[]>([]);
  const observeTopicQueueExpanded = ref(false);
  const observeManualRetrySuggested = ref(false);
  const pendingObserveSubscribeRoomId = ref<string | null>(null);
  let observeWs: WebSocket | null = null;
  let observeChannel: ReturnType<typeof createWebSocketChannel> | null = null;
  let msgSeq = 0;

  function nextLocalMessageSeq(): number {
    msgSeq += 1;
    return msgSeq;
  }

  /** Prefer server `id` (room message UUID); matches `GET` room history keys. */
  function resolveObserveMessageId(serverId: unknown): number | string {
    if (typeof serverId === "string" && serverId.trim()) return serverId.trim();
    return nextLocalMessageSeq();
  }

  /** Match server `get_room_messages` default; keep UI list bounded during long observe sessions. */
  const OBSERVE_FEED_MAX_MESSAGES = 50;

  function capObserveMessages() {
    if (observeMessages.value.length > OBSERVE_FEED_MAX_MESSAGES) {
      observeMessages.value = observeMessages.value.slice(-OBSERVE_FEED_MAX_MESSAGES);
    }
  }

  function observeSubscribePayload(roomId: string): Record<string, string> {
    return {
      type: "subscribe",
      room_id: roomId,
    };
  }

  function observeSocketShouldReconnect(ev: CloseEvent): boolean {
    if (ev.wasClean && ev.code === 1000) return false;
    if (ev.code === 4401) return false;
    if (ev.code === 1003) return false;
    const r = (ev.reason || "").toLowerCase();
    if (r.includes("invalid_observe_token")) return false;
    if (r === "room_dissolved") return false;
    return true;
  }

  function disconnectObserver() {
    pendingObserveSubscribeRoomId.value = null;
    observeChannel?.disconnect();
    observeChannel = null;
    observeWs = null;
    observeConnected.value = false;
    observeManualRetrySuggested.value = false;
    sendingTopicSubmission.value = false;
    observePendingTopics.value = [];
  }

  function connectObserver(roomId: string) {
    disconnectObserver();
    observeManualRetrySuggested.value = false;
    pendingObserveSubscribeRoomId.value = null;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    observeChannel = createWebSocketChannel({
      url: `${proto}://${location.host}/v2/social/observe`,
      reconnect: {
        initialDelayMs: 1200,
        maxDelayMs: 30_000,
        maxAttempts: 18,
        shouldReconnect: observeSocketShouldReconnect,
        onScheduled: () => {
          observeError.value = "Connection lost. Reconnecting…";
        },
        onExhausted: () => {
          observeManualRetrySuggested.value = true;
          observeError.value =
            "Could not restore the observer connection. Tap retry or reopen the room.";
        },
      },
      onOpen: (ws) => {
        observeWs = ws;
        const t = (import.meta.env.VITE_SOCIAL_OBSERVE_TOKEN as string | undefined)?.trim();
        if (t) {
          pendingObserveSubscribeRoomId.value = roomId;
          ws.send(JSON.stringify({ type: "auth_observe", token: t }));
        } else {
          ws.send(JSON.stringify(observeSubscribePayload(roomId)));
        }
      },
      onMessage: (raw) => {
        try {
          const frame = JSON.parse(raw);
          handleObserveFrame(frame);
        } catch {
          // ignore malformed frames
        }
      },
      onError: () => {
        observeError.value = "WebSocket error.";
      },
      onClose: (ev) => {
        observeConnected.value = false;
        observeWs = null;
        if (ev.reason === "room_dissolved") {
          pushSystemMessage("This room has been dissolved.");
        }
      },
    });
    observeWs = observeChannel.connect();
  }

  let scrollRaf1: number | null = null;
  let scrollRaf2: number | null = null;

  function cancelPendingScrollToBottom() {
    if (scrollRaf1 !== null) {
      cancelAnimationFrame(scrollRaf1);
      scrollRaf1 = null;
    }
    if (scrollRaf2 !== null) {
      cancelAnimationFrame(scrollRaf2);
      scrollRaf2 = null;
    }
  }

  /** After layout/paint so `scrollHeight` is final. `#observe-feed` = scrollport (padding on `.observe-feed__content`). */
  function scrollToBottom() {
    if (scrollRaf1 !== null) return;
    scrollRaf1 = requestAnimationFrame(() => {
      scrollRaf1 = null;
      scrollRaf2 = requestAnimationFrame(() => {
        scrollRaf2 = null;
        const el = document.getElementById("observe-feed");
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
  }

  function pushSystemMessage(text: string) {
    observeMessages.value.push({
      id: nextLocalMessageSeq(),
      agent_id: "",
      agent_name: "System",
      text,
      sent_at: new Date().toISOString(),
      system: true,
    });
    capObserveMessages();
    scrollToBottom();
  }

  function handleObserveFrame(frame: Record<string, unknown>) {
    const type = frame.type as string;

    if (type === "ping") {
      if (observeWs && observeWs.readyState === WebSocket.OPEN) {
        observeWs.send(JSON.stringify({ type: "pong" }));
      }
      return;
    }

    if (type === "auth_observe_ok") {
      const rid = pendingObserveSubscribeRoomId.value;
      pendingObserveSubscribeRoomId.value = null;
      if (rid && observeWs && observeWs.readyState === WebSocket.OPEN) {
        observeWs.send(JSON.stringify(observeSubscribePayload(rid)));
      }
      return;
    }
    if (type === "auth_ok") {
      const rid = pendingObserveSubscribeRoomId.value;
      pendingObserveSubscribeRoomId.value = null;
      if (rid && observeWs && observeWs.readyState === WebSocket.OPEN) {
        observeWs.send(JSON.stringify(observeSubscribePayload(rid)));
      }
      return;
    }
    if (type === "auth_fail") {
      pendingObserveSubscribeRoomId.value = null;
      observeError.value = `Observe auth failed: ${(frame.reason as string) || "unknown"}.`;
      return;
    }

    if (type === "subscribe_ok") {
      observeError.value = null;
      observeManualRetrySuggested.value = false;
      observeConnected.value = true;
      observeMembers.value = (frame.members as RoomMember[] | undefined) ?? [];
      if (observingRoom.value) {
        observingRoom.value = {
          ...observingRoom.value,
          name: (frame.name as string | undefined) ?? observingRoom.value.name,
          brief: (frame.brief as string | undefined) ?? observingRoom.value.brief,
          rules: (frame.rules as string) ?? observingRoom.value.rules,
          idle_dissolves_at:
            (frame.idle_dissolves_at as string | null | undefined) ?? observingRoom.value.idle_dissolves_at,
          is_private: (frame.is_private as boolean | undefined) ?? observingRoom.value.is_private,
          observable: (frame.observable as boolean | undefined) ?? observingRoom.value.observable,
          door_state:
            (frame.door_state as "open" | "closed" | undefined) ?? observingRoom.value.door_state,
          member_count: observeMembers.value.length,
        };
      }
      const recent = (frame.recent_messages as Array<Record<string, unknown>>) ?? [];
      if (recent.length > 0) {
        observeMessages.value = recent.map((m) => ({
          id: resolveObserveMessageId(m.id),
          agent_id: m.agent_id as string,
          agent_name: m.agent_name as string,
          text: m.text as string,
          image_url: (m.image_url as string | null | undefined) ?? null,
          sent_at: m.sent_at as string,
          mentions: (m.mentions as string[]) ?? [],
        }));
        capObserveMessages();
        scrollToBottom();
      }
      observePendingTopics.value = normalizePendingTopicSuggestions(frame.pending_topic_suggestions);
    } else if (type === "subscribe_fail") {
      const r = (frame.reason as string) || "";
      observeError.value =
        r === "not_observable"
          ? "This room is not open to public viewing — messages and members are not exposed."
          : `Cannot subscribe: ${r || "unknown"}`;
    } else if (type === "message") {
      observeMessages.value.push({
        id: resolveObserveMessageId(frame.id),
        agent_id: frame.agent_id as string,
        agent_name: frame.agent_name as string,
        text: frame.text as string,
        image_url: (frame.image_url as string | null | undefined) ?? null,
        sent_at: frame.sent_at as string,
        mentions: (frame.mentions as string[]) ?? [],
      });
      capObserveMessages();
      scrollToBottom();
    } else if (type === "member_joined") {
      const m = {
        agent_id: frame.agent_id as string,
        agent_name: frame.agent_name as string,
        joined_at: (frame.joined_at as string) || new Date().toISOString(),
      };
      if (m.agent_id) {
        observeMembers.value.push(m);
        if (observingRoom.value) {
          observingRoom.value = {
            ...observingRoom.value,
            member_count: observeMembers.value.length,
          };
        }
      }
    } else if (type === "member_left") {
      observeMembers.value = observeMembers.value.filter(
        (m) => m.agent_id !== (frame.agent_id as string),
      );
      if (observingRoom.value) {
        observingRoom.value = {
          ...observingRoom.value,
          member_count: observeMembers.value.length,
        };
      }
    } else if (type === "room_metadata_updated") {
      if (observingRoom.value) {
        observingRoom.value = {
          ...observingRoom.value,
          name: (frame.name as string | undefined) ?? observingRoom.value.name,
          brief: (frame.brief as string | undefined) ?? observingRoom.value.brief,
          rules: (frame.rules as string | undefined) ?? observingRoom.value.rules,
        };
      }
    } else if (type === "room_door_updated") {
      if (observingRoom.value) {
        observingRoom.value = {
          ...observingRoom.value,
          door_state:
            (frame.door_state as "open" | "closed" | undefined) ?? observingRoom.value.door_state,
        };
      }
      if (frame.door_state === "closed") {
        pushSystemMessage("The room door closed. New participants cannot enter.");
      }
    } else if (type === "room_state_cleared") {
      if (frame.cleared_messages === true) {
        observeMessages.value = [];
      }
      if (frame.cleared_signals === true) {
        observePendingTopics.value = [];
      }
      pushSystemMessage("The room owner cleared room state.");
    } else if (type === "room_dissolved") {
      const reason = frame.reason as string | undefined;
      pushSystemMessage(
        reason === "idle_timeout"
          ? "The room closed after extended silence (idle timeout)."
          : `The room has closed${reason ? ` (${reason})` : ""}.`,
      );
      observeConnected.value = false;
      const dissolvedId = frame.room_id as string;
      if (dissolvedId) {
        options.onRoomDissolved?.(dissolvedId);
      }
      observePendingTopics.value = [];
    } else if (type === "topic_suggestions_pending") {
      observePendingTopics.value = normalizePendingTopicSuggestions(frame.topics);
    } else if (type === "submit_topic_suggestion_ok") {
      sendingTopicSubmission.value = false;
    } else if (type === "error") {
      sendingTopicSubmission.value = false;
      const r = (frame.reason as string) || "unknown";
      observeError.value =
        r === "observe_auth_required" ? "Server requires observe token or agent auth." : r;
    }
  }

  function startObserve(room: RoomSummary) {
    observingRoom.value = { ...room };
    observeMembers.value = [];
    observeMessages.value = [];
    observePendingTopics.value = [];
    observeTopicQueueExpanded.value = false;
    observeConnected.value = false;
    observeError.value = null;
    observeManualRetrySuggested.value = false;
    topicDraft.value = "";
    connectObserver(room.room_id);
  }

  function stopObserve() {
    cancelPendingScrollToBottom();
    disconnectObserver();
    observingRoom.value = null;
    topicDraft.value = "";
  }

  function retryObserveConnection() {
    const room = observingRoom.value;
    if (!room) return;
    observeManualRetrySuggested.value = false;
    observeError.value = null;
    connectObserver(room.room_id);
  }

  function submitVisitorTopicSuggestion() {
    const room = observingRoom.value;
    const ws = observeWs;
    const text = topicDraft.value.trim();
    if (!room || !ws || ws.readyState !== WebSocket.OPEN) {
      observeError.value = "Not connected.";
      return;
    }
    if (!text) return;
    if (room.is_private) {
      observeError.value = "Topic suggestions are disabled for private rooms.";
      return;
    }
    sendingTopicSubmission.value = true;
    observeError.value = null;
    try {
      ws.send(
        JSON.stringify({
          type: "submit_topic_suggestion",
          room_id: room.room_id,
          text,
        }),
      );
      topicDraft.value = "";
    } catch {
      observeError.value = "Failed to send.";
      sendingTopicSubmission.value = false;
    }
  }

  function formatTime(iso: string): string {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  }

  function messageMentionHtml(msg: ChatMessage): string {
    const nameToId = new Map(
      observeMembers.value.map((m) => [m.agent_name.toLowerCase(), m.agent_id] as const),
    );
    const idToName = new Map(
      observeMembers.value.map((m) => [m.agent_id.toLowerCase(), m.agent_name] as const),
    );
    const mentionIds = new Set(msg.mentions ?? []);
    const mentionIdsLower = new Set([...mentionIds].map((id) => id.toLowerCase()));
    const hasServerMentionList = mentionIds.size > 0;
    return formatTextWithMentionSpansWithHints(msg.text, (n, rawToken): MentionHint | { hint: MentionHint; displayText?: string; title?: string } => {
      const id = n.startsWith("agt_") || n.startsWith("agn-") ? n : nameToId.get(n);
      const resolvedName = id ? idToName.get(id.toLowerCase()) : undefined;
      const isIdToken = n.startsWith("agt_") || n.startsWith("agn-");
      const preferDisplayName =
        isIdToken && Boolean(resolvedName) && resolvedName!.toLowerCase() !== n.toLowerCase();
      if (hasServerMentionList) {
        if (!id) return "room_only";
        const authoritative = mentionIds.has(id) || mentionIdsLower.has(id.toLowerCase());
        if (!authoritative) return "room_only";
        if (preferDisplayName) {
          return {
            hint: "authoritative",
            displayText: `@${resolvedName}`,
            title: rawToken,
          };
        }
        return "authoritative";
      }
      if (!id) return "stray";
      if (preferDisplayName) {
        return {
          hint: "room_only",
          displayText: `@${resolvedName}`,
          title: rawToken,
        };
      }
      return "room_only";
    });
  }

  onUnmounted(() => {
    stopObserve();
  });

  return {
    observingRoom,
    observeMembers,
    observeMessages,
    observeConnected,
    observeError,
    topicDraft,
    sendingTopicSubmission,
    observePendingTopics,
    observeTopicQueueExpanded,
    observeManualRetrySuggested,
    startObserve,
    stopObserve,
    retryObserveConnection,
    submitVisitorTopicSuggestion,
    formatTime,
    messageMentionHtml,
  };
}
