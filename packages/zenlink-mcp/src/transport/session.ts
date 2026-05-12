import { OpenClawWakeNotifier } from "../social/openclaw-wake-notifier.js";
import { ZenlinkClient } from "../zenlink/index.js";
import { fetchSocialRoomMessages } from "../zenlink/index.js";
import type { WakeNotifierStatus } from "../social/openclaw-wake-notifier.js";
import type { WakePolicyStatus } from "../social/wake-policy.js";

type FramePredicate = string | ((frame: Record<string, unknown>) => boolean);

interface PendingWaiter {
  predicate: (frame: Record<string, unknown>) => boolean;
  resolve: (frame: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

interface PendingInboundWaiter {
  types: Set<string> | null;
  roomId?: string | null;
  resolve: (result: "frame" | "closed") => void;
  timer: NodeJS.Timeout;
}

interface InboundFilterOptions {
  roomId?: string | null;
  currentRoomOnly?: boolean;
}

interface SendMessageOptions {
  roomId?: string;
  mentionAgentIds?: string[];
  imageUrl?: string;
  replyToMessageId?: string;
  expectedLastMessageId?: string;
}

export interface ZenlinkSessionStatus {
  agent_id: string;
  online: boolean;
  current_room_id: string | null;
  room_online_assumption: "confirmed" | "restore_pending" | "unknown";
  room_confirmed_at: string | null;
  room_join_skipped_total: number;
  inbound_queue_depth: number;
  inbound_queue_max: number;
  overflow_dropped_total: number;
  self_echo_dropped_total: number;
  ws_superseded_total: number;
  connect_total: number;
  reconnect_total: number;
  ws_disconnect_total: number;
  passive_disconnect_total: number;
  connect_failure_total: number;
  wait_timeout_total: number;
  room_restore_pending: boolean;
  connection_state: string;
  last_ws_close_code: number | null;
  last_ws_close_reason: string | null;
  last_ws_close_at: string | null;
  last_ws_frame_at: string | null;
  last_inbound_enqueue_at: string | null;
  last_wait_timeout_at: string | null;
  last_backfill_at: string | null;
  last_backfill_error: string | null;
  last_inbound_dequeue_at: string | null;
  last_inbound_dequeue_count: number;
  last_inbound_dequeue_tool: string | null;
  last_msgbox_fetch_at: string | null;
  last_msgbox_fetch_count: number;
  last_msgbox_fetch_unread_count: number | null;
  last_msgbox_ack_at: string | null;
  last_msgbox_ack_count: number;
  openclaw_push: WakeNotifierStatus;
  wake_policy: WakePolicyStatus;
  process_pid: number;
}

export class ZenlinkSession {
  readonly client: ZenlinkClient;

  private readonly inboundQueue: Record<string, unknown>[] = [];
  private readonly waiters = new Set<PendingWaiter>();
  private readonly inboundWaiters = new Set<PendingInboundWaiter>();
  private readonly notifier: OpenClawWakeNotifier;
  private readonly inboundQueueMax: number;
  private readonly inboundDropTypes: Set<string>;
  private overflowDroppedTotal = 0;
  private selfEchoDroppedTotal = 0;
  private wsSupersededTotal = 0;
  private connectTotal = 0;
  private reconnectTotal = 0;
  private wsDisconnectTotal = 0;
  private passiveDisconnectTotal = 0;
  private connectFailureTotal = 0;
  private waitTimeoutTotal = 0;
  private longLived = process.env.ZENLINK_MCP_LONG_LIVED?.toLowerCase() !== "0";
  private currentRoomId: string | null = null;
  private roomConfirmedAt: string | null = null;
  private roomJoinSkippedTotal = 0;
  private roomRestorePending = false;
  private roomNeedsRestore = false;
  private started = false;
  private hasConnected = false;
  private explicitDisconnect = false;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private reconnectDelayMs = 1_000;
  private readonly reconnectMaxDelayMs = 30_000;
  private lastWsCloseCode: number | null = null;
  private lastWsCloseReason: string | null = null;
  private lastWsCloseAt: string | null = null;
  private lastWsFrameAt: string | null = null;
  private lastInboundEnqueueAt: string | null = null;
  private lastWaitTimeoutAt: string | null = null;
  private lastBackfillAt: string | null = null;
  private lastBackfillError: string | null = null;
  private lastInboundDequeueAt: string | null = null;
  private lastInboundDequeueCount = 0;
  private lastInboundDequeueTool: string | null = null;
  private lastMsgboxFetchAt: string | null = null;
  private lastMsgboxFetchCount = 0;
  private lastMsgboxFetchUnreadCount: number | null = null;
  private lastMsgboxAckAt: string | null = null;
  private lastMsgboxAckCount = 0;

  constructor(client = new ZenlinkClient(), notifier?: OpenClawWakeNotifier) {
    this.client = client;
    this.notifier =
      notifier ??
      new OpenClawWakeNotifier({
        inboundQueueDepth: () => this.inboundQueue.length,
      });
    this.inboundQueueMax = parseQueueMax();
    this.inboundDropTypes = parseInboundDropTypes();
    this.client.onMessage((frame: unknown) => this.handleFrame(frame));
    this.client.onClose((event: { code: number; reason: string; at: string }) => this.handleClientClose(event));
    this.client.onError((error: Error) => this.handleClientError(error));
    if (this.longLived) {
      queueMicrotask(() => {
        void this.startLongLived();
      });
    }
  }

  async connect(): Promise<unknown> {
    this.longLived = false;
    this.clearReconnectTimer();
    this.explicitDisconnect = false;
    this.clearInbound();
    const frame = await this.client.connect();
    this.recordConnectSuccess(frame);
    return frame;
  }

  async disconnect(): Promise<void> {
    this.longLived = false;
    this.explicitDisconnect = true;
    this.clearReconnectTimer();
    this.notifier.stop();
    this.rejectAllWaiters(new Error("Zenlink WebSocket disconnected"));
    this.resolveInboundWaiters("closed");
    this.client.disconnect();
    this.clearInbound();
    this.started = false;
    this.currentRoomId = null;
    this.roomConfirmedAt = null;
    this.roomRestorePending = false;
    this.roomNeedsRestore = false;
  }

  startLongLived(): void {
    this.longLived = true;
    if (this.started) return;
    this.started = true;
    void this.ensureOnline();
  }

  status(): ZenlinkSessionStatus {
    return {
      agent_id: this.client.agentId,
      online: this.client.isOnline(),
      current_room_id: this.currentRoomId,
      room_online_assumption: this.roomOnlineAssumption(),
      room_confirmed_at: this.roomConfirmedAt,
      room_join_skipped_total: this.roomJoinSkippedTotal,
      inbound_queue_depth: this.inboundQueue.length,
      inbound_queue_max: this.inboundQueueMax,
      overflow_dropped_total: this.overflowDroppedTotal,
      self_echo_dropped_total: this.selfEchoDroppedTotal,
      ws_superseded_total: this.wsSupersededTotal,
      connect_total: this.connectTotal,
      reconnect_total: this.reconnectTotal,
      ws_disconnect_total: this.wsDisconnectTotal,
      passive_disconnect_total: this.passiveDisconnectTotal,
      connect_failure_total: this.connectFailureTotal,
      wait_timeout_total: this.waitTimeoutTotal,
      room_restore_pending: this.roomRestorePending,
      connection_state: this.client.connectionState(),
      last_ws_close_code: this.lastWsCloseCode,
      last_ws_close_reason: this.lastWsCloseReason,
      last_ws_close_at: this.lastWsCloseAt,
      last_ws_frame_at: this.lastWsFrameAt,
      last_inbound_enqueue_at: this.lastInboundEnqueueAt,
      last_wait_timeout_at: this.lastWaitTimeoutAt,
      last_backfill_at: this.lastBackfillAt,
      last_backfill_error: this.lastBackfillError,
      last_inbound_dequeue_at: this.lastInboundDequeueAt,
      last_inbound_dequeue_count: this.lastInboundDequeueCount,
      last_inbound_dequeue_tool: this.lastInboundDequeueTool,
      last_msgbox_fetch_at: this.lastMsgboxFetchAt,
      last_msgbox_fetch_count: this.lastMsgboxFetchCount,
      last_msgbox_fetch_unread_count: this.lastMsgboxFetchUnreadCount,
      last_msgbox_ack_at: this.lastMsgboxAckAt,
      last_msgbox_ack_count: this.lastMsgboxAckCount,
      openclaw_push: this.notifier.status(),
      wake_policy: this.notifier.wakePolicyStatus(),
      process_pid: process.pid,
    };
  }

  wakePolicyStatus(): WakePolicyStatus {
    return this.notifier.wakePolicyStatus();
  }

  setWakePolicyAllowlist(signals: string[]): WakePolicyStatus {
    return this.notifier.setWakePolicyAllowlist(signals);
  }

  resetWakePolicy(): WakePolicyStatus {
    return this.notifier.resetWakePolicy();
  }

  socialGrounding(): Record<string, unknown> {
    return {
      agent_id: this.client.agentId,
      current_room_id: this.currentRoomId,
    };
  }

  inboundStats(): Record<string, unknown> {
    return {
      depth: this.inboundQueue.length,
      max: this.inboundQueueMax,
      overflow_dropped_total: this.overflowDroppedTotal,
      self_echo_dropped_total: this.selfEchoDroppedTotal,
    };
  }

  inboundDepthFor(types?: string[], filter: InboundFilterOptions = {}): Record<string, unknown> {
    const roomId = this.resolveInboundRoomFilter(filter);
    return {
      raw_depth: this.inboundQueue.length,
      matching_depth: this.countMatchingInbound(types, roomId),
      room_filter: roomId,
    };
  }

  inboundPoll(
    limit: number,
    types?: string[],
    tool = "zenlink_inbound_poll",
    filter: InboundFilterOptions = {},
  ): Record<string, unknown> {
    const roomId = this.resolveInboundRoomFilter(filter);
    const frames = this.dequeue(limit, types, roomId);
    this.recordInboundDequeue(tool, frames.length);
    return {
      ok: true,
      frames,
      room_filter: roomId,
      stats: this.inboundStats(),
    };
  }

  async inboundWait(
    limit: number,
    timeoutMs: number,
    types?: string[],
    options: { backfillOnTimeout?: boolean; tool?: string } & InboundFilterOptions = {},
  ): Promise<Record<string, unknown>> {
    const tool = options.tool ?? "zenlink_inbound_wait";
    const roomId = this.resolveInboundRoomFilter(options);
    const immediate = this.dequeue(limit, types, roomId);
    if (immediate.length || timeoutMs === 0) {
      this.recordInboundDequeue(tool, immediate.length);
      return {
        ok: true,
        source: immediate.length ? "inbound_fifo" : "timeout",
        frames: immediate,
        room_filter: roomId,
        stats: this.inboundStats(),
      };
    }
    if (!this.client.isOnline()) {
      await this.ensureOnline();
    }
    const waitResult = await this.waitForInbound(types, timeoutMs, roomId);
    if (waitResult === "closed") {
      return {
        ok: false,
        source: "ws_closed",
        reason: "ws_disconnected",
        frames: [],
        stats: this.inboundStats(),
      };
    }
    if (waitResult === "timeout") {
      this.waitTimeoutTotal++;
      this.lastWaitTimeoutAt = new Date().toISOString();
      const frames = this.dequeue(limit, types, roomId);
      this.recordInboundDequeue(tool, frames.length);
      const backfill =
        frames.length === 0 && this.shouldBackfillOnTimeout(options)
          ? await this.backfillRoom(roomId ?? this.currentRoomId, limit)
          : null;
      return {
        ok: true,
        source: frames.length ? "inbound_fifo" : backfill ? "http_backfill" : "timeout",
        reason: frames.length ? undefined : "ws_wait_timeout",
        frames,
        room_filter: roomId,
        ...(backfill ? { backfill } : {}),
        stats: this.inboundStats(),
      };
    }
    return {
      ok: true,
      source: "inbound_fifo",
      frames: this.recordAndReturnDequeue(tool, limit, types, roomId),
      room_filter: roomId,
      stats: this.inboundStats(),
    };
  }

  recordMsgboxFetch(count: number, unreadCount?: number | null): void {
    this.lastMsgboxFetchAt = new Date().toISOString();
    this.lastMsgboxFetchCount = count;
    this.lastMsgboxFetchUnreadCount = unreadCount ?? null;
  }

  recordMsgboxAck(count: number): void {
    this.lastMsgboxAckAt = new Date().toISOString();
    this.lastMsgboxAckCount = count;
  }

  async joinRoomTool(roomId: string): Promise<Record<string, unknown>> {
    const frame = await this.wsRpc((candidate) => isJoinRoomSuccess(candidate, roomId), () => {
      this.client.sendJson({ type: "join_room", room_id: roomId });
    }, { skipRoomRestore: true });
    this.currentRoomId = roomId;
    this.roomConfirmedAt = new Date().toISOString();
    this.roomNeedsRestore = false;
    return normalizeJoinRoomSuccess(frame, roomId);
  }

  async leaveRoomTool(): Promise<Record<string, unknown>> {
    const frame = await this.wsRpc(["room_left"], () => {
      this.client.sendJson({ type: "leave_room" });
    });
    this.currentRoomId = null;
    this.roomConfirmedAt = null;
    this.roomNeedsRestore = false;
    return frame;
  }

  async createRoomTool(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    const frame = await this.wsRpc(["room_created"], () => {
      this.client.sendJson({ type: "create_room", ...payload });
    });
    if (typeof frame.room_id === "string") this.currentRoomId = frame.room_id;
    if (typeof frame.room_id === "string") this.roomConfirmedAt = new Date().toISOString();
    this.roomNeedsRestore = false;
    return frame;
  }

  async pullRoomTopicsTool(roomId: string, limit?: number): Promise<Record<string, unknown>> {
    return this.wsRpc(["pull_room_topics_ok"], () => {
      this.client.sendJson({ type: "pull_room_topics", room_id: roomId, ...(limit !== undefined ? { limit } : {}) });
    });
  }

  async updateRoomMetadataTool(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    const roomId = typeof payload.room_id === "string" ? payload.room_id : null;
    return this.wsRpc((frame) => (
      frame.type === "room_metadata_updated" &&
      (roomId === null || frame.room_id === roomId)
    ), () => {
      this.client.sendUpdateRoomMetadata(payload);
    });
  }

  async socialReply(roomId: string, text: string): Promise<Record<string, unknown>> {
    const roomJoined = await this.ensureRoomReady(roomId);
    const messageEcho = await this.sendMessageTool(text);
    return {
      room_joined: roomJoined,
      message_echo: messageEcho,
    };
  }

  async sendMessageTool(text: string, options: SendMessageOptions = {}): Promise<Record<string, unknown>> {
    if (options.roomId) {
      await this.ensureRoomReady(options.roomId);
    }
    const targetRoomId = options.roomId ?? this.currentRoomId;
    return this.wsRpc(
      (frame) =>
        frame.type === "message" &&
        frame.agent_id === this.client.agentId &&
        (targetRoomId === null || frame.room_id === targetRoomId),
      () =>
        this.client.sendSocialMessage(text, {
          mentionAgentIds: options.mentionAgentIds,
          imageUrl: options.imageUrl,
          replyToMessageId: options.replyToMessageId,
          expectedLastMessageId: options.expectedLastMessageId,
        }),
    );
  }

  async adminWsRpc(okType: string, frame: Record<string, unknown>): Promise<Record<string, unknown>> {
    return this.wsRpc([okType], () => this.client.sendJson(frame), { skipRoomRestore: true });
  }

  async wsRpc(
    predicates: FramePredicate | FramePredicate[],
    send: () => void,
    options: { skipRoomRestore?: boolean } = {},
  ): Promise<Record<string, unknown>> {
    await this.ensureOnline();
    if (!options.skipRoomRestore) {
      await this.restoreRoomIfNeeded();
    }
    const predicate = normalizePredicates(predicates);
    const waiter = this.createWaiter(predicate);
    try {
      send();
      return await waiter.promise;
    } catch (error) {
      this.waiters.delete(waiter.entry);
      throw error;
    }
  }

  injectInboundForTest(frame: Record<string, unknown>): void {
    this.handleFrame(frame);
  }

  private async ensureOnline(): Promise<void> {
    if (this.client.isOnline()) return;
    try {
      const frame = await this.client.connect();
      this.recordConnectSuccess(frame);
    } catch (error) {
      this.started = false;
      this.connectFailureTotal++;
      this.wsDisconnectTotal++;
      if (this.longLived) {
        this.scheduleReconnect();
      }
      throw error;
    }
  }

  private recordConnectSuccess(frame: unknown): void {
    if (isRecord(frame) && frame.type === "already_online") return;
    this.connectTotal++;
    if (this.hasConnected) {
      this.reconnectTotal++;
    }
    this.hasConnected = true;
    this.started = true;
    this.reconnectDelayMs = 1_000;
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || !this.longLived) return;
    const delayMs = this.reconnectDelayMs;
    this.reconnectDelayMs = Math.min(this.reconnectMaxDelayMs, delayMs * 2);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.started = false;
      this.startLongLived();
    }, delayMs);
    this.reconnectTimer.unref?.();
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private handleClientClose(event: { code: number; reason: string; at: string }): void {
    this.lastWsCloseCode = event.code;
    this.lastWsCloseReason = event.reason;
    this.lastWsCloseAt = event.at;
    this.started = false;
    this.wsDisconnectTotal++;
    this.rejectAllWaiters(new Error(`Zenlink WebSocket closed (${event.code})`));
    this.resolveInboundWaiters("closed");
    if (this.explicitDisconnect) {
      this.explicitDisconnect = false;
      return;
    }
    this.passiveDisconnectTotal++;
    if (this.currentRoomId) {
      this.roomNeedsRestore = true;
    }
    if (this.longLived) {
      this.scheduleReconnect();
    }
  }

