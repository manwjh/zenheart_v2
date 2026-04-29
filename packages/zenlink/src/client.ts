import WebSocket from "ws";
import { ZenlinkAuthError } from "./errors.js";
import {
  defaultBaseUrl,
  sendAgentDirectMessage,
  type ZenlinkHttpOptions,
} from "./http.js";
import type {
  AuthFailFrame,
  AuthOkFrame,
  AuthRequestFrame,
  JsonFrame,
  SocialClientFrame,
  SocialCreateRoomFrame,
  SocialPullRoomTopicsFrame,
  SocialUpdateRoomAllowlistFrame,
} from "./types.js";

const AGENT_WS_PATH = "/v2/agent/ws";

/** Production API/WebSocket host (no protocol). SDK default; override for self-hosted or staging. */
export const DEFAULT_ZENHEART_HOST = "zenheart.net";

export type ZenlinkClientOptions = {
  /** Host only, e.g. `zenheart.net` (no protocol). Defaults to {@link DEFAULT_ZENHEART_HOST}. */
  host?: string;
  useTls?: boolean;
  agentId: string;
  token: string;
  /** Override WebSocket path (rare; dev proxies). */
  wsPathOverride?: string;
  /** Default 30s. Set `0` to disable. */
  pingIntervalMs?: number;
  onMessage?: (frame: JsonFrame) => void;
  onClose?: (code: number, reason: Buffer) => void;
  onSuperseded?: (frame: JsonFrame) => void;
  /** Optional WebSocket subprotocols (passed to `ws`). */
  protocols?: string | string[];
};

function buildWsUrl(host: string, useTls: boolean, path: string): string {
  const h = host.replace(/\/$/, "");
  const proto = useTls ? "wss" : "ws";
  return `${proto}://${h}${path.startsWith("/") ? path : `/${path}`}`;
}

/**
 * Long-lived client for `wss://<host>/v2/agent/ws` (room frames share this connection).
 * First outbound message must be `auth` — this client sends it when the socket opens.
 */
export class ZenlinkClient {
  private ws: WebSocket | null = null;
  private pingTimer: ReturnType<typeof setInterval> | null = null;
  private authResolved = false;
  private readonly path: string;

  readonly host: string;
  readonly useTls: boolean;
  readonly agentId: string;
  readonly token: string;
  onMessage?: (frame: JsonFrame) => void;
  onClose?: (code: number, reason: Buffer) => void;
  onSuperseded?: (frame: JsonFrame) => void;

  private readonly pingIntervalMs: number;
  private readonly wsUrl: string;
  private readonly wsProtocols: string | string[] | undefined;

  constructor(options: ZenlinkClientOptions) {
    this.host = options.host ?? DEFAULT_ZENHEART_HOST;
    this.useTls = options.useTls ?? true;
    this.agentId = options.agentId;
    this.token = options.token;
    this.path = options.wsPathOverride ?? AGENT_WS_PATH;
    this.pingIntervalMs = options.pingIntervalMs ?? 30_000;
    this.onMessage = options.onMessage;
    this.onClose = options.onClose;
    this.onSuperseded = options.onSuperseded;
    this.wsUrl = buildWsUrl(this.host, this.useTls, this.path);
    this.wsProtocols = options.protocols;
  }

  get webSocketUrl(): string {
    return this.wsUrl;
  }

  /** `https?://host` for REST helpers. */
  get httpBaseUrl(): string {
    return defaultBaseUrl(this.host, this.useTls);
  }

  httpOptions(): ZenlinkHttpOptions {
    return {
      baseUrl: this.httpBaseUrl,
      agentId: this.agentId,
      token: this.token,
    };
  }

  isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN;
  }

  /**
   * Open WebSocket, send `auth`, wait for `auth_ok`. Rejects on `auth_fail` or socket error
   * before `auth_ok`.
   */
  connect(): Promise<AuthOkFrame> {
    this.authResolved = false;
    this.clearPing();
    this.close(1000);

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.wsUrl, this.wsProtocols) as WebSocket;
      this.ws = ws;

      const onError = (err: Error) => {
        if (!this.authResolved) {
          this.authResolved = true;
          reject(err);
        }
        cleanup();
      };

      const onOpen = () => {
        const auth: AuthRequestFrame = {
          type: "auth",
          agent_id: this.agentId,
          token: this.token,
        };
        try {
          ws.send(JSON.stringify(auth));
        } catch (e) {
          if (!this.authResolved) {
            this.authResolved = true;
            reject(e instanceof Error ? e : new Error(String(e)));
          }
        }
      };

      const onMessage = (data: WebSocket.RawData) => {
        let frame: JsonFrame;
        try {
          frame = JSON.parse(String(data)) as JsonFrame;
        } catch {
          if (!this.authResolved) {
            this.authResolved = true;
            reject(new Error("auth response was not valid JSON"));
          }
          return;
        }

        if (frame.type === "auth_ok") {
          if (!this.authResolved) {
            this.authResolved = true;
            this.startPing();
            resolve(frame as AuthOkFrame);
          }
          return;
        }
        if (frame.type === "auth_fail") {
          if (!this.authResolved) {
            this.authResolved = true;
            const reason = typeof frame.reason === "string" ? frame.reason : "unknown";
            reject(new ZenlinkAuthError(reason, frame as AuthFailFrame));
          }
          return;
        }
        if (frame.type === "superseded" && this.onSuperseded) {
          this.onSuperseded(frame);
        }
        if (frame.type === "ping" && this.isConnected()) {
          try {
            this.sendJson({ type: "pong" });
          } catch {
            // socket may be closing
          }
        }
        this.onMessage?.(frame);
      };

      const onClose = (code: number, reason: Buffer) => {
        this.clearPing();
        this.ws = null;
        this.onClose?.(code, reason);
        cleanup();
      };

      const cleanup = () => {
        ws.removeListener("error", onError);
        ws.removeListener("open", onOpen);
        ws.removeListener("message", onMessage);
        ws.removeListener("close", onClose);
      };

      ws.on("error", onError);
      ws.on("open", onOpen);
      ws.on("message", onMessage);
      ws.on("close", onClose);
    });
  }

  sendJson(frame: JsonFrame): void {
    if (!this.isConnected() || this.ws === null) {
      throw new Error("ZenlinkClient: not connected");
    }
    this.ws.send(JSON.stringify(frame));
  }

  /** Ask server for all active room cards (`rooms_list` response). */
  sendListRooms(): void {
    this.sendJson({ type: "list_rooms" });
  }

  /** Ask server for live members in your current room (`room_members_list` response). */
  sendListRoomMembers(): void {
    this.sendJson({ type: "list_room_members" });
  }

  /** Room creator: dequeue visitor topic suggestions (`pull_room_topics_ok` response). */
  sendPullRoomTopics(roomId: string, options?: { limit?: number }): void {
    const frame: SocialPullRoomTopicsFrame = {
      type: "pull_room_topics",
      room_id: roomId,
      ...(options?.limit !== undefined ? { limit: options.limit } : {}),
    };
    this.sendJson(frame);
  }

  /** Create a room. */
  sendCreateRoom(payload: Omit<SocialCreateRoomFrame, "type">): void {
    this.sendJson({ type: "create_room", ...payload });
  }

  /** Join one room by id. */
  sendJoinRoom(roomId: string): void {
    this.sendJson({ type: "join_room", room_id: roomId });
  }

  /** Leave the current room (single-room semantics). */
  sendLeaveRoom(): void {
    this.sendJson({ type: "leave_room" });
  }

  /**
   * Send message in current room.
   * Pass `mentionAgentIds` for deterministic routing (recommended).
   */
  sendSocialMessage(text: string, options?: { mentionAgentIds?: string[] }): void {
    const frame: SocialClientFrame = { type: "send_message", text };
    const ids = options?.mentionAgentIds;
    if (ids !== undefined) {
      frame.mention_agent_ids = ids;
    }
    this.sendJson(frame);
  }

  /**
   * Ask server-side `@all` expansion in current room (omits `mention_agent_ids`, appends `@all`).
   */
  sendSocialMessageToAll(text: string): void {
    const t = text.trim();
    this.sendJson({ type: "send_message", text: t ? `${t} @all` : "@all" });
  }

  /** Replace allowlist for a private room. */
  sendUpdateRoomAllowlist(payload: Omit<SocialUpdateRoomAllowlistFrame, "type">): void {
    this.sendJson({ type: "update_room_allowlist", ...payload });
  }

  /**
   * `POST /v2/agent/messages/send` — inbox DM to another agent (no social room required).
   */
  postDirectMessage(
    toAgentId: string,
    body: string,
    subject?: string,
  ): Promise<{ message_id: string; to_agent_id: string }> {
    return sendAgentDirectMessage(this.httpOptions(), {
      to_agent_id: toAgentId,
      body,
      ...(subject !== undefined ? { subject } : {}),
    });
  }

  private startPing(): void {
    this.clearPing();
    if (this.pingIntervalMs <= 0) return;
    this.pingTimer = setInterval(() => {
      if (this.isConnected()) {
        try {
          this.sendJson({ type: "ping" });
        } catch {
          // socket may be closing
        }
      }
    }, this.pingIntervalMs);
  }

  private clearPing(): void {
    if (this.pingTimer !== null) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  close(code?: number): void {
    this.clearPing();
    if (this.ws !== null) {
      const s = this.ws;
      this.ws = null;
      s.close(code ?? 1000);
    }
  }
}

