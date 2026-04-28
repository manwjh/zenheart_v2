/** First outbound frame on agent + social WebSocket channels. */
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
};

export type SocialJoinRoomFrame = {
  type: "join_room";
  room_id: string;
};

export type SocialSendMessageFrame = {
  type: "send_message";
  text: string;
  mention_agent_ids?: string[];
};

export type SocialLeaveRoomFrame = {
  type: "leave_room";
};

export type SocialUpdateRoomAllowlistFrame = {
  type: "update_room_allowlist";
  room_id: string;
  allowed_agent_ids?: string[] | null;
};

export type SocialListRoomsFrame = {
  type: "list_rooms";
};

export type SocialListRoomMembersFrame = {
  type: "list_room_members";
};

export type SocialClientFrame =
  | SocialCreateRoomFrame
  | SocialJoinRoomFrame
  | SocialSendMessageFrame
  | SocialLeaveRoomFrame
  | SocialUpdateRoomAllowlistFrame
  | SocialListRoomsFrame
  | SocialListRoomMembersFrame;

export type JsonFrame = Record<string, unknown>;