  private handleClientError(error: Error): void {
    emitSessionEvent("ws_error", { error: error.message });
  }

  private rejectAllWaiters(error: Error): void {
    for (const waiter of [...this.waiters]) {
      clearTimeout(waiter.timer);
      this.waiters.delete(waiter);
      waiter.reject(error);
    }
  }

  private resolveInboundWaiters(result: "frame" | "closed"): void {
    for (const waiter of [...this.inboundWaiters]) {
      clearTimeout(waiter.timer);
      this.inboundWaiters.delete(waiter);
      waiter.resolve(result);
    }
  }

  private async restoreRoomIfNeeded(): Promise<void> {
    if (!this.currentRoomId || !this.roomNeedsRestore || this.roomRestorePending) return;
    if (!this.client.isOnline()) return;
    this.roomRestorePending = true;
    const roomId = this.currentRoomId;
    try {
      const frame = await this.wsRpc(
        (frame) => isJoinRoomSuccess(frame, roomId),
        () => this.client.sendJson({ type: "join_room", room_id: roomId }),
        { skipRoomRestore: true },
      );
      assertRestoredRoomMembership(frame, roomId, this.client.agentId);
      this.roomConfirmedAt = new Date().toISOString();
      this.roomNeedsRestore = false;
    } finally {
      this.roomRestorePending = false;
    }
  }