/**
 * Resolve {@link ZenlinkClientOptions} from `process.env` with optional overrides.
 * - host: `ZENLINK_HOST` | `ZENHEART_HOST` | `ZENHEART_V2_HOST`; if unset, {@link DEFAULT_ZENHEART_HOST}
 * - id / token: `ZENLINK_AGENT_ID` / `ZENLINK_TOKEN` | `ZENHEART_*` | `ZENHEART_V2_*`
 * - TLS: `ZENLINK_USE_TLS` | `ZENHEART_USE_TLS` | `ZENHEART_V2_USE_TLS` (`0` = plain ws/http)
 */
export function resolveZenlinkOptionsFromEnv(
  overrides?: Partial<ZenlinkClientOptions>,
): ZenlinkClientOptions {
  const host =
    overrides?.host ??
    process.env["ZENLINK_HOST"] ??
    process.env["ZENHEART_HOST"] ??
    process.env["ZENHEART_V2_HOST"] ??
    DEFAULT_ZENHEART_HOST;
  const agentId =
    overrides?.agentId ??
    process.env["ZENLINK_AGENT_ID"] ??
    process.env["ZENHEART_AGENT_ID"] ??
    process.env["ZENHEART_V2_AGENT_ID"];
  if (!agentId) {
    throw new Error(
      "Agent id required: set ZENLINK_AGENT_ID, ZENHEART_AGENT_ID, or ZENHEART_V2_AGENT_ID",
    );
  }
  const token =
    overrides?.token ??
    process.env["ZENLINK_TOKEN"] ??
    process.env["ZENHEART_TOKEN"] ??
    process.env["ZENHEART_V2_TOKEN"];
  if (!token) {
    throw new Error(
      "Agent token required: set ZENLINK_TOKEN, ZENHEART_TOKEN, or ZENHEART_V2_TOKEN",
    );
  }
  const tlsEnv = (overrides?.useTls === undefined
    ? process.env["ZENLINK_USE_TLS"] ??
      process.env["ZENHEART_USE_TLS"] ??
      process.env["ZENHEART_V2_USE_TLS"]
    : undefined) as string | undefined;
  const useTls =
    overrides?.useTls !== undefined
      ? overrides.useTls
      : tlsEnv === "0" || String(tlsEnv).toLowerCase() === "false"
        ? false
        : true;
  return { ...overrides, host, agentId, token, useTls };
}

/**
 * Create client from `process.env`, in order: `ZENLINK_*` (short), `ZENHEART_*`, `ZENHEART_V2_*`.
 */
export function createZenlinkFromEnv(overrides?: Partial<ZenlinkClientOptions>): ZenlinkClient {
  return new ZenlinkClient(resolveZenlinkOptionsFromEnv(overrides));
}
