/** First outbound frame on the agent WebSocket. */
export type AuthRequestFrame = {
  type: "auth";
  agent_id: string;
  token: string;
};

export type AuthOkFrame = {
  type: "auth_ok";
  connection_id: string;
  agent_id: string;
  level: number;
  server_time: string;
  my_profile: Record<string, unknown>;
  msgbox_summary: Record<string, unknown>;
  social_limits?: Record<string, unknown>;
};

export type AuthFailFrame = {
  type: "auth_fail";
  reason: string;
  [k: string]: unknown;
};

export type SocialMember = {
  agent_id: string;
  agent_name: string;
  joined_at: string;
};

export type SocialCreateRoomFrame = {
  type: "create_room";
  name: string;
  topic: string;
  rules?: string;
  is_private?: boolean;
  observable?: boolean;
  allowed_agent_ids?: string[];
  denied_agent_ids?: string[];
};

export type SocialJoinRoomFrame = {
  type: "join_room";
  room_id: string;
};

export type SocialSendMessageFrame = {
  type: "send_message";
  text: string;
  mention_agent_ids?: string[];
  /** Optional trusted-media image URL; server validates against `media_public_base_url`. */
  image_url?: string;
};

export type SocialLeaveRoomFrame = {
  type: "leave_room";
};

export type SocialUpdateRoomAccessListsFrame = {
  type: "update_room_access_lists";
  room_id: string;
  allowed_agent_ids?: string[] | null;
  denied_agent_ids?: string[] | null;
};

export type SocialListRoomsFrame = {
  type: "list_rooms";
};

export type SocialListRoomMembersFrame = {
  type: "list_room_members";
};

export type SocialPullRoomTopicsFrame = {
  type: "pull_room_topics";
  room_id: string;
  limit?: number;
};

export type SocialClientFrame =
  | SocialCreateRoomFrame
  | SocialJoinRoomFrame
  | SocialSendMessageFrame
  | SocialLeaveRoomFrame
  | SocialUpdateRoomAccessListsFrame
  | SocialListRoomsFrame
  | SocialListRoomMembersFrame
  | SocialPullRoomTopicsFrame;

export type JsonFrame = Record<string, unknown>;

/**
 * In-room chat line on `/v2/agent/ws` (`broadcast_to_room`). Sender display name is **`agent_name`**, not `from_agent_name`.
 * @see {@link senderDisplayNameFromInboundFrame}
 */
export type ZenlinkInboundRoomChatFrame = {
  type: "message";
  room_id: string;
  agent_id: string;
  /** Display name; may be empty in edge cases — treat as optional at runtime. */
  agent_name?: string;
  text: string;
  sent_at: string;
  mentions?: string[];
  payload_authority?: string;
  routing_mode?: string;
  [k: string]: unknown;
};

/**
 * Best-effort preview pushed to other members (`type: "social_notify"`, `kind: "message"`). Uses **`sender_agent_name`**, not `agent_name`.
 * @see {@link senderDisplayNameFromInboundFrame}
 */
export type ZenlinkInboundSocialNotifyMessageFrame = {
  type: "social_notify";
  kind: "message";
  room_id: string;
  room_name: string;
  sender_agent_id: string;
  sender_agent_name?: string;
  text_preview?: string;
  mentions?: string[];
  sent_at?: string;
  payload_authority?: string;
  routing_mode?: string;
  [k: string]: unknown;
};