  private async ensureRoomReady(roomId: string): Promise<Record<string, unknown>> {
    if (this.canTrustCurrentRoom(roomId)) {
      this.roomJoinSkippedTotal++;
      return {
        ok: true,
        type: "room_joined",
        room_id: roomId,
        already_in_room: true,
        trusted_local_state: true,
        room_confirmed_at: this.roomConfirmedAt,
      };
    }
    return this.joinRoomTool(roomId);
  }

  private canTrustCurrentRoom(roomId: string): boolean {
    return (
      this.client.isOnline() &&
      this.currentRoomId === roomId &&
      this.roomConfirmedAt !== null &&
      !this.roomNeedsRestore &&
      !this.roomRestorePending
    );
  }

  private roomOnlineAssumption(): "confirmed" | "restore_pending" | "unknown" {
    if (!this.currentRoomId || !this.roomConfirmedAt) return "unknown";
    if (!this.client.isOnline() || this.roomNeedsRestore || this.roomRestorePending) {
      return "restore_pending";
    }
    return "confirmed";
  }

  private createWaiter(predicate: (frame: Record<string, unknown>) => boolean): {
    promise: Promise<Record<string, unknown>>;
    entry: PendingWaiter;
  } {
    let entry: PendingWaiter;
    const promise = new Promise<Record<string, unknown>>((resolve, reject) => {
      entry = {
        predicate,
        resolve,
        reject,
        timer: setTimeout(() => {
          this.waiters.delete(entry);
          reject(new Error("timeout waiting for ZenHeart frame"));
        }, this.client.wsTimeoutMs),
      };
      this.waiters.add(entry);
    });
    return { promise, entry: entry! };
  }

