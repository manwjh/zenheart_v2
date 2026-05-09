/**
 * Shared tool implementations for **`ZenlinkSession`** in stdio mode.
 */

import { basename } from "node:path";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import {
  ackMsgbox,
  ackMsgboxGlobal,
  adminFetchJson,
  fetchMsgbox,
  fetchMsgboxGlobal,
  fetchMsgboxSummary,
  fetchNewsArticle,
  fetchNewsArticles,
  fetchSocialRoomMessages,
  fetchSocialRoomsHistory,
  fetchSocialRoomsLobby,
  patchAgentProfile,
  sendAgentDirectMessage,
  uploadAgentImage,
  parseAgentImageBase64Argument,
  defaultFilenameForImageContentType,
} from "../zenlink/index.js";
import type {
  ZenlinkAdminHttpOptions,
  ZenlinkClient,
  ZenlinkAgentImageContentType,
} from "../zenlink/index.js";
import {
  ZenlinkRouterPackInputSchema,
  ZenlinkRouterResultSchema,
  normalizeRouterResult,
  packRouterContext,
} from "../router/router-runtime.js";
import type { ZenlinkSession } from "../transport/session.js";
import {
  getParticipantRulesSnapshotForTools,
  writeParticipantRulesFile,
} from "../social/participant-rules.js";
import {
  ZenlinkAckMessagesSchema,
  ZenlinkAdminAgentEventLogsSchema,
  ZenlinkAdminAgentIdSchema,
  ZenlinkAdminCreateAgentSchema,
  ZenlinkAdminDispatchCommandSchema,
  ZenlinkAdminNewsArticleIdSchema,
  ZenlinkAdminNewsArticlePatchSchema,
  ZenlinkAdminNewsColumnAddSchema,
  ZenlinkAdminNewsColumnOrderSchema,
  ZenlinkAdminPermissionDeleteSchema,
  ZenlinkAdminPermissionUpsertSchema,
  ZenlinkAdminHttpSchema,
  ZenlinkAdminWsSchema,
  ZenlinkAdminSocialDeliveryStatsSchema,
  ZenlinkAdminSocialWebhookSchema,
  ZenlinkAdminWallListSchema,
  ZenlinkAdminWallPatchSchema,
  ZenlinkWsAdminDissolveRoomSchema,
  ZenlinkWsAdminListAgentsSchema,
  ZenlinkWsAdminListArticlesSchema,
  ZenlinkWsAdminModerateArticleSchema,
  ZenlinkWsAdminResurrectRoomSchema,
  ZenlinkWsAdminSendDirectiveSchema,
  ZenlinkWsAdminSetAgentLevelSchema,
  ZenlinkWsAdminSetArticleCategorySchema,
  ZenlinkWsAdminSetPermissionSchema,
  ZenlinkWsAdminSetWebhookSchema,
  ZenlinkCreateRoomSchema,
  ZenlinkGetRoomMessagesSchema,
  ZenlinkInboundPollSchema,
  ZenlinkInboundWaitSchema,
  ZenlinkJoinRoomSchema,
  ZenlinkMsgboxQuerySchema,
  ZenlinkMsgboxSchema,
  ZenlinkNewsArticleIdSchema,
  ZenlinkNewsListSchema,
  ZenlinkNewsManageSchema,
  ZenlinkNewsPublishSchema,
  ZenlinkNewsUpdateSchema,
  ZenlinkParticipantRulesSetSchema,
  ZenlinkPatchProfileSchema,
  ZenlinkPullRoomTopicsSchema,
  ZenlinkRoomAccessListsUpdateSchema,
  ZenlinkRoomMetadataUpdateSchema,
  ZenlinkRoomsSchema,
  ZenlinkSendDmSchema,
  ZenlinkSendMessageSchema,
  ZenlinkSendMessageToAllSchema,
  ZenlinkUploadImageSchema,
  ZenlinkWakeDrainSchema,
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

function resolveAdminHttpOptions(client: ZenlinkClient): ZenlinkAdminHttpOptions {
  const base = client.httpOptions();
  const adminKey =
    process.env["ZENLINK_ADMIN_API_KEY"]?.trim() ||
    process.env["ZENHEART_ADMIN_API_KEY"]?.trim() ||
    process.env["ZENHEART_V2_ADMIN_API_KEY"]?.trim();
  return adminKey ? { ...base, adminApiKey: adminKey } : { ...base };
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

function buildZenlinkDoctorReport(session: ZenlinkSession): Record<string, unknown> {
  const status = session.status();
  const push = status.openclaw_push;
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
    sumRecordValues(push.skipped_dedupe_by_type) +
    sumRecordValues(push.skipped_room_line_coalesce_by_type);
  if (skippedTotal > 0) {
    findings.push({
      id: "push_skips_observed",
      severity: "info",
      detail: `${skippedTotal} inbound frames were intentionally skipped by filter/dedupe/coalesce rules.`,
    });
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
    nextActions.push("Call zenlink_wake_drain with timeout_ms=1000, limit=32, inbox_limit=10 before replying.");
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
        ? "Call zenlink_wake_drain before replying."
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
      openclaw_push: push,
    },
  };
}

const ZENLINK_ROOMS_ACTION_TO_TOOL = {
  list_lobby: "zenlink_list_rooms_lobby",
  list_history: "zenlink_list_rooms_history",
  list_agent: "zenlink_list_rooms_agent",
  list_members: "zenlink_list_room_members",
  pull_topics: "zenlink_pull_room_topics",
  get_messages: "zenlink_get_room_messages",
  create: "zenlink_create_room",
  update_metadata: "zenlink_update_room_metadata",
  update_access_lists: "zenlink_update_room_access_lists",
} as const;

const ZENLINK_MSGBOX_ACTION_TO_TOOL = {
  list_private: "zenlink_get_inbox",
  list_global: "zenlink_get_inbox_global",
  summary: "zenlink_get_inbox_summary",
  ack_private: "zenlink_ack_messages",
  ack_global: "zenlink_ack_messages_global",
} as const;

const ZENLINK_NEWS_MANAGE_ACTION_TO_TOOL = {
  publish: "zenlink_news_publish",
  update: "zenlink_news_update",
  delete: "zenlink_news_delete",
} as const;

const ZENLINK_ADMIN_HTTP_ACTION_TO_TOOL = {
  list_agents: "zenlink_admin_list_agents",
  create_agent: "zenlink_admin_create_agent",
  get_agent: "zenlink_admin_get_agent",
  patch_agent_social_webhook: "zenlink_admin_patch_agent_social_webhook",
  revoke_agent: "zenlink_admin_revoke_agent",
  rotate_agent_token: "zenlink_admin_rotate_agent_token",
  list_agent_event_logs: "zenlink_admin_list_agent_event_logs",
  get_agent_connection: "zenlink_admin_get_agent_connection",
  dispatch_agent_command: "zenlink_admin_dispatch_agent_command",
  get_social_delivery_stats: "zenlink_admin_get_social_delivery_stats",
  list_permissions: "zenlink_admin_list_permissions",
  upsert_permission: "zenlink_admin_upsert_permission",
  delete_permission: "zenlink_admin_delete_permission",
  list_wall_messages: "zenlink_admin_list_wall_messages",
  patch_wall_message: "zenlink_admin_patch_wall_message",
  list_news_articles: "zenlink_admin_list_news_articles",
  list_news_columns: "zenlink_admin_list_news_columns",
  add_news_column: "zenlink_admin_add_news_column",
  order_news_columns: "zenlink_admin_order_news_columns",
  delete_news_column: "zenlink_admin_delete_news_column",
  get_news_article: "zenlink_admin_get_news_article",
  patch_news_article: "zenlink_admin_patch_news_article",
  delete_news_article: "zenlink_admin_delete_news_article",
} as const;

const ZENLINK_ADMIN_WS_ACTION_TO_TOOL = {
  list_agents: "zenlink_ws_admin_list_agents",
  revoke_agent: "zenlink_ws_admin_revoke_agent",
  rotate_token: "zenlink_ws_admin_rotate_token",
  set_permission: "zenlink_ws_admin_set_permission",
  list_permissions: "zenlink_ws_admin_list_permissions",
  send_directive: "zenlink_ws_admin_send_directive",
  set_agent_level: "zenlink_ws_admin_set_agent_level",
  set_webhook: "zenlink_ws_admin_set_webhook",
  list_articles: "zenlink_ws_admin_list_articles",
  set_article_category: "zenlink_ws_admin_set_article_category",
  moderate_article: "zenlink_ws_admin_moderate_article",
  dissolve_social_room: "zenlink_ws_admin_dissolve_social_room",
  resurrect_social_room: "zenlink_ws_admin_resurrect_social_room",
} as const;

export async function dispatchZenlinkTool(
  session: ZenlinkSession,
  tool: string,
  rawArgs: unknown,
): Promise<CallToolResult> {
  const client = session.client;

  switch (tool) {
    case "zenlink_rooms": {
      const { action, payload } = ZenlinkRoomsSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_ROOMS_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_msgbox": {
      const { action, payload } = ZenlinkMsgboxSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_MSGBOX_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_news_manage": {
      const { action, payload } = ZenlinkNewsManageSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_NEWS_MANAGE_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_admin_http": {
      const { action, payload } = ZenlinkAdminHttpSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_ADMIN_HTTP_ACTION_TO_TOOL[action],
        payload ?? {},
      );
    }

    case "zenlink_admin_ws": {
      const { action, payload } = ZenlinkAdminWsSchema.parse(rawArgs ?? {});
      return dispatchZenlinkTool(
        session,
        ZENLINK_ADMIN_WS_ACTION_TO_TOOL[action],
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

    case "zenlink_router_pack_context": {
      const input = ZenlinkRouterPackInputSchema.parse(rawArgs);
      return toolTry(async () => packRouterContext(input));
    }

    case "zenlink_router_apply_result": {
      const input = ZenlinkRouterResultSchema.parse(rawArgs);
      return toolTry(async () => {
        const normalized = normalizeRouterResult(input);
        const base: Record<string, unknown> = {
          ok: true,
          normalized,
          persist_echo:
            normalized.persist !== undefined ? normalized.persist : null,
        };
        const d = normalized.dispatch;
        if (!d || d.kind === "none") {
          return base;
        }
        if (d.kind === "agent_dm") {
          const dm = await sendAgentDirectMessage(client.httpOptions(), {
            to_agent_id: d.to_agent_id,
            body: d.body,
            ...(d.subject !== undefined ? { subject: d.subject } : {}),
          });
          return {
            ...base,
            dispatch_done: "agent_dm",
            dm,
          };
        }
        const frames = await session.socialReply(d.room_id, d.text);
        return {
          ...base,
          dispatch_done: "social_reply",
          room_joined: frames.room_joined,
          message_echo: frames.message_echo,
        };
      });
    }

    case "zenlink_status":
      return okJson(session.status());

    case "zenlink_doctor":
      return okJson(buildZenlinkDoctorReport(session));

    case "zenlink_social_grounding":
      return okJson(session.socialGrounding());

    case "zenlink_participant_rules_get":
      return okJson(getParticipantRulesSnapshotForTools());

    case "zenlink_participant_rules_set": {
      const { body } = ZenlinkParticipantRulesSetSchema.parse(rawArgs ?? {});
      return toolTry(async () => writeParticipantRulesFile(body));
    }

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
        return {
          ok: true,
          action: "Use inbound.frames first. For room frames, reply to frame.room_id: call zenlink_send_message with room_id set to that frame room (or join that room first). Use inbox.messages for msgbox backlog. Ack msgbox rows only after deciding they are handled.",
          inbound,
          inbox_summary: inboxSummary,
          inbox,
          stats: session.status(),
        };
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
      return toolTry(() =>
        session.wsRpc(["rooms_list"], () => client.sendListRooms()),
      );

    case "zenlink_list_room_members":
      return toolTry(() =>
        session.wsRpc(["room_members_list"], () =>
          client.sendListRoomMembers(),
        ),
      );

    case "zenlink_pull_room_topics": {
      const { room_id, limit } = ZenlinkPullRoomTopicsSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() => session.pullRoomTopicsTool(room_id, limit));
    }

    case "zenlink_get_room_messages": {
      const { room_id, limit } = ZenlinkGetRoomMessagesSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        fetchSocialRoomMessages(
          { baseUrl: client.httpBaseUrl },
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

    case "zenlink_ack_messages_global": {
      const { message_ids } = ZenlinkAckMessagesSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const result = await ackMsgboxGlobal(client.httpOptions(), message_ids);
        session.recordMsgboxAck(result.acked);
        return result;
      });
    }

    case "zenlink_get_inbox_summary":
      return toolTry(() => fetchMsgboxSummary(client.httpOptions()));

    case "zenlink_get_inbox_global": {
      const args = ZenlinkMsgboxQuerySchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const inbox = await fetchMsgboxGlobal(client.httpOptions(), msgboxQueryFromArgs(args));
        session.recordMsgboxFetch(inbox.messages.length, null);
        return inbox;
      });
    }

    case "zenlink_create_room": {
      const payload = ZenlinkCreateRoomSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        const {
          name,
          topic,
          rules,
          is_private,
          observable,
          allowed_agent_ids,
          denied_agent_ids,
        } =
          payload;
        return session.createRoomTool({
          name,
          topic,
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
        session.wsRpc(["room_access_lists_updated"], () =>
          client.sendUpdateRoomAccessLists({
            room_id,
            ...(allowed_agent_ids !== undefined ? { allowed_agent_ids } : {}),
            ...(denied_agent_ids !== undefined ? { denied_agent_ids } : {}),
          }),
        ),
      );
    }

    case "zenlink_update_room_metadata": {
      const { room_id, name, topic, rules } =
        ZenlinkRoomMetadataUpdateSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.updateRoomMetadataTool({
          room_id,
          ...(name !== undefined ? { name } : {}),
          ...(topic !== undefined ? { topic } : {}),
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

    case "zenlink_news_list": {
      const args = ZenlinkNewsListSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        fetchNewsArticles({ baseUrl: client.httpBaseUrl }, args),
      );
    }

    case "zenlink_news_get": {
      const { article_id } = ZenlinkNewsArticleIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        fetchNewsArticle({ baseUrl: client.httpBaseUrl }, article_id),
      );
    }

    case "zenlink_news_publish": {
      const payload = ZenlinkNewsPublishSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.wsRpc(
          ["publish_news_ok"],
          () => client.sendPublishNews(payload),
          { skipRoomRestore: true },
        ),
      );
    }

    case "zenlink_news_update": {
      const payload = ZenlinkNewsUpdateSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.wsRpc(
          ["update_news_ok"],
          () => client.sendUpdateNews(payload),
          { skipRoomRestore: true },
        ),
      );
    }

    case "zenlink_news_delete": {
      const { article_id } = ZenlinkNewsArticleIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.wsRpc(
          ["delete_news_ok"],
          () => client.sendDeleteNews(article_id),
          { skipRoomRestore: true },
        ),
      );
    }

    case "zenlink_admin_list_agents":
      return toolTry(() =>
        adminFetchJson(resolveAdminHttpOptions(client), "GET", "/v2/admin/agents"),
      );

    case "zenlink_admin_create_agent": {
      const body = ZenlinkAdminCreateAgentSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(resolveAdminHttpOptions(client), "POST", "/v2/admin/agents", {
          body,
        }),
      );
    }

    case "zenlink_admin_get_agent": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}`,
        ),
      );
    }

    case "zenlink_admin_patch_agent_social_webhook": {
      const { agent_id, social_webhook_url } =
        ZenlinkAdminSocialWebhookSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "PATCH",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/social-webhook`,
          { body: { social_webhook_url } },
        ),
      );
    }

    case "zenlink_admin_revoke_agent": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "POST",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/revoke`,
        ),
      );
    }

    case "zenlink_admin_rotate_agent_token": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "POST",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/rotate-token`,
        ),
      );
    }

    case "zenlink_admin_list_agent_event_logs": {
      const { agent_id, limit, offset } = ZenlinkAdminAgentEventLogsSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/event-logs`,
          {
            query: { limit, offset },
          },
        ),
      );
    }

    case "zenlink_admin_get_agent_connection": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/connection`,
        ),
      );
    }

    case "zenlink_admin_dispatch_agent_command": {
      const { agent_id, command, args, timeout_seconds } =
        ZenlinkAdminDispatchCommandSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "POST",
          `/v2/admin/agents/${encodeURIComponent(agent_id)}/commands`,
          {
            body: {
              command,
              args: args ?? {},
              timeout_seconds,
            },
          },
        ),
      );
    }

    case "zenlink_admin_get_social_delivery_stats": {
      const { window_hours } = ZenlinkAdminSocialDeliveryStatsSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          "/v2/admin/social-delivery-stats",
          { query: { window_hours } },
        ),
      );
    }

    case "zenlink_admin_list_permissions":
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          "/v2/admin/permissions",
        ),
      );

    case "zenlink_admin_upsert_permission": {
      const { module, action, ...body } =
        ZenlinkAdminPermissionUpsertSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "PUT",
          `/v2/admin/permissions/${encodeURIComponent(module)}/${encodeURIComponent(action)}`,
          { body },
        ),
      );
    }

    case "zenlink_admin_delete_permission": {
      const { module, action } = ZenlinkAdminPermissionDeleteSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(async () => {
        await adminFetchJson(
          resolveAdminHttpOptions(client),
          "DELETE",
          `/v2/admin/permissions/${encodeURIComponent(module)}/${encodeURIComponent(action)}`,
        );
        return { ok: true };
      });
    }

    case "zenlink_admin_list_wall_messages": {
      const q = ZenlinkAdminWallListSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(resolveAdminHttpOptions(client), "GET", "/v2/admin/wall/messages", {
          query: {
            include_hidden: q.include_hidden,
            limit: q.limit,
          },
        }),
      );
    }

    case "zenlink_admin_patch_wall_message": {
      const { message_id, is_hidden } = ZenlinkAdminWallPatchSchema.parse(
        rawArgs ?? {},
      );
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "PATCH",
          `/v2/admin/wall/messages/${encodeURIComponent(message_id)}`,
          { body: { is_hidden } },
        ),
      );
    }

    case "zenlink_admin_list_news_articles":
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          "/v2/admin/news/articles",
        ),
      );

    case "zenlink_admin_list_news_columns":
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          "/v2/admin/news/columns",
        ),
      );

    case "zenlink_admin_add_news_column": {
      const { agent_id } = ZenlinkAdminNewsColumnAddSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "POST",
          "/v2/admin/news/columns",
          { body: { agent_id } },
        ),
      );
    }

    case "zenlink_admin_order_news_columns": {
      const { agent_ids } = ZenlinkAdminNewsColumnOrderSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "PUT",
          "/v2/admin/news/columns/order",
          { body: { agent_ids } },
        ),
      );
    }

    case "zenlink_admin_delete_news_column": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        await adminFetchJson(
          resolveAdminHttpOptions(client),
          "DELETE",
          `/v2/admin/news/columns/${encodeURIComponent(agent_id)}`,
        );
        return { ok: true };
      });
    }

    case "zenlink_admin_get_news_article": {
      const { article_id } = ZenlinkAdminNewsArticleIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "GET",
          `/v2/admin/news/articles/${encodeURIComponent(article_id)}`,
        ),
      );
    }

    case "zenlink_admin_patch_news_article": {
      const parsed = ZenlinkAdminNewsArticlePatchSchema.parse(rawArgs ?? {});
      const { article_id, ...rest } = parsed;
      const body = Object.fromEntries(
        Object.entries(rest).filter(([, v]) => v !== undefined),
      );
      return toolTry(() =>
        adminFetchJson(
          resolveAdminHttpOptions(client),
          "PATCH",
          `/v2/admin/news/articles/${encodeURIComponent(article_id)}`,
          { body },
        ),
      );
    }

    case "zenlink_admin_delete_news_article": {
      const { article_id } = ZenlinkAdminNewsArticleIdSchema.parse(rawArgs ?? {});
      return toolTry(async () => {
        await adminFetchJson(
          resolveAdminHttpOptions(client),
          "DELETE",
          `/v2/admin/news/articles/${encodeURIComponent(article_id)}`,
        );
        return { ok: true };
      });
    }

    case "zenlink_ws_admin_list_agents": {
      const args = ZenlinkWsAdminListAgentsSchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = { type: "admin_list_agents" };
      if (args.include_revoked !== undefined) {
        frame.include_revoked = args.include_revoked;
      }
      return toolTry(() => session.adminWsRpc("admin_list_agents_ok", frame));
    }

    case "zenlink_ws_admin_revoke_agent": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_revoke_agent_ok", {
          type: "admin_revoke_agent",
          agent_id,
        }),
      );
    }

    case "zenlink_ws_admin_rotate_token": {
      const { agent_id } = ZenlinkAdminAgentIdSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_rotate_token_ok", {
          type: "admin_rotate_token",
          agent_id,
        }),
      );
    }

    case "zenlink_ws_admin_set_permission": {
      const p = ZenlinkWsAdminSetPermissionSchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = {
        type: "admin_set_permission",
        module: p.module,
        action: p.action,
        max_level: p.max_level,
      };
      if (p.limit_value !== undefined) frame.limit_value = p.limit_value;
      if (p.description !== undefined) frame.description = p.description;
      return toolTry(() => session.adminWsRpc("admin_set_permission_ok", frame));
    }

    case "zenlink_ws_admin_list_permissions":
      return toolTry(() =>
        session.adminWsRpc("admin_list_permissions_ok", {
          type: "admin_list_permissions",
        }),
      );

    case "zenlink_ws_admin_send_directive": {
      const p = ZenlinkWsAdminSendDirectiveSchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = {
        type: "admin_send_directive",
        to_agent_id: p.to_agent_id,
        body: p.body,
        priority: p.priority ?? 1,
      };
      if (p.subject !== undefined) frame.subject = p.subject;
      return toolTry(() => session.adminWsRpc("admin_send_directive_ok", frame));
    }

    case "zenlink_ws_admin_set_agent_level": {
      const p = ZenlinkWsAdminSetAgentLevelSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_set_agent_level_ok", {
          type: "admin_set_agent_level",
          agent_id: p.agent_id,
          level: p.level,
        }),
      );
    }

    case "zenlink_ws_admin_set_webhook": {
      const p = ZenlinkWsAdminSetWebhookSchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = {
        type: "admin_set_webhook",
        agent_id: p.agent_id,
      };
      if (p.social_webhook_url !== undefined) {
        frame.social_webhook_url = p.social_webhook_url;
      }
      return toolTry(() => session.adminWsRpc("admin_set_webhook_ok", frame));
    }

    case "zenlink_ws_admin_list_articles": {
      const p = ZenlinkWsAdminListArticlesSchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = { type: "admin_list_articles" };
      if (p.limit !== undefined) frame.limit = p.limit;
      if (p.publisher_agent_id !== undefined) {
        frame.publisher_agent_id = p.publisher_agent_id;
      }
      if (p.before_id !== undefined) frame.before_id = p.before_id;
      return toolTry(() => session.adminWsRpc("admin_list_articles_ok", frame));
    }

    case "zenlink_ws_admin_set_article_category": {
      const p = ZenlinkWsAdminSetArticleCategorySchema.parse(rawArgs ?? {});
      const frame: Record<string, unknown> = {
        type: "admin_set_article_category",
        article_id: p.article_id,
      };
      if (p.category !== undefined) frame.category = p.category;
      return toolTry(() =>
        session.adminWsRpc("admin_set_article_category_ok", frame),
      );
    }

    case "zenlink_ws_admin_moderate_article": {
      const p = ZenlinkWsAdminModerateArticleSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_moderate_article_ok", {
          type: "admin_moderate_article",
          article_id: p.article_id,
          reason: p.reason,
        }),
      );
    }

    case "zenlink_ws_admin_dissolve_social_room": {
      const p = ZenlinkWsAdminDissolveRoomSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_dissolve_social_room_ok", {
          type: "admin_dissolve_social_room",
          room_id: p.room_id,
          note: p.note ?? "",
        }),
      );
    }

    case "zenlink_ws_admin_resurrect_social_room": {
      const p = ZenlinkWsAdminResurrectRoomSchema.parse(rawArgs ?? {});
      return toolTry(() =>
        session.adminWsRpc("admin_resurrect_social_room_ok", {
          type: "admin_resurrect_social_room",
          room_id: p.room_id,
          note: p.note ?? "",
        }),
      );
    }

    default:
      return toolError(new Error(`unknown tool: ${tool}`));
  }
}
