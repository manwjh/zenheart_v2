import {
  ZenlinkManagedConnection,
  createZenlinkManagedFromEnv,
  type ZenlinkClient,
  type AuthOkFrame,
  type JsonFrame,
} from "../zenlink/index.js";
import {
  OpenClawPushNotifier,
  readOpenClawPushConfig,
  describeOpenClawPushPublic,
  type OpenClawPushRuntimeConfig,
} from "../social/openclaw-push.js";
import {
  ZENHEART_WORKSPACE_CONTEXT_REMINDER,
  getEffectiveParticipantRules,
  type ParticipantRulesSource,
} from "../social/participant-rules.js";
import {
  readClientPingIntervalMs,
  readInboundDropTypes,
  readInboundQueueMax,
  readLongLivedAutostart,
  readWsWaitTimeoutMs,
} from "./session-env.js";
import {
  ZenlinkInboundFrameBuffer,
  type InboundPollResult,
  type InboundStatsResult,
} from "./session-inbound-buffer.js";

type PendingWait = {
  accept: (f: JsonFrame) => boolean;
  resolve: (f: JsonFrame) => void;
  reject: (err: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

export type ZenlinkSessionOptions = {
  onSuperseded?: (payload: { total: number }) => void;
  onRoomStateChanged?: (payload: {
    current_room_id: string | null;
    room_restore_pending: boolean;
  }) => void;
  onLifecycleLog?: (payload: { event: string; detail?: Record<string, unknown> }) => void;
};

export class ZenlinkSession {
  private readonly managed: ZenlinkManagedConnection;
  readonly client: ZenlinkClient;
  private readonly openclawPush: OpenClawPushNotifier | undefined;
  private readonly openclawPushConfigSnapshot: OpenClawPushRuntimeConfig | undefined;
  private readonly wsWaitTimeoutMs: number;
  private readonly inbound: ZenlinkInboundFrameBuffer;
  private tail: Promise<unknown> = Promise.resolve();
  private pending: PendingWait | null = null;
  private lastSocialRoomId: string | null = null;
  private roomRestorePending = false;
  private wsSupersededTotal = 0;
  private lastRoomSnapshot: {
    room_id: string;
    name: string | null;
    topic: string | null;
    rules: string | null;
    creator_agent_id: string | null;
    creator_agent_name: string | null;
  } | null = null;
  private readonly selfCreatedRoomIds = new Set<string>();
  private readonly options: ZenlinkSessionOptions;
  private roomRestoreLoopActive = false;

  constructor(options?: ZenlinkSessionOptions) {
    this.options = options ?? {};
    this.wsWaitTimeoutMs = readWsWaitTimeoutMs();
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
          this.emitRoomStateChanged();
          this.scheduleAutoRoomRestore();
        }
        this.emitLifecycleLog("ws_closed", {
          tracked_room_id: this.lastSocialRoomId,
          room_restore_pending: this.roomRestorePending,
        });
        this.abortPendingWait(
          new Error("zenlink-mcp: WebSocket closed before response"),
        );
      },
      onAuthFailure: (err) => {
        console.error(`zenlink-mcp: long-lived auth failed: ${err.message}`);
        this.emitLifecycleLog("ws_auth_failed", { message: err.message });
      },
    });
    this.client = this.managed.client;
    this.inbound = new ZenlinkInboundFrameBuffer(
      readInboundQueueMax(),
      readInboundDropTypes(),
      this.client.agentId,
    );
    if (readLongLivedAutostart()) {
      this.managed.startLongLived();
    }
  }

  status(): {
    connected: boolean;
    longLived: boolean;
    agentId: string;
    host: string;
    process_pid: number;
    ws_superseded_total: number;
    current_room_id: string | null;
    room_restore_pending: boolean;
    openclaw_push: ReturnType<typeof describeOpenClawPushPublic> &
      ReturnType<OpenClawPushNotifier["status"]>;
  } {
    const base = describeOpenClawPushPublic(this.openclawPushConfigSnapshot);
    const st = this.openclawPush?.status() ?? {
      last_error: null,
      last_ok_at_ms: null,
      last_ok_frame: null,
      last_failed_frame: null,
      sent_total_by_type: {},
      failed_total_by_type: {},
      skipped_dedupe_by_type: {},
      skipped_room_line_coalesce_by_type: {},
      skipped_frame_type_filter_by_type: {},
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

  socialGrounding(): {
    workspace_context_reminder: string;
    participant_rules: string;
    participant_rules_source: ParticipantRulesSource;
    agent: { agent_id: string; host: string };
    room: {
      room_id: string;
      name: string | null;
      topic: string | null;
      rules: string | null;
      creator_agent_id: string | null;
      creator_agent_name: string | null;
      is_room_creator: boolean | null;
    } | null;
    note: string | null;
  } {
    const pr = getEffectiveParticipantRules();
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
    if (pr.participant_rules_file_missing) {
      parts.push(
        "ZENLINK_MCP_PARTICIPANT_RULES_FILE is set but the file is missing; effective participant_rules text is env/default until created. Use zenlink_participant_rules_set after enabling ZENLINK_MCP_PARTICIPANT_RULES_WRITE, or zenlink_participant_rules_get to inspect.",
      );
    }

    return {
      workspace_context_reminder: ZENHEART_WORKSPACE_CONTEXT_REMINDER,
      participant_rules: pr.text,
      participant_rules_source: pr.source,
      agent: { agent_id: agentId, host: this.client.host },
      room:
        roomId === null
          ? null
          : {
              room_id: roomId,
              name: snap?.name ?? null,
              topic: snap?.topic ?? null,
              rules: snap?.rules ?? null,
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
    const topicRaw = ZenlinkSession.strField(frame, "topic");
    const rulesRaw = ZenlinkSession.strField(frame, "rules");
    const topic =
      topicRaw !== undefined && topicRaw.trim().length > 0 ? topicRaw : null;
    const rules =
      rulesRaw !== undefined && rulesRaw.trim().length > 0 ? rulesRaw : null;
    this.lastRoomSnapshot = {
      room_id,
      name,
      topic,
      rules,
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
    this.emitRoomStateChanged();
  }

  private onFrame(frame: JsonFrame): void {
    const p = this.pending;
    const t = frame.type;

    if (t === "superseded") {
      this.wsSupersededTotal += 1;
      this.options.onSuperseded?.({ total: this.wsSupersededTotal });
      this.emitLifecycleLog("ws_superseded", {
        total: this.wsSupersededTotal,
      });
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

    this.inbound.tryEnqueue(frame, (f) =>
      this.openclawPush?.notifyInboundQueued(f),
    );
  }

  inboundPoll(limit: number, types?: string[]): InboundPollResult {
    return this.inbound.poll(limit, types);
  }

  inboundWait(
    limit: number,
    timeoutMs: number,
    types?: string[],
  ): Promise<InboundPollResult> {
    return this.inbound.wait(limit, timeoutMs, types);
  }

  inboundStats(): InboundStatsResult {
    return this.inbound.stats();
  }

  private clearInboundQueue(): void {
    this.inbound.clear();
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
      this.emitRoomStateChanged();
      this.emitLifecycleLog("room_restore_failed", { room_id: roomId });
      throw e;
    }
    this.roomRestorePending = false;
    this.emitRoomStateChanged();
    this.emitLifecycleLog("room_restored", { room_id: roomId });
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
    this.emitRoomStateChanged();
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
      this.emitRoomStateChanged();
    }
    return frame;
  }

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
    this.emitRoomStateChanged();
    const message_echo = await this.wsRpc(
      (f) => f.type === "message" && f.agent_id === myId,
      () => this.client.sendSocialMessage(text),
    );
    return { room_joined, message_echo };
  }

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

  /**
   * Sovereign WebSocket `admin_*` request/response (level 0 on server). Skips room restore.
   */
  adminWsRpc(okType: string, frame: Record<string, unknown>): Promise<JsonFrame> {
    return this.wsRpc([okType], () => this.client.sendJson(frame as JsonFrame), {
      skipRoomRestore: true,
    });
  }

  getTrackedRoomId(): string | null {
    return this.lastSocialRoomId;
  }

  markRoomRestorePending(roomId: string): void {
    this.lastSocialRoomId = roomId;
    this.roomRestorePending = true;
    this.emitRoomStateChanged();
    this.scheduleAutoRoomRestore();
  }

  async restoreTrackedRoomMembership(): Promise<{
    restored: boolean;
    room_id: string | null;
  }> {
    return this.withLock(async () => {
      await this.managed.awaitOnline(this.wsWaitTimeoutMs);
      const before = this.roomRestorePending;
      await this.restoreRoomMembershipIfNeeded();
      return {
        restored: before && !this.roomRestorePending,
        room_id: this.lastSocialRoomId,
      };
    });
  }

  private emitRoomStateChanged(): void {
    this.options.onRoomStateChanged?.({
      current_room_id: this.lastSocialRoomId,
      room_restore_pending: this.roomRestorePending,
    });
  }

  private emitLifecycleLog(
    event: string,
    detail?: Record<string, unknown>,
  ): void {
    this.options.onLifecycleLog?.({ event, detail });
  }

  private scheduleAutoRoomRestore(): void {
    if (this.roomRestoreLoopActive) {
      return;
    }
    if (!this.roomRestorePending || !this.lastSocialRoomId) {
      return;
    }
    this.roomRestoreLoopActive = true;
    void this.runAutoRoomRestoreLoop();
  }

  private async runAutoRoomRestoreLoop(): Promise<void> {
    try {
      while (this.roomRestorePending && this.lastSocialRoomId) {
        try {
          await this.restoreTrackedRoomMembership();
          if (!this.roomRestorePending) {
            return;
          }
        } catch (e) {
          const message = e instanceof Error ? e.message : String(e);
          this.emitLifecycleLog("room_restore_retry_wait", {
            room_id: this.lastSocialRoomId,
            message,
          });
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
      }
    } finally {
      this.roomRestoreLoopActive = false;
      if (this.roomRestorePending && this.lastSocialRoomId) {
        this.scheduleAutoRoomRestore();
      }
    }
  }
}