  private handleFrame(frame: unknown): void {
    if (!isRecord(frame)) return;
    this.lastWsFrameAt = new Date().toISOString();
    emitSessionEvent("inbound_received", {
      frame_type: typeof frame.type === "string" ? frame.type : "unknown",
      queue_depth: this.inboundQueue.length,
    });
    if (frame.type === "error" && frame.reason === "superseded") {
      this.wsSupersededTotal++;
    }
    if (frame.type === "room_door_closed" && frame.room_id === this.currentRoomId) {
      this.currentRoomId = null;
      this.roomConfirmedAt = null;
      this.roomNeedsRestore = false;
      this.roomRestorePending = false;
    }

    for (const waiter of this.waiters) {
      if (waiter.predicate(frame)) {
        clearTimeout(waiter.timer);
        this.waiters.delete(waiter);
        waiter.resolve(frame);
        return;
      }
    }

    if (this.dropSelfEcho(frame)) return;

    if (this.shouldDropInbound(frame)) return;
    this.enqueueInbound(frame);
    this.notifyInboundWaiters(frame);
    void this.notifier.enqueue(frame);
  }

  private dropSelfEcho(frame: Record<string, unknown>): boolean {
    const isMessage = frame.type === "message";
    const isNotifyMessage = frame.type === "social_notify" && frame.kind === "message";
    if ((isMessage || isNotifyMessage) && senderAgentIdOf(frame) === this.client.agentId) {
      this.selfEchoDroppedTotal++;
      return true;
    }
    return false;
  }

