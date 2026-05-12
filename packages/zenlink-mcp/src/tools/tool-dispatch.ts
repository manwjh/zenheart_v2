/**
 * Shared tool implementations for **`ZenlinkSession`** in stdio mode.
 */

import { basename } from "node:path";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import {
  ackMsgbox,
  clearRoomStateHttp,
  fetchAgentNativeProtocolArtifact,
  fetchAgentNativeProtocolDiscovery,
  fetchAgentSocialRooms,
  fetchCurrentRoomMembers,
  fetchMsgbox,
  fetchMsgboxSummary,
  fetchSocialRoomMessages,
  fetchSocialRoomsHistory,
  fetchSocialRoomsLobby,
  patchAgentProfile,
  pullRoomTopicsHttp,
  sendAgentDirectMessage,
  updateRoomAccessListsHttp,
  updateRoomDoorHttp,
  updateRoomMetadataHttp,
  uploadAgentImage,
  parseAgentImageBase64Argument,
  defaultFilenameForImageContentType,
} from "../zenlink/index.js";
import type { ZenlinkAgentImageContentType } from "../zenlink/index.js";
import type { ZenlinkSession } from "../transport/session.js";
import {
  ZenlinkAckMessagesSchema,
  ZenlinkA2aSchema,
  ZenlinkConnectionSchema,
  ZenlinkCreateRoomSchema,
  ZenlinkGetRoomMessagesSchema,
  ZenlinkInboundPollSchema,
  ZenlinkInboundWaitSchema,
  ZenlinkJoinRoomSchema,
  ZenlinkMsgboxQuerySchema,
  ZenlinkPatchProfileSchema,
  ZenlinkProtocolArtifactSchema,
  ZenlinkPullRoomTopicsSchema,
  ZenlinkRoomAccessListsUpdateSchema,
  ZenlinkRoomDoorUpdateSchema,
  ZenlinkRoomMetadataUpdateSchema,
  ZenlinkRoomStateClearSchema,
  ZenlinkRoomSchema,
  ZenlinkSendDmSchema,
  ZenlinkSendMessageSchema,
  ZenlinkSendMessageToAllSchema,
  ZenlinkUploadImageSchema,
  ZenlinkWakeDrainSchema,
  ZenlinkWakePolicySchema,
} from "./tool-input-schemas.js";
import { readAgentImageBytesFromResolvedPath } from "./upload-image-from-path.js";

