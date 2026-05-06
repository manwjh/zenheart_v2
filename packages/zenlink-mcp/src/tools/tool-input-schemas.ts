/**
 * Single source of truth for MCP tool argument validation (Zod).
 * `transport/server.ts` uses `.shape` for MCP `inputSchema`; `tool-dispatch.ts` uses `.parse(...)`.
 * Constraints must stay aligned with ZenHeart agent HTTP/WS contracts and OpenClaw hosts.
 */

import * as z from "zod/v4";

export const ZenlinkParticipantRulesSetSchema = z.object({
  body: z.string().min(1).max(96_000),
});

export const ZenlinkInboundPollSchema = z.object({
  limit: z.number().int().positive().max(500).optional(),
  types: z.array(z.string().min(1)).max(64).optional(),
});

export const ZenlinkInboundWaitSchema = z.object({
  timeout_ms: z.number().int().min(0).max(120_000),
  limit: z.number().int().positive().max(500).optional(),
  types: z.array(z.string().min(1)).max(64).optional(),
});

export const ZenlinkJoinRoomSchema = z.object({
  room_id: z.string().describe("Room UUID"),
});

export const ZenlinkSendMessageSchema = z.object({
  text: z.string().optional(),
  image_url: z.string().min(1).max(2048).optional(),
  mention_agent_ids: z.array(z.string()).optional(),
}).refine((v) => Boolean(v.text?.trim()) || Boolean(v.image_url?.trim()), {
  message: "text or image_url is required",
});

export const ZenlinkSendMessageToAllSchema = z.object({
  text: z.string(),
});

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
  topic: z.string(),
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

export const ZenlinkPatchProfileSchema = z.object({
  body: z.record(z.string(), z.unknown()),
});

export const ZenlinkNewsListSchema = z.object({
  publisher_agent_id: z.string().optional(),
  tag: z.string().optional(),
  category_primary: z.string().optional(),
  category_secondary: z.string().optional(),
  classification: z.enum(["categorized", "uncategorized"]).optional(),
  limit: z.number().int().positive().max(200).optional(),
  before_id: z.string().optional(),
});

export const ZenlinkNewsArticleIdSchema = z.object({
  article_id: z.string().min(1).max(80),
});

export const ZenlinkNewsPublishSchema = z.object({
  title: z.string().min(1).max(200),
  summary: z.string().min(1).max(2000),
  cover_image_url: z.string().min(1).max(2048),
  markdown: z.string().min(1).max(2_000_000),
  tags: z.array(z.string()).optional(),
  keywords: z.array(z.string()).optional(),
  published_at: z.string().min(1).max(80).optional(),
});

export const ZenlinkNewsUpdateSchema = z.object({
  article_id: z.string().min(1).max(80),
  title: z.string().min(1).max(200).optional(),
  summary: z.string().min(1).max(2000).optional(),
  cover_image_url: z.string().min(1).max(2048).optional(),
  markdown: z.string().min(1).max(2_000_000).optional(),
  tags: z.array(z.string()).optional(),
  keywords: z.array(z.string()).optional(),
  published_at: z.string().min(1).max(80).optional(),
});

/** `/v2/admin/*` — server accepts `X-Admin-Key` or sovereign L0 `X-Agent-Id`/`X-Agent-Token`. */

export const ZenlinkAdminAgentIdSchema = z.object({
  agent_id: z.string().min(1).max(80),
});

export const ZenlinkAdminCreateAgentSchema = z.object({
  email: z.string().email(),
  agent_name: z.string().min(1).max(120),
  level: z.number().int().min(0).max(9),
  label: z.string().max(256).nullable().optional(),
});

export const ZenlinkAdminSocialWebhookSchema = z.object({
  agent_id: z.string().min(1).max(80),
  social_webhook_url: z.union([z.string().url().max(2048), z.null()]),
});

export const ZenlinkAdminAgentEventLogsSchema = z.object({
  agent_id: z.string().min(1).max(80),
  limit: z.number().int().min(1).max(500).optional(),
  offset: z.number().int().min(0).optional(),
});

export const ZenlinkAdminDispatchCommandSchema = z.object({
  agent_id: z.string().min(1).max(80),
  command: z.string().min(1).max(120),
  args: z.record(z.string(), z.unknown()).optional(),
  timeout_seconds: z.number().int().min(1).max(300),
});

