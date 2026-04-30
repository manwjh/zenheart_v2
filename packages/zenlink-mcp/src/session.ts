import {
  ZenlinkManagedConnection,
  createZenlinkManagedFromEnv,
  type ZenlinkClient,
  type AuthOkFrame,
  type JsonFrame,
} from "zenlink";
import {
  OpenClawPushNotifier,
  readOpenClawPushConfig,
  describeOpenClawPushPublic,
  type OpenClawPushRuntimeConfig,
} from "./openclaw-push.js";
import {
  ZENHEART_WORKSPACE_CONTEXT_REMINDER,
  getEffectiveSocialRules,
} from "./social-context.js";

function readWsWaitTimeoutMs(): number {
  const raw = process.env["ZENLINK_MCP_WS_TIMEOUT_MS"];
  if (raw === undefined || raw === "") {
    return 30_000;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n <= 0) {
    throw new Error(
      "ZENLINK_MCP_WS_TIMEOUT_MS must be a positive number when set",
    );
  }
  return n;
}

function readLongLivedAutostart(): boolean {
  const v = process.env["ZENLINK_MCP_LONG_LIVED"];
  if (v === undefined || v === "") {
    return true;
  }
  const lower = v.trim().toLowerCase();
  if (lower === "0" || lower === "false" || lower === "no" || lower === "off") {
    return false;
  }
  if (lower === "1" || lower === "true" || lower === "yes" || lower === "on") {
    return true;
  }
  throw new Error(
    `ZENLINK_MCP_LONG_LIVED: invalid value "${v}" (omit for default long-lived, or use 1/true / 0/false)`,
  );
}

/** Max buffered inbound WS frames for {@link ZenlinkSession.inboundPoll}. When queue is full, oldest frames are dropped. */
function readInboundQueueMax(): number {
  const raw = process.env["ZENLINK_MCP_INBOUND_QUEUE_MAX"];
  if (raw === undefined || raw === "") {
    return 500;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(
      "ZENLINK_MCP_INBOUND_QUEUE_MAX must be a non-negative integer when set",
    );
  }
  return Math.floor(n);
}

/** Outbound WS **`ping`** interval (zenlink client). `0` disables client-initiated ping (server may still ping). Default **30000** ms. */
function readClientPingIntervalMs(): number {
  const raw = process.env["ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS"];
  if (raw === undefined || raw === "") {
    return 30_000;
  }
  const n = Number(raw);
  if (!Number.isFinite(n)) {
    throw new Error(
      "ZENLINK_MCP_WS_CLIENT_PING_INTERVAL_MS must be a finite number (or omit; 0 disables)",
    );
  }
  return Math.floor(n);
}

