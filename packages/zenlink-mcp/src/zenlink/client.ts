import WebSocket from "ws";
import {
  formatZenlinkErrorFrame,
  isZenlinkErrorFrame,
  ZenlinkAuthError,
  ZenlinkProtocolError,
} from "./errors.js";
import { defaultBaseUrl } from "./http.js";
import type { JsonFrame } from "./types.js";
import type { ZenlinkHttpOptions } from "./http.js";

export const DEFAULT_ZENHEART_HOST = "zenheart.net";

export interface ZenlinkClientOptions {
  agentId: string;
  token: string;
  host: string;
  useTls: boolean;
  wsTimeoutMs: number;
  wsPingIntervalMs: number;
}

export type ZenlinkConnectionState = "offline" | "connecting" | "authenticated";

export interface ZenlinkCloseEvent {
  code: number;
  reason: string;
  at: string;
}

export function resolveZenlinkOptionsFromEnv(env: NodeJS.ProcessEnv = process.env): ZenlinkClientOptions {
  const agentId = firstEnv(env, ["ZENLINK_AGENT_ID", "ZENHEART_AGENT_ID", "ZENHEART_V2_AGENT_ID"]);
  const token = firstEnv(env, ["ZENLINK_TOKEN", "ZENHEART_TOKEN", "ZENHEART_V2_TOKEN"]);
  if (!agentId) throw new Error("Missing ZENLINK_AGENT_ID from the registration email");
  if (!token) throw new Error("Missing ZENLINK_TOKEN from the registration email");
  return {
    agentId,
    token,
    host: env.ZENLINK_HOST?.trim() || DEFAULT_ZENHEART_HOST,
    useTls: env.ZENLINK_USE_TLS?.trim().toLowerCase() !== "0",
    wsTimeoutMs: parseTimeout(env.ZENLINK_MCP_WS_TIMEOUT_MS),
    wsPingIntervalMs: parsePingInterval(env.ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS),
  };
}

export function createZenlinkFromEnv(env: NodeJS.ProcessEnv = process.env): ZenlinkClient {
  return new ZenlinkClient(resolveZenlinkOptionsFromEnv(env));
}

export class ZenlinkClient {
  readonly agentId: string;
  readonly token: string;
  readonly host: string;
  readonly useTls: boolean;
  readonly wsTimeoutMs: number;
  readonly wsPingIntervalMs: number;
  readonly httpBaseUrl: string;
  readonly wsUrl: string;

  private socket: WebSocket | null = null;
  private state: ZenlinkConnectionState = "offline";
  private connectPromise: Promise<JsonFrame> | null = null;
  private pingTimer: NodeJS.Timeout | null = null;
  private lastCloseEvent: ZenlinkCloseEvent | null = null;
  private readonly handlers = new Set<(frame: JsonFrame) => void>();
  private readonly closeHandlers = new Set<(event: ZenlinkCloseEvent) => void>();
  private readonly errorHandlers = new Set<(error: Error) => void>();

  constructor(options: Partial<ZenlinkClientOptions> = {}) {
    const resolved = completeOptions(options);
    this.agentId = resolved.agentId;
    this.token = resolved.token;
    this.host = resolved.host;
    this.useTls = resolved.useTls;
    this.wsTimeoutMs = resolved.wsTimeoutMs;
    this.wsPingIntervalMs = resolved.wsPingIntervalMs;
    this.httpBaseUrl = defaultBaseUrl(this.host, this.useTls);
    this.wsUrl = `${this.useTls ? "wss" : "ws"}://${this.host.replace(/^wss?:\/\//, "").replace(/^https?:\/\//, "").replace(/\/+$/, "")}/v2/agent/ws`;
  }

  httpOptions(): ZenlinkHttpOptions {
    return {
      baseUrl: this.httpBaseUrl,
      agentId: this.agentId,
      token: this.token,
    };
  }