export const ZenlinkAdminSocialDeliveryStatsSchema = z.object({
  window_hours: z.number().int().min(1).max(168).optional(),
});

export const ZenlinkAdminPermissionUpsertSchema = z.object({
  module: z.string().min(1).max(80),
  action: z.string().min(1).max(80),
  max_level: z.number().int().min(0).max(9),
  limit_value: z.number().int().min(0).nullable().optional(),
  description: z.string().max(500).nullable().optional(),
});

export const ZenlinkAdminPermissionDeleteSchema = z.object({
  module: z.string().min(1).max(80),
  action: z.string().min(1).max(80),
});

export const ZenlinkAdminWallListSchema = z.object({
  include_hidden: z.boolean().optional(),
  limit: z.number().int().min(1).max(500).optional(),
});

export const ZenlinkAdminWallPatchSchema = z.object({
  message_id: z.string().uuid(),
  is_hidden: z.boolean(),
});

export const ZenlinkAdminNewsArticleIdSchema = z.object({
  article_id: z.string().uuid(),
});

export const ZenlinkAdminNewsColumnAddSchema = z.object({
  agent_id: z.string().min(1).max(80),
});

export const ZenlinkAdminNewsColumnOrderSchema = z.object({
  agent_ids: z.array(z.string().min(1).max(80)).min(1),
});

const adminNewsCategorySchema = z.object({
  primary: z.string().min(1).max(60).optional(),
  secondary: z.string().min(1).max(60).optional(),
});

export const ZenlinkAdminNewsArticlePatchSchema = z.object({
  article_id: z.string().uuid(),
  title: z.string().min(1).max(200).optional(),
  summary: z.string().min(1).max(2000).optional(),
  cover_image_url: z.string().min(1).max(2048).optional(),
  markdown_path: z.string().min(1).max(4000).optional(),
  tags: z.array(z.string()).optional(),
  keywords: z.array(z.string()).optional(),
  published_at: z.string().optional(),
  score: z.number().int().optional(),
  category: adminNewsCategorySchema.optional(),
});

/** `/v2/agent/ws` sovereign frames (`admin_*` → `admin_*_ok`). Server enforces level 0. */

export const ZenlinkWsAdminListAgentsSchema = z.object({
  include_revoked: z.boolean().optional(),
});

export const ZenlinkWsAdminSetPermissionSchema = z.object({
  module: z.string().min(1).max(60),
  action: z.string().min(1).max(60),
  max_level: z.number().int().min(0).max(9),
  limit_value: z.number().int().min(0).nullable().optional(),
  description: z.string().max(500).nullable().optional(),
});

export const ZenlinkWsAdminSendDirectiveSchema = z.object({
  to_agent_id: z.string().min(1).max(80),
  body: z.string().min(1).max(4000),
  subject: z.string().max(120).optional(),
  priority: z.number().int().min(1).max(3).optional(),
});

export const ZenlinkWsAdminSetAgentLevelSchema = z.object({
  agent_id: z.string().min(1).max(80),
  level: z.number().int().min(0).max(9),
});

export const ZenlinkWsAdminSetWebhookSchema = z.object({
  agent_id: z.string().min(1).max(80),
  social_webhook_url: z.union([z.string().url().max(2000), z.null()]).optional(),
});

export const ZenlinkWsAdminListArticlesSchema = z.object({
  limit: z.number().int().min(1).max(100).optional(),
  publisher_agent_id: z.string().min(1).max(80).optional(),
  before_id: z.string().optional(),
});

export const ZenlinkWsAdminSetArticleCategorySchema = z.object({
  article_id: z.string().uuid(),
  category: z
    .object({
      primary: z.string().nullable().optional(),
      secondary: z.string().nullable().optional(),
    })
    .optional(),
});

export const ZenlinkWsAdminModerateArticleSchema = z.object({
  article_id: z.string().uuid(),
  reason: z.string().min(10).max(500),
});

export const ZenlinkWsAdminDissolveRoomSchema = z.object({
  room_id: z.string().min(1).max(80),
  note: z.string().max(500).optional(),
});

export const ZenlinkWsAdminResurrectRoomSchema = z.object({
  room_id: z.string().min(1).max(80),
  note: z.string().max(500).optional(),
});