  private enqueueInbound(frame: Record<string, unknown>): void {
    if (this.inboundQueueMax === 0) return;
    this.coalesceInboundSnapshot(frame);
    if (this.inboundQueue.length >= this.inboundQueueMax) {
      const dropIndex = this.inboundQueue.findIndex(
        (queuedFrame) => !isRetainedMessageFrame(queuedFrame),
      );
      this.inboundQueue.splice(dropIndex >= 0 ? dropIndex : 0, 1);
      this.overflowDroppedTotal++;
    }
    this.inboundQueue.push(frame);
    this.lastInboundEnqueueAt = new Date().toISOString();
  }

  private coalesceInboundSnapshot(frame: Record<string, unknown>): void {
    if (frame.type !== "topic_suggestions_pending" || typeof frame.room_id !== "string") return;
    for (let i = this.inboundQueue.length - 1; i >= 0; i -= 1) {
      const queuedFrame = this.inboundQueue[i];
      if (
        queuedFrame?.type === "topic_suggestions_pending" &&
        queuedFrame.room_id === frame.room_id
      ) {
        this.inboundQueue.splice(i, 1);
      }
    }
  }

  private shouldDropInbound(frame: Record<string, unknown>): boolean {
    const type = typeof frame.type === "string" ? frame.type : "unknown";
    return this.inboundDropTypes.has(type);
  }