function compactToolJsonEnabled(): boolean {
  const v = process.env["ZENLINK_MCP_COMPACT_TOOL_JSON"];
  if (v === undefined || v.trim() === "") {
    return false;
  }
  const s = v.trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

/** JSON for MCP `text` tool content; pretty by default, single-line when compact env is on. */
export function stringifyZenlinkToolPayload(data: unknown): string {
  return compactToolJsonEnabled()
    ? JSON.stringify(data)
    : JSON.stringify(data, null, 2);
}

export function okJson(data: unknown): CallToolResult {
  return {
    content: [{ type: "text", text: stringifyZenlinkToolPayload(data) }],
  };
}

function toolError(e: unknown): CallToolResult {
  const message = e instanceof Error ? e.message : String(e);
  return {
    isError: true,
    content: [{ type: "text", text: message }],
  };
}

export async function toolTry<T>(
  fn: () => Promise<T>,
): Promise<CallToolResult> {
  try {
    return okJson(await fn());
  } catch (e) {
    return toolError(e);
  }
}

function msgboxQueryFromArgs(args: {
  unread_only?: boolean;
  limit?: number;
  before_id?: string;
}): { unread_only?: boolean; limit?: number; before_id?: string } | undefined {
  const q: {
    unread_only?: boolean;
    limit?: number;
    before_id?: string;
  } = {};
  if (args.unread_only !== undefined) q.unread_only = args.unread_only;
  if (args.limit !== undefined) q.limit = args.limit;
  if (args.before_id !== undefined) q.before_id = args.before_id;
  return Object.keys(q).length ? q : undefined;
}

type DoctorFinding = {
  id: string;
  severity: "info" | "warning" | "error";
  detail: string;
};

function sumRecordValues(record: unknown): number {
  if (!record || typeof record !== "object") return 0;
  return Object.values(record as Record<string, unknown>).reduce<number>(
    (total, value) => total + (typeof value === "number" ? value : 0),
    0,
  );
}

function timeAfter(left: unknown, right: unknown): boolean {
  if (typeof left !== "string" || typeof right !== "string") return false;
  const leftMs = Date.parse(left);
  const rightMs = Date.parse(right);
  return Number.isFinite(leftMs) && Number.isFinite(rightMs) && leftMs > rightMs;
}

function wakeDrainInstruction(queueDepth: number): string {
  const limit = Math.min(Math.max(queueDepth, 32), 500);
  const timeoutMs = queueDepth > 32 ? 0 : 1_000;
  return `Call zenlink_wake_drain with timeout_ms=${timeoutMs}, limit=${limit}, inbox_limit=10 before replying. Repeat until remaining_inbound_queue_depth is 0.`;
}

const COMMON_USER_WAKE_SIGNALS = [
  "room.message",
  "room.message_notify",
  "room.topic_suggestions_pending",
  "msgbox.notify",
] as const;

async function probeAgentNativeProtocolDiscovery(
  baseUrl: string,
): Promise<Record<string, unknown>> {
  try {
    const discovery = await fetchAgentNativeProtocolDiscovery({ baseUrl });
    const data = discovery as {
      protocol?: unknown;
      drafter?: unknown;
      artifacts?: unknown;
      bindings?: unknown;
    };
    return {
      available: data.protocol === "agent-native-site-world/v0.1",
      protocol: typeof data.protocol === "string" ? data.protocol : null,
      drafter: typeof data.drafter === "string" ? data.drafter : null,
      has_artifacts: Boolean(data.artifacts && typeof data.artifacts === "object"),
      has_bindings: Boolean(data.bindings && typeof data.bindings === "object"),
    };
  } catch (e) {
    return {
      available: false,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

async function buildZenlinkDoctorReport(session: ZenlinkSession): Promise<Record<string, unknown>> {
  const status = session.status();
  const push = status.openclaw_push;
  const wakePolicy = status.wake_policy;
  const protocol = await probeAgentNativeProtocolDiscovery(session.client.httpBaseUrl);
  const findings: DoctorFinding[] = [];
  const nextActions: string[] = [];

  if (!status.online) {
    findings.push({
      id: "daemon_ws_offline",
      severity: "error",
      detail: `ZenHeart WebSocket is ${status.connection_state}`,
    });
    nextActions.push("Call zenlink_start_long_lived, then re-run zenlink_doctor.");
  }

  if (!push.enabled) {
    findings.push({
      id: "push_disabled",
      severity: "error",
      detail: "OpenClaw hook base/token are missing in the MCP environment.",
    });
    nextActions.push("Re-run install-openclaw.sh so hook env is merged into the MCP server.");
  } else {
    if (!push.session_key) {
      findings.push({
        id: "session_key_missing",
        severity: "warning",
        detail: "OpenClaw hook POSTs do not include a request-level sessionKey.",
      });
      nextActions.push("Re-run install-openclaw.sh so ZENLINK_MCP_OPENCLAW_SESSION_KEY is persisted.");
    }
    if (push.last_http_status !== null && push.last_http_status >= 400) {
      findings.push({
        id: "push_post_failed",
        severity: "error",
        detail: `Last OpenClaw hook POST returned HTTP ${push.last_http_status}.`,
      });
      nextActions.push("Check OpenClaw Gateway is running and hooks.token matches ZENLINK_MCP_OPENCLAW_HOOK_TOKEN.");
    }
    if (push.pending_wake_count > 0) {
      findings.push({
        id: "push_pending_retry",
        severity: "warning",
        detail: `${push.pending_wake_count} wake requests are pending retry.`,
      });
    }
    if (push.last_error) {
      findings.push({
        id: "push_last_error",
        severity: "warning",
        detail: push.last_error,
      });
    }
  }

  const skippedTotal =
    sumRecordValues(push.skipped_frame_type_filter_by_type) +
    sumRecordValues(push.skipped_signal_policy_by_signal) +
    sumRecordValues(push.skipped_dedupe_by_type) +
    sumRecordValues(push.skipped_room_line_coalesce_by_type);
  if (skippedTotal > 0) {
    findings.push({
      id: "push_skips_observed",
      severity: "info",
      detail: `${skippedTotal} inbound frames were intentionally skipped by filter/signal-policy/dedupe/coalesce rules.`,
    });
  }

  if (wakePolicy.mode === "allowlist") {
    const configured = new Set(wakePolicy.wake_signals ?? []);
    const missingCommonSignals = COMMON_USER_WAKE_SIGNALS.filter((signal) => !configured.has(signal));
    if (missingCommonSignals.length > 0) {
      findings.push({
        id: "wake_policy_common_signals_excluded",
        severity: "warning",
        detail: `Wake policy allowlist excludes common user-facing signals: ${missingCommonSignals.join(", ")}.`,
      });
      nextActions.push("Call zenlink_connection action=wake_policy with action=get to inspect, or action=set/reset to adjust.");
    }
  }

  if (
    status.last_inbound_enqueue_at &&
    push.enabled &&
    !push.last_success_at &&
    skippedTotal === 0 &&
    push.pending_wake_count === 0
  ) {
    findings.push({
      id: "inbound_received_but_no_push_success",
      severity: "error",
      detail: "Inbound frames were queued, but no successful OpenClaw hook POST is recorded.",
    });
    nextActions.push("Inspect openclaw_push.last_failed_frame and last_error; verify hook delivery mode and Gateway reachability.");
  }

  if (
    status.last_inbound_enqueue_at &&
    push.last_success_at &&
    timeAfter(status.last_inbound_enqueue_at, push.last_success_at) &&
    skippedTotal === 0
  ) {
    findings.push({
      id: "latest_inbound_after_last_push",
      severity: "warning",
      detail: "The latest inbound enqueue is newer than the latest successful OpenClaw hook POST.",
    });
    nextActions.push("Send a fresh room message, then confirm openclaw_push.sent_total increments.");
  }

  if (
    status.inbound_queue_depth > 0 &&
    (!status.last_inbound_dequeue_at ||
      timeAfter(status.last_inbound_enqueue_at, status.last_inbound_dequeue_at))
  ) {
    findings.push({
      id: "inbound_waiting_for_drain",
      severity: "warning",
      detail: `${status.inbound_queue_depth} inbound frame(s) are queued and not yet drained.`,
    });
    nextActions.push(wakeDrainInstruction(status.inbound_queue_depth));
  }

  if (!protocol.available) {
    findings.push({
      id: "protocol_discovery_unavailable",
      severity: "warning",
      detail: "Agent-Native Site World Protocol discovery is not available from the configured ZenHeart server.",
    });
    nextActions.push("Call zenlink_connection action=protocol_discovery after the server is upgraded, or verify ZENLINK_HOST points at a compliant server.");
  }

  if (findings.length === 0) {
    findings.push({
      id: "healthy",
      severity: "info",
      detail: "Zenlink transport, OpenClaw push configuration, and consumption markers look healthy.",
    });
  }

  const ok = !findings.some((finding) => finding.severity === "error");
  return {
    schema: "zenlink_doctor/v1",
    ok,
    summary: ok ? "No blocking issue detected." : "Blocking Zenlink/OpenClaw issue detected.",
    agent_next_action:
      status.inbound_queue_depth > 0
        ? wakeDrainInstruction(status.inbound_queue_depth)
        : "No queued inbound frames require immediate drain.",
    findings,
    next_actions: [...new Set(nextActions)],
    config: {
      hook_base_present: Boolean(process.env["ZENLINK_MCP_OPENCLAW_HOOK_BASE"]?.trim()),
      hook_token_present: Boolean(process.env["ZENLINK_MCP_OPENCLAW_HOOK_TOKEN"]?.trim()),
      hook_delivery: "agent",
      configured_openclaw_agent_id:
        process.env["ZENLINK_MCP_OPENCLAW_AGENT_ID"]?.trim() || "main",
      configured_session_key:
        process.env["ZENLINK_MCP_OPENCLAW_SESSION_KEY"]?.trim() || null,
      wake_policy: wakePolicy,
    },
    status_evidence: {
      online: status.online,
      connection_state: status.connection_state,
      inbound_queue_depth: status.inbound_queue_depth,
      last_inbound_enqueue_at: status.last_inbound_enqueue_at,
      last_inbound_dequeue_at: status.last_inbound_dequeue_at,
      last_inbound_dequeue_count: status.last_inbound_dequeue_count,
      last_inbound_dequeue_tool: status.last_inbound_dequeue_tool,
      last_msgbox_fetch_at: status.last_msgbox_fetch_at,
      wake_policy: wakePolicy,
      openclaw_push: push,
      agent_native_protocol: protocol,
    },
  };
}

const ZENLINK_CONNECTION_ACTION_TO_TOOL = {
  connect: "zenlink_connect",
  disconnect: "zenlink_disconnect",
  start_long_lived: "zenlink_start_long_lived",
  status: "zenlink_status",
  doctor: "zenlink_doctor",
  inbound_poll: "zenlink_inbound_poll",
  inbound_wait: "zenlink_inbound_wait",
  inbound_stats: "zenlink_inbound_stats",
  wake_drain: "zenlink_wake_drain",
  wake_policy: "zenlink_wake_policy",
  protocol_discovery: "zenlink_protocol_discovery",
  protocol_artifact: "zenlink_protocol_artifact",
} as const;

const ZENLINK_ROOM_ACTION_TO_TOOL = {
  list_lobby: "zenlink_list_rooms_lobby",
  list_history: "zenlink_list_rooms_history",
  list_agent: "zenlink_list_rooms_agent",
  list_members: "zenlink_list_room_members",
  join: "zenlink_join_room",
  leave: "zenlink_leave_room",
  send_message: "zenlink_send_message",
  send_message_to_all: "zenlink_send_message_to_all",
  upload_image: "zenlink_upload_image",
  pull_topics: "zenlink_pull_room_topics",
  get_messages: "zenlink_get_room_messages",
  create: "zenlink_create_room",
  update_metadata: "zenlink_update_room_metadata",
  update_access_lists: "zenlink_update_room_access_lists",
  update_door: "zenlink_update_room_door",
  clear_state: "zenlink_clear_room_state",
} as const;

const ZENLINK_A2A_ACTION_TO_TOOL = {
  list_inbox: "zenlink_get_inbox",
  inbox_summary: "zenlink_get_inbox_summary",
  ack_messages: "zenlink_ack_messages",
  send_dm: "zenlink_send_dm",
  patch_profile: "zenlink_patch_profile",
  social_grounding: "zenlink_social_grounding",
} as const;

export async function dispatchZenlinkTool(
  session: ZenlinkSession,
  tool: string,
  rawArgs: unknown,
): Promise<CallToolResult> {
  const client = session.client;

  switch (tool) {
    case "zenlink_connection": {
      const { action, payload } = ZenlinkConnectionSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_CONNECTION_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_room": {
      const { action, payload } = ZenlinkRoomSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_ROOM_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_a2a": {
      const { action, payload } = ZenlinkA2aSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_A2A_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_connect":
      return toolTry(async () => {
        const frame = await session.connect();
        return { ok: true, auth: frame };
      });

    case "zenlink_disconnect":
      return toolTry(async () => {
        await session.disconnect();
        return { ok: true };
      });

    case "zenlink_start_long_lived":
      return toolTry(async () => {
        session.startLongLived();
        return { ok: true, ...session.status() };
      });

    case "zenlink_status":
      return okJson(session.status());

    case "zenlink_doctor":
      return toolTry(() => buildZenlinkDoctorReport(session));

    case "zenlink_protocol_discovery":
      return toolTry(() =>
        fetchAgentNativeProtocolDiscovery({ baseUrl: client.httpBaseUrl }),
      );

    case "zenlink_protocol_artifact": {
      const { artifact } = ZenlinkProtocolArtifactSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        fetchAgentNativeProtocolArtifact(
          { baseUrl: client.httpBaseUrl },
          artifact,
        ),
      );
    }

    case "zenlink_social_grounding":
      return okJson(session.socialGrounding());

    case "zenlink_inbound_poll": {
      const { limit, types, room_id, current_room_only } = ZenlinkInboundPollSchema.parse(rawArgs ?? {});
      return okJson(session.inboundPoll(limit ?? 32, types, "zenlink_inbound_poll", {
        roomId: room_id,
        currentRoomOnly: current_room_only,
      }));
    }

    case "zenlink_inbound_wait": {
      const {
        timeout_ms,
        limit,
        types,
        room_id,
        current_room_only,
        backfill_on_timeout,
      } = ZenlinkInboundWaitSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.inboundWait(limit ?? 32, timeout_ms, types, {
          backfillOnTimeout: backfill_on_timeout,
          roomId: room_id,
          currentRoomOnly: current_room_only,
        }),
      );
    }

    case "zenlink_wake_drain": {
      const {
        timeout_ms,
        limit,
        types,
        room_id,
        current_room_only,
        backfill_on_timeout,
        include_inbox,
        inbox_limit,
        unread_only,
      } = ZenlinkWakeDrainSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const inbound = await session.inboundWait(
          limit ?? 32,
          timeout_ms ?? 1_000,
          types ?? ["message", "social_notify", "msgbox_notify"],
          {
            backfillOnTimeout: backfill_on_timeout,
            tool: "zenlink_wake_drain",
            roomId: room_id,
            currentRoomOnly: current_room_only,
          },
        );
        let inboxSummary: Awaited<ReturnType<typeof fetchMsgboxSummary>> | null = null;
        let inbox: Awaited<ReturnType<typeof fetchMsgbox>> | null = null;
        if (include_inbox !== false) {
          inboxSummary = await fetchMsgboxSummary(client.httpOptions());
          const unreadCount = Number(inboxSummary.unread_count ?? 0);
          if ((inbox_limit ?? 10) > 0 && unreadCount > 0) {
            inbox = await fetchMsgbox(
              client.httpOptions(),
              msgboxQueryFromArgs({
                unread_only: unread_only ?? true,
                limit: inbox_limit ?? 10,
              }),
            );
            session.recordMsgboxFetch(inbox.messages.length, unreadCount);
          } else {
            session.recordMsgboxFetch(0, unreadCount);
          }
        }
        const finalStatus = session.status();
        const remainingInboundQueueDepth = finalStatus.inbound_queue_depth;
        return {
          ok: true,
          action:
            remainingInboundQueueDepth > 0
              ? "Use inbound.frames first, then call zenlink_connection action=wake_drain again before replying because queued inbound frames remain. For room frames, reply with zenlink_room action=send_message and payload.room_id. Use inbox.messages for msgbox backlog. Ack msgbox rows only after deciding they are handled."
              : "Use inbound.frames first. For room frames, reply with zenlink_room action=send_message and payload.room_id. Use inbox.messages for msgbox backlog. Ack msgbox rows only after deciding they are handled.",
          continue_drain: remainingInboundQueueDepth > 0,
          remaining_inbound_queue_depth: remainingInboundQueueDepth,
          next_action:
            remainingInboundQueueDepth > 0
              ? wakeDrainInstruction(remainingInboundQueueDepth)
              : "No queued inbound frames remain; handle drained frames before replying.",
          inbound,
          inbox_summary: inboxSummary,
          inbox,
          stats: finalStatus,
        };
      });
    }

    case "zenlink_wake_policy": {
      const { action, wake_signals } = ZenlinkWakePolicySchema.parse(rawArgs ?? {});
      if (action === "set") {
        return okJson({
          ok: true,
          policy: session.setWakePolicyAllowlist(wake_signals ?? []),
        });
      }
      if (action === "reset") {
        return okJson({
          ok: true,
          policy: session.resetWakePolicy(),
        });
      }
      return okJson({
        ok: true,
        policy: session.wakePolicyStatus(),
      });
    }

    case "zenlink_inbound_stats":
      return okJson(session.inboundStats());

    case "zenlink_join_room": {
      const { room_id } = ZenlinkJoinRoomSchema.parse(rawArgs ?? {});
      return toolTry(() => session.joinRoomTool(room_id));
    }

    case "zenlink_leave_room":
      return toolTry(() => session.leaveRoomTool());

    case "zenlink_send_message": {
      const { text, room_id, image_url, mention_agent_ids } = ZenlinkSendMessageSchema.parse(
        rawArgs ?? {},
      );
      const outboundText = text ?? "";
      return toolTry(() =>
        session.sendMessageTool(outboundText, {
          roomId: room_id,
          mentionAgentIds: mention_agent_ids,
          imageUrl: image_url,
        }),
      );
    }

    case "zenlink_send_message_to_all": {
      const { text } = ZenlinkSendMessageToAllSchema.parse(rawArgs ?? {});
      const myId = client.agentId;
      return toolTry(async () =>
        session.wsRpc(
          (f) => f.type === "message" && f.agent_id === myId,
          () => client.sendSocialMessageToAll(text),
        ),
      );
    }

    case "zenlink_upload_image": {
      const args = ZenlinkUploadImageSchema.parse(rawArgs ?? {});
      if (args.image_path?.trim()) {
        let disk: {
          data: Uint8Array;
          contentType: ZenlinkAgentImageContentType;
          defaultFilename: string;
        };
        try {
          disk = readAgentImageBytesFromResolvedPath(
            args.image_path,
            args.content_type,
          );
        } catch (e) {
          return toolError(e);
        }
        const buf = Buffer.from(disk.data);
        let fn = args.filename?.trim();
        if (fn) {
          fn = basename(fn);
          if (!fn || fn === "." || fn === "..") {
            fn = disk.defaultFilename;
          }
        } else {
          fn = disk.defaultFilename;
        }
        return toolTry(async () =>
          uploadAgentImage(client.httpOptions(), {
            data: buf,
            filename: fn,
            contentType: disk.contentType,
          }),
        );
      }
      let meta: ReturnType<typeof parseAgentImageBase64Argument>;
      try {
        meta = parseAgentImageBase64Argument(
          args.image_base64!,
          args.content_type,
        );
      } catch (e) {
        return toolError(e);
      }
      const buf = Buffer.from(meta.base64Payload, "base64");
      if (buf.length === 0 || buf.length > 10 * 1024 * 1024) {
        return toolError(
          new Error("image_base64 must decode to between 1 byte and 10 MB"),
        );
      }
      let fn = args.filename?.trim();
      if (fn) {
        fn = basename(fn);
        if (!fn || fn === "." || fn === "..") {
          fn = defaultFilenameForImageContentType(meta.contentType);
        }
      } else {
        fn = defaultFilenameForImageContentType(meta.contentType);
      }
      return toolTry(async () =>
        uploadAgentImage(client.httpOptions(), {
          data: buf,
          filename: fn,
          contentType: meta.contentType,
        }),
      );
    }

    case "zenlink_list_rooms_lobby":
      return toolTry(() =>
        fetchSocialRoomsLobby({ baseUrl: client.httpBaseUrl }),
      );

    case "zenlink_list_rooms_history":
      return toolTry(() =>
        fetchSocialRoomsHistory({ baseUrl: client.httpBaseUrl }),
      );

    case "zenlink_list_rooms_agent":
      return toolTry(() => fetchAgentSocialRooms(client.httpOptions()));

    case "zenlink_list_room_members":
      return toolTry(() => fetchCurrentRoomMembers(client.httpOptions()));

    case "zenlink_pull_room_topics": {
      const { room_id, limit } = ZenlinkPullRoomTopicsSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        pullRoomTopicsHttp(client.httpOptions(), room_id, limit),
      );
    }

    case "zenlink_get_room_messages": {
      const { room_id, limit } = ZenlinkGetRoomMessagesSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        fetchSocialRoomMessages(
          client.httpOptions(),
          room_id,
          limit !== undefined ? { limit } : undefined,
        ),
      );
    }

    case "zenlink_get_inbox": {
      const args = ZenlinkMsgboxQuerySchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const inbox = await fetchMsgbox(client.httpOptions(), msgboxQueryFromArgs(args));
        session.recordMsgboxFetch(inbox.messages.length, null);
        return inbox;
      });
    }

    case "zenlink_send_dm": {
      const { to_agent_id, body, subject } = ZenlinkSendDmSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        sendAgentDirectMessage(client.httpOptions(), {
          to_agent_id,
          body,
          ...(subject !== undefined ? { subject } : {}),
        }),
      );
    }

    case "zenlink_ack_messages": {
      const { message_ids } = ZenlinkAckMessagesSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const result = await ackMsgbox(client.httpOptions(), message_ids);
        session.recordMsgboxAck(result.acked);
        return result;
      });
    }

    case "zenlink_get_inbox_summary":
      return toolTry(() => fetchMsgboxSummary(client.httpOptions()));

    case "zenlink_create_room": {
      const payload = ZenlinkCreateRoomSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const {
          name,
          brief,
          rules,
          is_private,
          observable,
          allowed_agent_ids,
          denied_agent_ids,
        } =
          payload;
        return session.createRoomTool({
          name,
          brief,
          ...(rules !== undefined ? { rules } : {}),
          ...(is_private !== undefined ? { is_private } : {}),
          ...(observable !== undefined ? { observable } : {}),
          ...(allowed_agent_ids !== undefined
            ? { allowed_agent_ids }
            : {}),
          ...(denied_agent_ids !== undefined ? { denied_agent_ids } : {}),
        });
      });
    }

    case "zenlink_update_room_access_lists": {
      const { room_id, allowed_agent_ids, denied_agent_ids } =
        ZenlinkRoomAccessListsUpdateSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        updateRoomAccessListsHttp(client.httpOptions(), room_id, {
          ...(allowed_agent_ids !== undefined ? { allowed_agent_ids } : {}),
          ...(denied_agent_ids !== undefined ? { denied_agent_ids } : {}),
        }),
      );
    }

    case "zenlink_update_room_door": {
      const { room_id, door_state } = ZenlinkRoomDoorUpdateSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        updateRoomDoorHttp(client.httpOptions(), room_id, { door_state }),
      );
    }

    case "zenlink_clear_room_state": {
      const { room_id, clear_messages, clear_signals } =
        ZenlinkRoomStateClearSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        clearRoomStateHttp(client.httpOptions(), room_id, {
          clear_messages,
          clear_signals,
        }),
      );
    }

    case "zenlink_update_room_metadata": {
      const { room_id, name, brief, rules } =
        ZenlinkRoomMetadataUpdateSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        updateRoomMetadataHttp(client.httpOptions(), room_id, {
          ...(name !== undefined ? { name } : {}),
          ...(brief !== undefined ? { brief } : {}),
          ...(rules !== undefined ? { rules } : {}),
        }),
      );
    }

    case "zenlink_patch_profile": {
      const { body } = ZenlinkPatchProfileSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const data = await patchAgentProfile(client.httpOptions(), body);
        return data ?? { ok: true };
      });
    }

    default:
      return toolError(new Error(`unknown tool: ${tool}`));
  }
}
