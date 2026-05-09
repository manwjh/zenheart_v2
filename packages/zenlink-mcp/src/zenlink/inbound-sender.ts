import type {
  ZenlinkInboundRoomChatFrame,
  ZenlinkInboundSocialNotifyMessageFrame,
} from "./types.js";

export function senderAgentIdFromInboundFrame(
  frame: ZenlinkInboundRoomChatFrame | ZenlinkInboundSocialNotifyMessageFrame,
): string | null {
  return typeof frame.agent_id === "string" ? frame.agent_id : null;
}

export function senderDisplayNameFromInboundFrame(
  frame: ZenlinkInboundRoomChatFrame | ZenlinkInboundSocialNotifyMessageFrame,
): string | null {
  const value = frame.display_name ?? frame.agent_name ?? frame.agent_id;
  return typeof value === "string" ? value : null;
}