  onMessage(handler: (frame: JsonFrame) => void): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  onClose(handler: (event: ZenlinkCloseEvent) => void): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  onError(handler: (error: Error) => void): () => void {
    this.errorHandlers.add(handler);
    return () => this.errorHandlers.delete(handler);
  }

  connectionState(): ZenlinkConnectionState {
    return this.state;
  }

  lastClose(): ZenlinkCloseEvent | null {
    return this.lastCloseEvent;
  }

  isOnline(): boolean {
    return this.state === "authenticated" && this.socket?.readyState === WebSocket.OPEN;
  }

  async connect(): Promise<JsonFrame> {
    if (this.isOnline()) return { type: "already_online" };
    if (this.connectPromise) return this.connectPromise;
    this.teardownSocket();
    this.state = "connecting";
    const socket = new WebSocket(this.wsUrl);
    this.socket = socket;
    this.connectPromise = new Promise<JsonFrame>((resolve, reject) => {
      let settled = false;
      const finish = (fn: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this.connectPromise = null;
        fn();
      };
      const fail = (error: Error) => {
        finish(() => {
          if (this.socket === socket) {
            this.state = "offline";
          }
          this.teardownSocket(socket);
          reject(error);
        });
      };
      const timer = setTimeout(
        () => fail(new Error("timeout waiting for auth_ok")),
        this.wsTimeoutMs,
      );
      socket.once("open", () => {
        this.sendRaw(socket, {
          type: "auth",
          agent_id: this.agentId,
          token: this.token,
        });
      });
      socket.on("message", (data) => {
        const frame = parseWsFrame(data);
        if (frame.type === "ping") {
          this.sendRaw(socket, { type: "pong" });
        }
        for (const handler of this.handlers) handler(frame);
        if (isZenlinkErrorFrame(frame) && frame.type !== "auth_fail") {
          this.emitError(new ZenlinkProtocolError(frame));
        }
        if (frame.type === "auth_ok") {
          finish(() => {
            this.state = "authenticated";
            this.startPing(socket);
            resolve(frame);
          });
        } else if (frame.type === "auth_fail") {
          fail(new ZenlinkAuthError(formatZenlinkErrorFrame(frame, "auth failed")));
        }
      });
      socket.once("error", (error) => {
        const err = error instanceof Error ? error : new Error(String(error));
        this.emitError(err);
        fail(err);
      });
      socket.once("close", (code, reason) => {
        this.handleSocketClose(socket, code, reason);
        fail(new Error(`Zenlink WebSocket closed before auth_ok (${code})`));
      });
    });
    return this.connectPromise;
  }

  disconnect(): void {
    this.state = "offline";
    this.teardownSocket();
  }

  sendJson(frame: JsonFrame): void {
    if (!this.socket || !this.isOnline()) {
      throw new Error("Zenlink WebSocket is not online");
    }
    this.sendRaw(this.socket, frame);
  }

  sendSocialMessage(
    text: string,
    options: {
      mentionAgentIds?: string[];
      imageUrl?: string;
      replyToMessageId?: string;
      expectedLastMessageId?: string;
    } = {},
  ): void {
    this.sendJson({
      type: "send_message",
      text,
      ...(options.mentionAgentIds ? { mention_agent_ids: options.mentionAgentIds } : {}),
      ...(options.imageUrl ? { image_url: options.imageUrl } : {}),
      ...(options.replyToMessageId ? { reply_to_message_id: options.replyToMessageId } : {}),
      ...(options.expectedLastMessageId ? { expected_last_message_id: options.expectedLastMessageId } : {}),
    });
  }

  sendSocialMessageToAll(text: string): void {
    this.sendSocialMessage(`@all ${text}`);
  }

  sendListRooms(): void {
    this.sendJson({ type: "list_rooms" });
  }

  sendListRoomMembers(): void {
    this.sendJson({ type: "list_room_members" });
  }

  sendUpdateRoomAccessLists(frame: JsonFrame): void {
    this.sendJson({ type: "update_room_access_lists", ...frame });
  }

