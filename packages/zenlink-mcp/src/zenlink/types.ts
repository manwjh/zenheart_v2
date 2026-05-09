export type JsonFrame = Record<string, unknown>;

export interface AuthRequestFrame extends JsonFrame {
  type: "auth";
  agent_id: string;
  token: string;
}

export interface AuthOkFrame extends JsonFrame {
  type: "auth_ok";
}

export interface AuthFailFrame extends JsonFrame {
  type: "auth_fail";
  reason?: string;
}

export interface SocialMember extends JsonFrame {
  agent_id: string;
}

export interface SocialCreateRoomFrame extends JsonFrame {
  type: "create_room";
}

export interface SocialJoinRoomFrame extends JsonFrame {
  type: "join_room";
  room_id: string;
}

export interface SocialSendMessageFrame extends JsonFrame {
  type: "send_message";
  text: string;
}

export interface SocialLeaveRoomFrame extends JsonFrame {
  type: "leave_room";
}

export interface SocialUpdateRoomAccessListsFrame extends JsonFrame {
  type: "update_room_access_lists";
}

export interface SocialListRoomsFrame extends JsonFrame {
  type: "list_rooms";
}

export interface SocialListRoomMembersFrame extends JsonFrame {
  type: "list_room_members";
}

export interface SocialPullRoomTopicsFrame extends JsonFrame {
  type: "pull_room_topics";
}

export type SocialClientFrame =
  | SocialCreateRoomFrame
  | SocialJoinRoomFrame
  | SocialSendMessageFrame
  | SocialLeaveRoomFrame
  | SocialUpdateRoomAccessListsFrame
  | SocialListRoomsFrame
  | SocialListRoomMembersFrame
  | SocialPullRoomTopicsFrame;

export interface ZenlinkInboundRoomChatFrame extends JsonFrame {
  type: "message";
  agent_id?: string;
  room_id?: string;
  text?: string;
}

export interface ZenlinkInboundSocialNotifyMessageFrame extends JsonFrame {
  type: "social_notify";
  kind?: string;
  agent_id?: string;
  room_id?: string;
  text?: string;
}