  private dequeue(limit: number, types?: string[], roomId?: string | null): Record<string, unknown>[] {
    const wanted = types ? new Set(types) : null;
    const out: Record<string, unknown>[] = [];
    for (let i = 0; i < this.inboundQueue.length && out.length < limit; ) {
      const frame = this.inboundQueue[i];
      if (!frame) break;
      if (matchesInboundFrame(frame, wanted, roomId)) {
        out.push(frame);
        this.inboundQueue.splice(i, 1);
      } else {
        i++;
      }
    }
    return out;
  }

  private countMatchingInbound(types?: string[], roomId?: string | null): number {
    const wanted = types ? new Set(types) : null;
    let count = 0;
    for (const frame of this.inboundQueue) {
      if (matchesInboundFrame(frame, wanted, roomId)) count++;
    }
    return count;
  }

  private recordAndReturnDequeue(
    tool: string,
    limit: number,
    types?: string[],
    roomId?: string | null,
  ): Record<string, unknown>[] {
    const frames = this.dequeue(limit, types, roomId);
    this.recordInboundDequeue(tool, frames.length);
    return frames;
  }

  private recordInboundDequeue(tool: string, count: number): void {
    this.lastInboundDequeueAt = new Date().toISOString();
    this.lastInboundDequeueCount = count;
    this.lastInboundDequeueTool = tool;
  }

