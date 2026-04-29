import * as z from "zod/v4";

/** Wire format for Router -> OpenClaw structured context (not raw chat text). */
export const ZENLINK_ROUTER_CONTEXT_VERSION = "zenlink.router_context/1" as const;

const looseRecord = z.record(z.string(), z.unknown());

export const ZenlinkRouterContextSchema = z
  .object({
    schema_version: z.literal(ZENLINK_ROUTER_CONTEXT_VERSION).optional(),
    agent: looseRecord.optional(),
    session: looseRecord.optional(),
    message: looseRecord.optional(),
    history: z.array(z.unknown()).optional(),
    memory: z.array(z.unknown()).optional(),
  })
  .strict();

export type ZenlinkRouterContext = z.infer<typeof ZenlinkRouterContextSchema>;

/** MCP tool input for `zenlink_router_pack_context` (version is always emitted by {@link packRouterContext}). */
export const ZenlinkRouterPackInputSchema = ZenlinkRouterContextSchema.omit({
  schema_version: true,
});

export type ZenlinkRouterPackInput = z.infer<typeof ZenlinkRouterPackInputSchema>;

export const ZENLINK_ROUTER_RESULT_VERSION = "zenlink.router_result/1" as const;

const dispatchSchema = z.discriminatedUnion("kind", [
  z.object({ kind: z.literal("none") }),
  z.object({
    kind: z.literal("social_reply"),
    room_id: z.string().min(1),
    text: z.string(),
  }),
  z.object({
    kind: z.literal("agent_dm"),
    to_agent_id: z.string().min(1).max(80),
    body: z.string().min(1).max(4000),
    subject: z.string().max(120).optional(),
  }),
]);

export const ZenlinkRouterResultSchema = z
  .object({
    schema_version: z.literal(ZENLINK_ROUTER_RESULT_VERSION).optional(),
    /** Opaque blob for the host/runtime to persist via ZenHeart session APIs (MCP echoes only). */
    persist: z
      .object({
        artifact: z.record(z.string(), z.unknown()),
      })
      .optional(),
    dispatch: dispatchSchema.optional(),
  })
  .strict();

export type ZenlinkRouterResult = z.infer<typeof ZenlinkRouterResultSchema>;

/**
 * Validate and normalize Router context. Returns a single block suitable for system/user injection.
 */
export function packRouterContext(input: unknown): {
  schema_version: typeof ZENLINK_ROUTER_CONTEXT_VERSION;
  value: ZenlinkRouterContext;
  prompt_block: string;
} {
  const parsed = ZenlinkRouterContextSchema.parse(input);
  const value: ZenlinkRouterContext = {
    ...parsed,
    schema_version: ZENLINK_ROUTER_CONTEXT_VERSION,
  };
  const json = JSON.stringify(value, null, 2);
  const prompt_block = [
    `<zenheart_router_context version="${ZENLINK_ROUTER_CONTEXT_VERSION}">`,
    json,
    `</zenheart_router_context>`,
  ].join("\n");
  return { schema_version: ZENLINK_ROUTER_CONTEXT_VERSION, value, prompt_block };
}

/** Validate OpenClaw / host JSON output before persistence or downstream routing. */
export function normalizeRouterResult(input: unknown): ZenlinkRouterResult {
  return ZenlinkRouterResultSchema.parse(input);
}
