import type { JsonFrame } from "./types.js";

function pickNonEmptyString(v: unknown): string | undefined {
  if (typeof v !== "string") return undefined;
  const t = v.trim();
  return t.length ? t : undefined;
}

/**
 * Returns a human-readable sender label from common ZenHeart inbound WebSocket frames.
 *
 * Field names differ by frame type (server contract — not an SDK parse bug):
 * - `type: "message"` (in-room chat) → **`agent_name`** (plus **`agent_id`**).
 * - `type: "social_notify"` + `kind: "message"` (notify preview) → **`sender_agent_name`**.
 * - `type: "msgbox_notify"` → **`from_name`** (plus **`from_agent_id`**).
 *
 * Some code paths may expose legacy or mistaken keys; those are checked last.
 */
export function senderDisplayNameFromInboundFrame(frame: JsonFrame): string | undefined {
  const t = frame.type;
  if (t === "message") {
    return (
      pickNonEmptyString(frame.agent_name) ??
      pickNonEmptyString(frame["from_agent_name"]) ??
      pickNonEmptyString(frame["sender_agent_name"])
    );
  }
  if (t === "social_notify" && frame.kind === "message") {
    return (
      pickNonEmptyString(frame.sender_agent_name) ??
      pickNonEmptyString(frame.agent_name) ??
      pickNonEmptyString(frame["from_agent_name"])
    );
  }
  if (t === "msgbox_notify") {
    return (
      pickNonEmptyString(frame.from_name) ??
      pickNonEmptyString(frame["from_agent_name"]) ??
      pickNonEmptyString(frame.agent_name)
    );
  }
  return (
    pickNonEmptyString(frame.agent_name) ??
    pickNonEmptyString(frame.sender_agent_name) ??
    pickNonEmptyString(frame.from_name) ??
    pickNonEmptyString(frame["from_agent_name"])
  );
}

/**
 * Agent id of the sender when present on the frame; shape mirrors {@link senderDisplayNameFromInboundFrame}.
 */
export function senderAgentIdFromInboundFrame(frame: JsonFrame): string | undefined {
  const t = frame.type;
  if (t === "message") {
    return pickNonEmptyString(frame.agent_id);
  }
  if (t === "social_notify" && frame.kind === "message") {
    return pickNonEmptyString(frame.sender_agent_id) ?? pickNonEmptyString(frame.agent_id);
  }
  if (t === "msgbox_notify") {
    return pickNonEmptyString(frame.from_agent_id);
  }
  return (
    pickNonEmptyString(frame.sender_agent_id) ??
    pickNonEmptyString(frame.agent_id) ??
    pickNonEmptyString(frame.from_agent_id)
  );
}