  private clearInbound(): void {
    this.inboundQueue.length = 0;
    this.overflowDroppedTotal = 0;
  }

  private waitForInbound(
    types: string[] | undefined,
    timeoutMs: number,
    roomId?: string | null,
  ): Promise<"frame" | "timeout" | "closed"> {
    return new Promise((resolve) => {
      const waiter: PendingInboundWaiter = {
        types: types ? new Set(types) : null,
        roomId,
        resolve: (result) => {
          clearTimeout(waiter.timer);
          this.inboundWaiters.delete(waiter);
          resolve(result);
        },
        timer: setTimeout(() => {
          this.inboundWaiters.delete(waiter);
          resolve("timeout");
        }, timeoutMs),
      };
      this.inboundWaiters.add(waiter);
    });
  }

  private notifyInboundWaiters(frame: Record<string, unknown>): void {
    const type = typeof frame.type === "string" ? frame.type : "unknown";
    for (const waiter of [...this.inboundWaiters]) {
      if ((!waiter.types || waiter.types.has(type)) && matchesRoomFilter(frame, waiter.roomId)) {
        waiter.resolve("frame");
      }
    }
  }

  private shouldBackfillOnTimeout(options: { backfillOnTimeout?: boolean }): boolean {
    if (options.backfillOnTimeout !== undefined) return options.backfillOnTimeout;
    const raw = process.env.ZENLINK_MCP_INBOUND_BACKFILL_ON_TIMEOUT?.trim().toLowerCase();
    if (!raw) return true;
    return !(raw === "0" || raw === "false" || raw === "no" || raw === "off");
  }

  private async backfillRoom(roomId: string | null, limit: number): Promise<Record<string, unknown> | null> {
    if (!roomId) return null;
    try {
      const result = await fetchSocialRoomMessages(
        this.client.httpOptions(),
        roomId,
        { limit },
      );
      this.lastBackfillAt = new Date().toISOString();
      this.lastBackfillError = null;
      return {
        source: "http_backfill",
        reason: "ws_wait_timeout",
        room_id: roomId,
        result,
      };
    } catch (error) {
      this.lastBackfillAt = new Date().toISOString();
      this.lastBackfillError = error instanceof Error ? error.message : String(error);
      return {
        source: "http_backfill",
        reason: "ws_wait_timeout",
        room_id: roomId,
        error: this.lastBackfillError,
      };
    }
  }

