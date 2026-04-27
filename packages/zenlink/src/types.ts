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

export type JsonFrame = Record<string, unknown>;
