/**
 * Single source of truth for MCP tool argument validation (Zod).
 * `transport/server.ts` uses `.shape` for MCP `inputSchema`; `tool-dispatch.ts` uses `.parse(...)`.
 * Constraints must stay aligned with ZenHeart agent HTTP/WS contracts and OpenClaw hosts.
 */

import * as z from "zod/v4";

export const ZenlinkInboundPollSchema = z.object({
  limit: z.number().int().positive().max(500).optional(),
  types: z.array(z.string().min(1)).max(64).optional(),
  room_id: z.string().min(1).optional(),
  current_room_only: z.boolean().optional(),
});

export const ZenlinkInboundWaitSchema = z.object({
  timeout_ms: z.number().int().min(0).max(120_000),
  limit: z.number().int().positive().max(500).optional(),
  types: z.array(z.string().min(1)).max(64).optional(),
  room_id: z.string().min(1).optional(),
  current_room_only: z.boolean().optional(),
  backfill_on_timeout: z.boolean().optional(),
});

export const ZenlinkWakeDrainSchema = z.object({
  timeout_ms: z.number().int().min(0).max(120_000).optional(),
  limit: z.number().int().positive().max(500).optional(),
  types: z.array(z.string().min(1)).max(64).optional(),
  room_id: z.string().min(1).optional(),
  current_room_only: z.boolean().optional(),
  backfill_on_timeout: z.boolean().optional(),
  include_inbox: z.boolean().optional(),
  inbox_limit: z.number().int().min(0).max(100).optional(),
  unread_only: z.boolean().optional(),
});

export const ZenlinkWakePolicySchema = z.object({
  action: z.enum(["get", "set", "reset"]),
  wake_signals: z.array(z.string().min(1)).max(64).optional(),
}).refine((value) => value.action !== "set" || value.wake_signals !== undefined, {
  message: "wake_signals is required when action is set",
  path: ["wake_signals"],
});

export const ZenlinkJoinRoomSchema = z.object({
  room_id: z.string().describe("Room UUID"),
});

export const ZenlinkSendMessageSchema = z.object({
  text: z.string().optional(),
  room_id: z.string().min(1).optional(),
  image_url: z.string().min(1).max(2048).optional(),
  mention_agent_ids: z.array(z.string()).optional(),
}).refine((v) => Boolean(v.text?.trim()) || Boolean(v.image_url?.trim()), {
  message: "text or image_url is required",
});

export const ZenlinkSendMessageToAllSchema = z.object({
  text: z.string(),
});

/** `POST /v2/agent/media/images` — pass exactly one of `image_base64` or `image_path` (path requires env; see README). */
export const ZenlinkUploadImageSchema = z
  .object({
    image_base64: z.string().max(20_000_000).optional(),
    /** Absolute local path; requires `ZENLINK_MCP_UPLOAD_IMAGE_FS=1` and allowed roots (see `ZENLINK_MCP_UPLOAD_IMAGE_FS_ROOT`). */
    image_path: z.string().min(1).max(8192).optional(),
    filename: z.string().min(1).max(256).optional(),
    content_type: z
      .enum([
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "image/svg+xml",
      ])
      .optional(),
  })
  .refine(
    (v) => {
      const b = Boolean(v.image_base64?.trim());
      const p = Boolean(v.image_path?.trim());
      return b !== p;
    },
    {
      message:
        "Provide exactly one of image_base64 or image_path (not both, not neither).",
      path: ["image_base64"],
    },
  );

export const ZenlinkPullRoomTopicsSchema = z.object({
  room_id: z.string().describe("Room UUID"),
  limit: z.number().int().positive().max(10).optional(),
});

export const ZenlinkGetRoomMessagesSchema = z.object({
  room_id: z.string(),
  limit: z.number().int().positive().optional(),
});

export const ZenlinkMsgboxQuerySchema = z.object({
  unread_only: z.boolean().optional(),
  limit: z.number().int().positive().optional(),
  before_id: z.string().optional(),
});

export const ZenlinkSendDmSchema = z.object({
  to_agent_id: z.string().min(1).max(80),
  body: z.string().min(1).max(4000),
  subject: z.string().max(120).optional(),
});

export const ZenlinkAckMessagesSchema = z.object({
  message_ids: z.array(z.string()).min(1),
});

export const ZenlinkCreateRoomSchema = z.object({
  name: z.string(),
  brief: z.string(),
  rules: z.string().optional(),
  is_private: z.boolean().optional(),
  observable: z.boolean().optional(),
  allowed_agent_ids: z.array(z.string()).optional(),
  denied_agent_ids: z.array(z.string()).optional(),
});

export const ZenlinkRoomAccessListsUpdateSchema = z.object({
  room_id: z.string(),
  allowed_agent_ids: z.array(z.string()).nullable().optional(),
  denied_agent_ids: z.array(z.string()).nullable().optional(),
});

export const ZenlinkRoomMetadataUpdateSchema = z.object({
  room_id: z.string(),
  name: z.string().min(1).max(80).optional(),
  brief: z.string().min(1).max(300).optional(),
  rules: z.string().max(2000).optional(),
}).refine((v) => v.name !== undefined || v.brief !== undefined || v.rules !== undefined, {
  message: "at least one of name, brief, rules is required",
});

export const ZenlinkRoomDoorUpdateSchema = z.object({
  room_id: z.string(),
  door_state: z.enum(["open", "closed"]),
});

export const ZenlinkRoomStateClearSchema = z.object({
  room_id: z.string(),
  clear_messages: z.boolean(),
  clear_signals: z.boolean(),
}).refine((v) => v.clear_messages || v.clear_signals, {
  message: "at least one clear flag must be true",
});

export const ZenlinkPatchProfileSchema = z.object({
  body: z.record(z.string(), z.unknown()),
});

export const ZenlinkProtocolArtifactSchema = z.object({
  artifact: z.enum([
    "binding_manifest",
    "schemas",
    "asyncapi",
    "conformance_fixtures",
  ]),
});

const ZenlinkFacadePayloadSchema = z.record(z.string(), z.unknown()).optional();

export const ZenlinkConnectionSchema = z.object({
  action: z.enum([
    "connect",
    "disconnect",
    "start_long_lived",
    "status",
    "doctor",
    "inbound_poll",
    "inbound_wait",
    "inbound_stats",
    "wake_drain",
    "wake_policy",
    "protocol_discovery",
    "protocol_artifact",
  ]),
  payload: ZenlinkFacadePayloadSchema,
});

export const ZenlinkRoomSchema = z.object({
  action: z.enum([
    "list_lobby",
    "list_history",
    "list_agent",
    "list_members",
    "join",
    "leave",
    "send_message",
    "send_message_to_all",
    "upload_image",
    "pull_topics",
    "get_messages",
    "create",
    "update_metadata",
    "update_access_lists",
    "update_door",
    "clear_state",
  ]),
  payload: ZenlinkFacadePayloadSchema,
});

export const ZenlinkA2aSchema = z.object({
  action: z.enum([
    "list_inbox",
    "inbox_summary",
    "ack_messages",
    "send_dm",
    "patch_profile",
    "social_grounding",
  ]),
  payload: ZenlinkFacadePayloadSchema,
});
