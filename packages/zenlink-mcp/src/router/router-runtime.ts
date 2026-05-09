import * as z from "zod/v4";

export const ZenlinkRouterPackInputSchema = z.object({
  agent: z.record(z.string(), z.unknown()).optional(),
  session: z.record(z.string(), z.unknown()).optional(),
  messages: z.array(z.record(z.string(), z.unknown())).optional(),
  history: z.array(z.unknown()).optional(),
  memory: z.array(z.unknown()).optional(),
});

export const ZenlinkRouterResultSchema = z.object({
  persist: z.unknown().optional(),
  dispatch: z
    .discriminatedUnion("kind", [
      z.object({ kind: z.literal("none") }),
      z.object({
        kind: z.literal("agent_dm"),
        to_agent_id: z.string().min(1),
        body: z.string().min(1),
        subject: z.string().optional(),
      }),
      z.object({
        kind: z.literal("social_reply"),
        room_id: z.string().min(1),
        text: z.string().min(1),
      }),
    ])
    .optional(),
});

export type ZenlinkRouterResult = z.infer<typeof ZenlinkRouterResultSchema>;

export function packRouterContext(input: z.infer<typeof ZenlinkRouterPackInputSchema>): Record<string, unknown> {
  const canonical = {
    schema: "zenlink.router_context/1",
    agent: input.agent ?? {},
    session: input.session ?? {},
    messages: input.messages ?? [],
    history: input.history ?? [],
    memory: input.memory ?? [],
  };
  return {
    ok: true,
    prompt_block: JSON.stringify(canonical, null, 2),
    context: canonical,
  };
}

export function normalizeRouterResult(input: ZenlinkRouterResult): ZenlinkRouterResult {
  return {
    ...input,
    dispatch: input.dispatch ?? { kind: "none" },
  };
}
