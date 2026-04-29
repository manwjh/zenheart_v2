/**
 * Shared tool implementations for **`ZenlinkSession`** (local MCP or **`--daemon`** IPC).
 */

import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import * as z from "zod/v4";
import {
  ackMsgbox,
  fetchMsgbox,
  fetchMsgboxGlobal,
  fetchMsgboxSummary,
  fetchSocialRoomMessages,
  fetchSocialRoomsHistory,
  fetchSocialRoomsLobby,
  patchAgentProfile,
  sendAgentDirectMessage,
} from "zenlink";
import {
  ZenlinkRouterPackInputSchema,
  ZenlinkRouterResultSchema,
  normalizeRouterResult,
  packRouterContext,
} from "./router-runtime.js";
import type { ZenlinkSession } from "./session.js";

export function okJson(data: unknown): CallToolResult {
  return {
    content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
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

export async function dispatchZenlinkTool(
  session: ZenlinkSession,
  tool: string,
  rawArgs: unknown,
): Promise<CallToolResult> {
  const client = session.client;

  switch (tool) {
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

    case "zenlink_inbound_poll": {
      const schema = z.object({
        limit: z.number().int().positive().max(500).optional(),
      });
      const { limit } = schema.parse(rawArgs ?? {});
      return okJson(session.inboundPoll(limit ?? 32));
    }

    case "zenlink_inbound_stats":
      return okJson(session.inboundStats());

    case "zenlink_join_room": {
      const { room_id } = z
        .object({ room_id: z.string() })
        .parse(rawArgs ?? {});
      return toolTry(() => session.joinRoomTool(room_id));
    }

    case "zenlink_leave_room":
      return toolTry(() => session.leaveRoomTool());

    case "zenlink_send_message": {
      const { text, mention_agent_ids } = z
        .object({
          text: z.string(),
          mention_agent_ids: z.array(z.string()).optional(),
        })
        .parse(rawArgs ?? {});
      const myId = client.agentId;
      return toolTry(async () =>
        session.wsRpc(
          (f) =>
            f.type === "message" &&
            f.agent_id === myId &&
            f.text === text,
          () =>
            client.sendSocialMessage(text, {
              mentionAgentIds: mention_agent_ids,
            }),
        ),
      );
    }

    case "zenlink_send_message_to_all": {
      const { text } = z.object({ text: z.string() }).parse(rawArgs ?? {});
      const myId = client.agentId;
      const trimmed = text.trim();
      const outboundText = trimmed ? `${trimmed} @all` : "@all";
      return toolTry(async () =>
        session.wsRpc(
          (f) =>
            f.type === "message" &&
            f.agent_id === myId &&
            f.text === outboundText,
          () => client.sendSocialMessageToAll(text),
        ),
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
      const { room_id, limit } = z
        .object({
          room_id: z.string(),
          limit: z.number().int().positive().max(500).optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() => session.pullRoomTopicsTool(room_id, limit));
    }

    case "zenlink_get_room_messages": {
      const { room_id, limit } = z
        .object({
          room_id: z.string(),
          limit: z.number().int().positive().optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() =>
        fetchSocialRoomMessages(
          { baseUrl: client.httpBaseUrl },
          room_id,
          limit !== undefined ? { limit } : undefined,
        ),
      );
    }

    case "zenlink_get_inbox": {
      const args = z
        .object({
          unread_only: z.boolean().optional(),
          limit: z.number().int().positive().optional(),
          before_id: z.string().optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() =>
        fetchMsgbox(client.httpOptions(), msgboxQueryFromArgs(args)),
      );
    }

    case "zenlink_send_dm": {
      const { to_agent_id, body, subject } = z
        .object({
          to_agent_id: z.string().min(1).max(80),
          body: z.string().min(1).max(4000),
          subject: z.string().max(120).optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() =>
        sendAgentDirectMessage(client.httpOptions(), {
          to_agent_id,
          body,
          ...(subject !== undefined ? { subject } : {}),
        }),
      );
    }

    case "zenlink_ack_messages": {
      const { message_ids } = z
        .object({ message_ids: z.array(z.string()).min(1) })
        .parse(rawArgs ?? {});
      return toolTry(() => ackMsgbox(client.httpOptions(), message_ids));
    }

    case "zenlink_get_inbox_summary":
      return toolTry(() => fetchMsgboxSummary(client.httpOptions()));

    case "zenlink_get_inbox_global": {
      const args = z
        .object({
          unread_only: z.boolean().optional(),
          limit: z.number().int().positive().optional(),
          before_id: z.string().optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() =>
        fetchMsgboxGlobal(client.httpOptions(), msgboxQueryFromArgs(args)),
      );
    }

    case "zenlink_create_room": {
      const payload = z
        .object({
          name: z.string(),
          topic: z.string(),
          rules: z.string().optional(),
          is_private: z.boolean().optional(),
          observable: z.boolean().optional(),
          allowed_agent_ids: z.array(z.string()).optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(async () => {
        const { name, topic, rules, is_private, observable, allowed_agent_ids } =
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
        });
      });
    }

    case "zenlink_update_room_allowlist": {
      const { room_id, allowed_agent_ids } = z
        .object({
          room_id: z.string(),
          allowed_agent_ids: z.array(z.string()).nullable().optional(),
        })
        .parse(rawArgs ?? {});
      return toolTry(() =>
        session.wsRpc(["room_allowlist_updated"], () =>
          client.sendUpdateRoomAllowlist({
            room_id,
            ...(allowed_agent_ids !== undefined ? { allowed_agent_ids } : {}),
          }),
        ),
      );
    }

    case "zenlink_patch_profile": {
      const { body } = z
        .object({ body: z.record(z.string(), z.unknown()) })
        .parse(rawArgs ?? {});
      return toolTry(async () => {
        const data = await patchAgentProfile(client.httpOptions(), body);
        return data ?? { ok: true };
      });
    }

    default:
      return toolError(new Error(`unknown tool: ${tool}`));
  }
}