type PendingWait = {
  accept: (f: JsonFrame) => boolean;
  resolve: (f: JsonFrame) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

/**
 * Single ZenlinkClient (via {@link ZenlinkManagedConnection}), serialized WebSocket commands,
 * and one in-flight response wait (rooms_list, room_members_list, etc.).
 *
 * Inbound frames that are not consumed by the active `wsRpc` wait (including when there is no wait)
 * are appended to an FIFO queue (bounded by {@link readInboundQueueMax}) for {@link inboundPoll}.
 *
 * After an idle disconnect, reconnect uses exponential backoff while long-lived mode is enabled.
 * Long-lived starts automatically at process startup unless **`ZENLINK_MCP_LONG_LIVED`** is set to **`0`** / **`false`** / **`off`** / **`no`**.
 * Unexpected close during an in-flight `wsRpc` rejects the wait immediately (`onClose`), instead of
 * waiting for the generic timeout.
 */
export class ZenlinkSession {
  private readonly managed: ZenlinkManagedConnection;
  readonly client: ZenlinkClient;
  private readonly openclawPush: OpenClawPushNotifier | undefined;
  private readonly openclawPushConfigSnapshot: OpenClawPushRuntimeConfig | undefined;
  private readonly wsWaitTimeoutMs: number;
  private readonly inboundQueueMax: number;
  private overflowDroppedTotal = 0;
  private inboundQueue: JsonFrame[] = [];
  private tail: Promise<unknown> = Promise.resolve();
  private pending: PendingWait | null = null;

  /**
   * Last social room id for this MCP process (successful join_room or room_created).
   * Server room membership resets on WebSocket reconnect; see {@link roomRestorePending}.
   */
  private lastSocialRoomId: string | null = null;

  /**
   * After a passive socket close while {@link lastSocialRoomId} was set, reconnect must
   * re-send join_room before send_message succeeds.
   */
  private roomRestorePending = false;

  /** Increments whenever this process receives `type: superseded` on the WS (another connection took this agent slot). */
  private wsSupersededTotal = 0;

  /**
   * After `room_joined` / `room_created` (incl. reconnect restore), from server frames; includes
   * `creator_agent_id` when the backend sends it. Cleared on leave / disconnect.
   */
  private lastRoomSnapshot: {
    room_id: string;
    name: string | null;
    creator_agent_id: string | null;
    creator_agent_name: string | null;
  } | null = null;

  /** Rooms created in this process when `room_created` was seen; used if server omits `creator_agent_id` on old builds. */
  private readonly selfCreatedRoomIds = new Set<string>();

  constructor() {
    this.wsWaitTimeoutMs = readWsWaitTimeoutMs();
    this.inboundQueueMax = readInboundQueueMax();
    const pushCfg = readOpenClawPushConfig();
    this.openclawPushConfigSnapshot = pushCfg;
    this.openclawPush = pushCfg
      ? new OpenClawPushNotifier(pushCfg)
      : undefined;
    this.managed = createZenlinkManagedFromEnv({
      pingIntervalMs: readClientPingIntervalMs(),
      onMessage: (frame) => this.onFrame(frame),
      onClose: () => {
        if (this.lastSocialRoomId !== null) {
          this.roomRestorePending = true;
        }
        this.abortPendingWait(
          new Error("zenlink-mcp: WebSocket closed before response"),
        );
      },
      onAuthFailure: (err) => {
        console.error(`zenlink-mcp: long-lived auth failed: ${err.message}`);
      },
    });
    this.client = this.managed.client;
    if (readLongLivedAutostart()) {
      this.managed.startLongLived();
    }
  }

  status(): {
    connected: boolean;
    longLived: boolean;
    agentId: string;
    host: string;
    /** This OS process id (helps correlate logs when hosts spawn multiple MCP stdio peers). */
    process_pid: number;
    /** Lifetime count of `superseded` frames for this process (strong hint of concurrent connections with same agent id). */
    ws_superseded_total: number;
    /** Tracked room for **this** Zenlink session process (join/create). Not a server-side roster query; after reconnect use `zenlink_list_room_members` / `zenlink_list_rooms_agent` if unsure. */
    current_room_id: string | null;
    room_restore_pending: boolean;
    openclaw_push: ReturnType<typeof describeOpenClawPushPublic> & {
      last_error: string | null;
      last_ok_at_ms: number | null;
    };
  } {
    const base = describeOpenClawPushPublic(this.openclawPushConfigSnapshot);
    const st = this.openclawPush?.status() ?? {
      last_error: null,
      last_ok_at_ms: null,
    };
    return {
      connected: this.client.isConnected(),
      longLived: this.managed.isLongLivedEnabled(),
      agentId: this.client.agentId,
      host: this.client.host,
      process_pid: process.pid,
      ws_superseded_total: this.wsSupersededTotal,
      current_room_id: this.lastSocialRoomId,
      room_restore_pending: this.roomRestorePending,
      openclaw_push: { ...base, ...st },
    };
  }

  startLongLived(): void {
    this.managed.startLongLived();
  }

  /**
   * Effective social guidance + `agent_id` + current room and whether this identity is the room **creator** (from last
   * `room_joined` / `room_created` in this process). Call when workspace context and ZenHeart role might be confused.
   */
  socialContext(): {
    workspace_context_reminder: string;
    social_rules: string;
    social_rules_source: ReturnType<typeof getEffectiveSocialRules>["source"];
    agent: { agent_id: string; host: string };
    room: {
      current_room_id: string;
      room_name: string | null;
      creator_agent_id: string | null;
      creator_agent_name: string | null;
      is_room_creator: boolean | null;
    } | null;
    note: string | null;
  } {
    const rules = getEffectiveSocialRules();
    const agentId = this.client.agentId;
    const roomId = this.lastSocialRoomId;
    const snap = this.lastRoomSnapshot;
    let isRoomCreator: boolean | null = null;
    if (roomId && snap?.room_id === roomId) {
      if (snap.creator_agent_id && snap.creator_agent_id.length > 0) {
        isRoomCreator = snap.creator_agent_id === agentId;
      } else if (this.selfCreatedRoomIds.has(roomId)) {
        isRoomCreator = true;
      }
    }
    const needNote =
      roomId !== null &&
      isRoomCreator === null &&
      (snap === null || snap.creator_agent_id == null);

    const parts: string[] = [];
    if (needNote) {
      parts.push(
        "is_room_creator unknown: join or create a room so room_joined/room_created can be processed; ensure ZenHeart backend exposes creator_agent_id (current servers include it).",
      );
    }
    if (rules.rules_file_missing) {
      parts.push(
        "ZENLINK_MCP_SOCIAL_RULES_FILE is set but the file is missing; effective social_rules text is env/default until created. Use zenlink_social_rules_set after enabling ZENLINK_MCP_SOCIAL_RULES_WRITE, or zenlink_social_rules_get to inspect.",
      );
    }

    return {
      workspace_context_reminder: ZENHEART_WORKSPACE_CONTEXT_REMINDER,
      social_rules: rules.text,
      social_rules_source: rules.source,
      agent: { agent_id: agentId, host: this.client.host },
      room:
        roomId === null
          ? null
          : {
              current_room_id: roomId,
              room_name: snap?.name ?? null,
              creator_agent_id: snap?.creator_agent_id ?? null,
              creator_agent_name: snap?.creator_agent_name ?? null,
              is_room_creator: isRoomCreator,
            },
      note: parts.length > 0 ? parts.join(" ") : null,
    };
  }

  private static strField(f: JsonFrame, k: string): string | undefined {
    const v = f[k];
    return typeof v === "string" ? v : undefined;
  }

  private applyRoomSnapshotFromFrame(frame: JsonFrame): void {
    const t = frame.type;
    if (t !== "room_joined" && t !== "room_created") {
      return;
    }
    const room_id = ZenlinkSession.roomIdFromFrame(frame);
    if (!room_id) {
      return;
    }
    const nameRaw = ZenlinkSession.strField(frame, "name");
    const name = nameRaw && nameRaw.length > 0 ? nameRaw : null;
    const rawCr = ZenlinkSession.strField(frame, "creator_agent_id");
    const creatorId =
      rawCr && rawCr.length > 0
        ? rawCr
        : t === "room_created"
          ? this.client.agentId
          : undefined;
    const cname = ZenlinkSession.strField(frame, "creator_agent_name");
    this.lastRoomSnapshot = {
      room_id,
      name,
      creator_agent_id: creatorId ?? null,
      creator_agent_name: cname && cname.length > 0 ? cname : null,
    };
    if (t === "room_created") {
      this.selfCreatedRoomIds.add(room_id);
    }
  }

  private clearRoomSocialState(): void {
    this.lastSocialRoomId = null;
    this.lastRoomSnapshot = null;
    this.roomRestorePending = false;
    this.selfCreatedRoomIds.clear();
  }

  private onFrame(frame: JsonFrame): void {
    const p = this.pending;
    const t = frame.type;

    if (t === "superseded") {
      this.wsSupersededTotal += 1;
    }

    if (p) {
      if (t === "error") {
        const reason =
          typeof frame["reason"] === "string" ? frame["reason"] : "error";
        const detailRaw = frame["detail"];
        const detail =
          typeof detailRaw === "string" ? `: ${detailRaw}` : "";
        this.abortPendingWait(new Error(`zenlink: ${reason}${detail}`));
        return;
      }
      if (t === "superseded") {
        this.abortPendingWait(new Error("zenlink: connection superseded"));
        return;
      }
      if (p.accept(frame)) {
        if (t === "room_joined" || t === "room_created") {
          this.applyRoomSnapshotFromFrame(frame);
        } else if (t === "room_left") {
          const rid = ZenlinkSession.roomIdFromFrame(frame);
          if (rid && rid === this.lastSocialRoomId) {
            this.clearRoomSocialState();
          }
        }
        p.resolve(frame);
        return;
      }
    }

    if (t === "room_joined" || t === "room_created") {
      this.applyRoomSnapshotFromFrame(frame);
    } else if (t === "room_left") {
      const rid = ZenlinkSession.roomIdFromFrame(frame);
      if (rid && rid === this.lastSocialRoomId) {
        this.clearRoomSocialState();
      }
    }

    this.maybeEnqueueInbound(frame);
  }

  /** Server `ping` is answered inside {@link ZenlinkClient}; omit from poll noise. */
  private shouldSkipInbound(frame: JsonFrame): boolean {
    return frame.type === "ping";
  }

  private maybeEnqueueInbound(frame: JsonFrame): void {
    if (this.inboundQueueMax === 0) {
      return;
    }
    if (this.shouldSkipInbound(frame)) {
      return;
    }
    if (this.inboundQueue.length >= this.inboundQueueMax) {
      this.inboundQueue.shift();
      this.overflowDroppedTotal += 1;
    }
    this.inboundQueue.push(frame);
    this.openclawPush?.notifyInboundQueued(frame);
  }

  /**
   * Remove up to `limit` inbound frames (oldest first). Does not reset overflow counter.
   */
  inboundPoll(limit: number): {
    frames: JsonFrame[];
    remaining: number;
    overflow_dropped_total: number;
  } {
    const cap = Math.min(Math.max(1, limit), 500);
    const frames = this.inboundQueue.splice(0, cap);
    return {
      frames,
      remaining: this.inboundQueue.length,
      overflow_dropped_total: this.overflowDroppedTotal,
    };
  }

  inboundStats(): {
    queued: number;
    overflow_dropped_total: number;
    queue_max: number;
    inbound_poll_disabled: boolean;
  } {
    return {
      queued: this.inboundQueue.length,
      overflow_dropped_total: this.overflowDroppedTotal,
      queue_max: this.inboundQueueMax,
      inbound_poll_disabled: this.inboundQueueMax === 0,
    };
  }

  private clearInboundQueue(): void {
    this.inboundQueue.length = 0;
    this.overflowDroppedTotal = 0;
  }

  private abortPendingWait(err: Error): void {
    const p = this.pending;
    if (!p) {
      return;
    }
    clearTimeout(p.timer);
    this.pending = null;
    p.reject(err);
  }

  private cancelWait(): void {
    this.abortPendingWait(
      new Error("zenlink-mcp: WebSocket response wait cancelled"),
    );
  }

  private beginWait(
    describe: string,
    accept: (f: JsonFrame) => boolean,
  ): Promise<JsonFrame> {
    if (this.pending) {
      return Promise.reject(
        new Error(
          "zenlink-mcp: overlapping WebSocket response waits (serialize tool calls)",
        ),
      );
    }
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const cur = this.pending;
        if (!cur || cur.timer !== timer) {
          return;
        }
        this.pending = null;
        cur.reject(
          new Error(
            `timeout waiting for ${describe} (${this.wsWaitTimeoutMs}ms)`,
          ),
        );
      }, this.wsWaitTimeoutMs);
      this.pending = {
        accept,
        resolve: (f) => {
          clearTimeout(timer);
          this.pending = null;
          resolve(f);
        },
        reject: (err) => {
          clearTimeout(timer);
          this.pending = null;
          reject(err);
        },
        timer,
      };
    });
  }

  private withLock<T>(fn: () => Promise<T>): Promise<T> {
    const next = this.tail.then(fn);
    this.tail = next.then(
      () => undefined,
      () => undefined,
    );
    return next;
  }

  async connect(): Promise<AuthOkFrame> {
    return this.withLock(async () => {
      this.clearInboundQueue();
      return this.managed.connect();
    });
  }

  async disconnect(): Promise<void> {
    return this.withLock(async () => {
      this.cancelWait();
      this.clearInboundQueue();
      this.clearRoomSocialState();
      this.managed.disconnect();
    });
  }

  private static roomIdFromFrame(f: JsonFrame): string | undefined {
    const id = f["room_id"];
    return typeof id === "string" ? id : undefined;
  }

  /**
   * Re-enter last social room after a passive reconnect (serialized before user WS verbs).
   */
  private async restoreRoomMembershipIfNeeded(): Promise<void> {
    if (!this.roomRestorePending || !this.lastSocialRoomId) {
      return;
    }
    const roomId = this.lastSocialRoomId;
    const waitPromise = this.beginWait(
      "frame type(s): room_joined",
      (f) =>
        typeof f.type === "string" &&
        f.type === "room_joined" &&
        (ZenlinkSession.roomIdFromFrame(f) ?? roomId) === roomId,
    );
    try {
      this.client.sendJoinRoom(roomId);
    } catch (e) {
      this.cancelWait();
      throw e instanceof Error ? e : new Error(String(e));
    }
    try {
      await waitPromise;
    } catch (e) {
      this.lastSocialRoomId = null;
      this.roomRestorePending = false;
      throw e;
    }
    this.roomRestorePending = false;
  }

  async joinRoomTool(roomId: string): Promise<JsonFrame> {
    const frame = await this.wsRpc(
      ["room_joined"],
      () => this.client.sendJoinRoom(roomId),
      { skipRoomRestore: true },
    );
    const id = ZenlinkSession.roomIdFromFrame(frame) ?? roomId;
    this.lastSocialRoomId = id;
    this.roomRestorePending = false;
    return frame;
  }

  async pullRoomTopicsTool(
    roomId: string,
    limit?: number,
  ): Promise<JsonFrame> {
    return this.wsRpc(
      ["pull_room_topics_ok"],
      () =>
        this.client.sendPullRoomTopics(roomId,
          limit !== undefined ? { limit } : {}),
      { skipRoomRestore: true },
    );
  }

  async leaveRoomTool(): Promise<JsonFrame> {
    const frame = await this.wsRpc(
      ["room_left"],
      () => this.client.sendLeaveRoom(),
      { skipRoomRestore: true },
    );
    this.clearRoomSocialState();
    return frame;
  }

  async createRoomTool(
    payload: Parameters<ZenlinkClient["sendCreateRoom"]>[0],
  ): Promise<JsonFrame> {
    const frame = await this.wsRpc(
      ["room_created"],
      () => this.client.sendCreateRoom(payload),
      { skipRoomRestore: true },
    );
    const id = ZenlinkSession.roomIdFromFrame(frame);
    if (id) {
      this.lastSocialRoomId = id;
      this.roomRestorePending = false;
    }
    return frame;
  }

  /**
   * Join a room then send a social message (two serialized WS round-trips).
   * Caller should avoid overlapping waits with other WebSocket tools.
   */
  async socialReply(roomId: string, text: string): Promise<{
    room_joined: JsonFrame;
    message_echo: JsonFrame;
  }> {
    const myId = this.client.agentId;
    const room_joined = await this.wsRpc(
      ["room_joined"],
      () => this.client.sendJoinRoom(roomId),
      { skipRoomRestore: true },
    );
    const rid = ZenlinkSession.roomIdFromFrame(room_joined) ?? roomId;
    this.lastSocialRoomId = rid;
    this.roomRestorePending = false;
    const message_echo = await this.wsRpc(
      (f) =>
        f.type === "message" &&
        f.agent_id === myId &&
        f.text === text,
      () => this.client.sendSocialMessage(text),
    );
    return { room_joined, message_echo };
  }

  /**
   * Send a WS request and wait for the first matching inbound frame (by type names),
   * or use `accept` to match (e.g. own `message` echo).
   * Server `error` / `superseded` rejects the wait immediately.
   *
   * @param skipRoomRestore - When true (join/leave/create), do not prepend automatic
   *   `join_room` after reconnect — those tools encode explicit room targets.
   */
  async wsRpc(
    expectedTypesOrAccept:
      | string[]
      | ((f: JsonFrame) => boolean),
    send: () => void,
    options?: { skipRoomRestore?: boolean },
  ): Promise<JsonFrame> {
    const describe = Array.isArray(expectedTypesOrAccept)
      ? `frame type(s): ${expectedTypesOrAccept.join(", ")}`
      : "predicate match";
    const accept = Array.isArray(expectedTypesOrAccept)
      ? (f: JsonFrame) =>
          typeof f.type === "string" &&
          expectedTypesOrAccept.includes(f.type)
      : expectedTypesOrAccept;

    return this.withLock(async () => {
      await this.managed.awaitOnline(this.wsWaitTimeoutMs);
      if (!options?.skipRoomRestore) {
        await this.restoreRoomMembershipIfNeeded();
      }
      const waitPromise = this.beginWait(describe, accept);
      try {
        send();
      } catch (e) {
        this.cancelWait();
        throw e;
      }
      return waitPromise;
    });
  }
}