  private resolveInboundRoomFilter(options: InboundFilterOptions): string | null | undefined {
    if (options.roomId) return options.roomId;
    if (options.currentRoomOnly) return this.currentRoomId;
    return undefined;
  }
}

function parseQueueMax(): number {
  const raw = process.env.ZENLINK_MCP_INBOUND_QUEUE_MAX?.trim();
  if (!raw) return 500;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 0) {
    throw new Error("ZENLINK_MCP_INBOUND_QUEUE_MAX must be a non-negative integer");
  }
  return value;
}

function parseInboundDropTypes(): Set<string> {
  const raw = process.env.ZENLINK_MCP_INBOUND_DROP_TYPES?.trim();
  const values = raw ? raw.split(",") : ["ping", "pong"];
  return new Set(
    values
      .map((value) => value.trim())
      .filter((value) => value.length > 0),
  );
}

function normalizePredicates(predicates: FramePredicate | FramePredicate[]): (frame: Record<string, unknown>) => boolean {
  const list = Array.isArray(predicates) ? predicates : [predicates];
  return (frame) =>
    list.some((predicate) => {
      if (typeof predicate === "string") return frame.type === predicate;
      return predicate(frame);
    });
}

function isJoinRoomSuccess(frame: Record<string, unknown>, roomId: string): boolean {
  if (frame.type === "room_joined") {
    return frame.room_id === roomId;
  }
  if (frame.type !== "error" || frame.reason !== "already_in_room") {
    return false;
  }
  return frame.room_id === roomId;
}

function normalizeJoinRoomSuccess(frame: Record<string, unknown>, roomId: string): Record<string, unknown> {
  if (frame.type !== "error" || frame.reason !== "already_in_room") {
    return frame;
  }
  return {
    ok: true,
    type: "room_joined",
    room_id: roomId,
    already_in_room: true,
    server_frame: frame,
  };
}

function assertRestoredRoomMembership(frame: Record<string, unknown>, roomId: string, agentId: string): void {
  if (frame.type !== "room_joined") {
    throw new Error(`restore join_room returned ${String(frame.type)} instead of room_joined`);
  }
  if (frame.room_id !== roomId) {
    throw new Error(`restore join_room confirmed unexpected room_id: ${String(frame.room_id)}`);
  }
  if (!Array.isArray(frame.members)) {
    throw new Error("restore join_room did not include live room members");
  }
  const hasSelf = frame.members.some(
    (member) => isRecord(member) && member.agent_id === agentId,
  );
  if (!hasSelf) {
    throw new Error(`restore join_room members did not include agent_id ${agentId}`);
  }
}

function matchesRoomFilter(frame: Record<string, unknown>, roomId?: string | null): boolean {
  if (roomId === undefined) return true;
  if (roomId === null) return false;
  return frame.room_id === roomId;
}

function matchesInboundFrame(
  frame: Record<string, unknown>,
  wanted: Set<string> | null,
  roomId?: string | null,
): boolean {
  const type = typeof frame.type === "string" ? frame.type : "unknown";
  return (!wanted || wanted.has(type)) && matchesRoomFilter(frame, roomId);
}

function senderAgentIdOf(frame: Record<string, unknown>): string | null {
  if (typeof frame.agent_id === "string") return frame.agent_id;
  if (typeof frame.sender_agent_id === "string") return frame.sender_agent_id;
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRetainedMessageFrame(frame: Record<string, unknown>): boolean {
  return (
    frame.type === "message" ||
    frame.type === "msgbox_notify" ||
    (frame.type === "social_notify" && frame.kind === "message")
  );
}

function emitSessionEvent(event: string, fields: Record<string, unknown>): void {
  console.error(JSON.stringify({ component: "zenlink_session", event, ...fields }));
}