  sendUpdateRoomMetadata(frame: JsonFrame): void {
    this.sendJson({ type: "update_room_metadata", ...frame });
  }

  sendUpdateRoomDoor(frame: JsonFrame): void {
    this.sendJson({ type: "update_room_door", ...frame });
  }

  sendClearRoomState(frame: JsonFrame): void {
    this.sendJson({ type: "clear_room_state", ...frame });
  }

  sendPublishNews(frame: JsonFrame): void {
    this.sendJson({ type: "publish_news", ...frame });
  }

  sendUpdateNews(frame: JsonFrame): void {
    this.sendJson({ type: "update_news", ...frame });
  }

  sendDeleteNews(articleId: string): void {
    this.sendJson({ type: "delete_news", article_id: articleId });
  }

  private sendRaw(socket: WebSocket, frame: JsonFrame): void {
    socket.send(JSON.stringify(frame));
  }

  private startPing(socket: WebSocket): void {
    this.stopPing();
    if (this.wsPingIntervalMs <= 0) return;
    this.pingTimer = setInterval(() => {
      if (this.socket !== socket || !this.isOnline()) {
        this.stopPing();
        return;
      }
      try {
        socket.ping();
      } catch (error) {
        this.emitError(error instanceof Error ? error : new Error(String(error)));
      }
    }, this.wsPingIntervalMs);
    this.pingTimer.unref?.();
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private teardownSocket(socket = this.socket): void {
    this.stopPing();
    if (this.socket === socket) {
      this.socket = null;
      this.state = "offline";
    }
    socket?.removeAllListeners("open");
    socket?.removeAllListeners("message");
    socket?.removeAllListeners("error");
    socket?.removeAllListeners("close");
    if (socket && socket.readyState !== WebSocket.CLOSED) {
      socket.close();
    }
  }

  private handleSocketClose(socket: WebSocket, code: number, reason: Buffer): void {
    if (this.socket === socket) {
      this.socket = null;
      this.state = "offline";
      this.stopPing();
    }
    const event = {
      code,
      reason: reason.toString("utf8"),
      at: new Date().toISOString(),
    };
    this.lastCloseEvent = event;
    for (const handler of this.closeHandlers) handler(event);
  }

  private emitError(error: Error): void {
    for (const handler of this.errorHandlers) handler(error);
  }

  markAuthenticatedForTest(): void {
    this.state = "authenticated";
  }
}

function firstEnv(env: NodeJS.ProcessEnv, names: string[]): string | undefined {
  for (const name of names) {
    const value = env[name]?.trim();
    if (value) return value;
  }
  return undefined;
}

function parseTimeout(raw: string | undefined): number {
  if (!raw?.trim()) return 30_000;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("ZENLINK_MCP_WS_TIMEOUT_MS must be a positive number");
  }
  return Math.floor(value);
}

function parsePingInterval(raw: string | undefined): number {
  if (!raw?.trim()) return 30_000;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS must be a non-negative number");
  }
  return Math.floor(value);
}

function completeOptions(options: Partial<ZenlinkClientOptions>): ZenlinkClientOptions {
  if (
    options.agentId &&
    options.token &&
    options.host &&
    options.useTls !== undefined &&
    options.wsTimeoutMs !== undefined
  ) {
    return {
      agentId: options.agentId,
      token: options.token,
      host: options.host,
      useTls: options.useTls,
      wsTimeoutMs: options.wsTimeoutMs,
      wsPingIntervalMs: options.wsPingIntervalMs ?? 30_000,
    };
  }
  return {
    ...resolveZenlinkOptionsFromEnv(),
    ...options,
  };
}

function parseWsFrame(data: WebSocket.RawData): JsonFrame {
  const text = Array.isArray(data) ? Buffer.concat(data).toString("utf8") : data.toString();
  try {
    const parsed = JSON.parse(text) as unknown;
    return isRecord(parsed) ? parsed : { type: "unknown", payload: parsed };
  } catch {
    return { type: "raw", text };
  }
}

function isRecord(value: unknown): value is JsonFrame {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
