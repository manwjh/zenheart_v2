import type { JsonFrame } from "../zenlink/index.js";
import { senderAgentIdFromInboundFrame } from "../zenlink/index.js";

export type InboundPollResult = {
  frames: JsonFrame[];
  remaining: number;
  overflow_dropped_total: number;
  self_echo_dropped_total: number;
  type_filter_applied: string[] | null;
};

export type InboundStatsResult = {
  queued: number;
  overflow_dropped_total: number;
  self_echo_dropped_total: number;
  queue_max: number;
  inbound_poll_disabled: boolean;
};

type InboundWaiter = {
  id: number;
  cap: number;
  filterSet: Set<string> | null;
  timer: ReturnType<typeof setTimeout>;
  resolve: (value: InboundPollResult) => void;
};

/**
 * Bounded FIFO of inbound WebSocket frames consumed via zenlink_inbound_poll / zenlink_inbound_wait.
 *
 * Drops self-originated frames (`message`, `social_notify` `kind:message`) so an agent never sees its
 * own echo as a peer message. ZenHeart broadcasts every room message back to the sender, so without
 * this filter agent-to-agent loops collapse into agents replying to themselves.
 */
export class ZenlinkInboundFrameBuffer {
  private overflowDroppedTotal = 0;
  private selfEchoDroppedTotal = 0;
  private inboundQueue: JsonFrame[] = [];
  private waiters = new Map<number, InboundWaiter>();
  private nextWaiterId = 1;

  constructor(
    private readonly queueMax: number,
    private readonly dropTypes: Set<string>,
    private readonly selfAgentId: string,
  ) {}

  private shouldSkipInbound(frame: JsonFrame): boolean {
    return typeof frame.type === "string" && this.dropTypes.has(frame.type);
  }

  private isSelfEcho(frame: JsonFrame): boolean {
    const t = frame.type;
    if (t !== "message" && !(t === "social_notify" && frame.kind === "message")) {
      return false;
    }
    const sender = senderAgentIdFromInboundFrame(frame);
    return typeof sender === "string" && sender === this.selfAgentId;
  }

  private isPriorityInboundFrame(frame: JsonFrame): boolean {
    const t = frame.type;
    if (t === "message") {
      return true;
    }
    if (t === "social_notify" && frame.kind === "message") {
      return true;
    }
    if (t === "msgbox_notify") {
      return true;
    }
    if (t === "news_signal") {
      return true;
    }
    return false;
  }

  tryEnqueue(frame: JsonFrame, onQueued?: (f: JsonFrame) => void): void {
    if (this.queueMax === 0) {
      return;
    }
    if (this.shouldSkipInbound(frame)) {
      return;
    }
    if (this.isSelfEcho(frame)) {
      this.selfEchoDroppedTotal += 1;
      return;
    }
    if (this.inboundQueue.length >= this.queueMax) {
      if (this.isPriorityInboundFrame(frame)) {
        const idx = this.inboundQueue.findIndex(
          (f) => !this.isPriorityInboundFrame(f),
        );
        if (idx >= 0) {
          this.inboundQueue.splice(idx, 1);
        } else {
          this.inboundQueue.shift();
        }
      } else {
        this.inboundQueue.shift();
      }
      this.overflowDroppedTotal += 1;
    }
    this.inboundQueue.push(frame);
    onQueued?.(frame);
    this.flushWaiters();
  }

  poll(limit: number, types?: string[]): InboundPollResult {
    const cap = Math.min(Math.max(1, limit), 500);
    const filterSet =
      Array.isArray(types) && types.length > 0
        ? new Set(types.filter((t) => t.trim().length > 0))
        : null;
    const frames: JsonFrame[] = [];
    if (filterSet === null) {
      frames.push(...this.inboundQueue.splice(0, cap));
    } else {
      const keep: JsonFrame[] = [];
      for (const frame of this.inboundQueue) {
        const t = typeof frame.type === "string" ? frame.type : "";
        if (frames.length < cap && filterSet.has(t)) {
          frames.push(frame);
        } else {
          keep.push(frame);
        }
      }
      this.inboundQueue = keep;
    }
    return {
      frames,
      remaining: this.inboundQueue.length,
      overflow_dropped_total: this.overflowDroppedTotal,
      self_echo_dropped_total: this.selfEchoDroppedTotal,
      type_filter_applied: filterSet ? [...filterSet] : null,
    };
  }

  wait(limit: number, timeoutMs: number, types?: string[]): Promise<InboundPollResult> {
    const immediate = this.poll(limit, types);
    if (immediate.frames.length > 0 || timeoutMs === 0) {
      return Promise.resolve(immediate);
    }
    const cap = Math.min(Math.max(1, limit), 500);
    const filterSet =
      Array.isArray(types) && types.length > 0
        ? new Set(types.filter((t) => t.trim().length > 0))
        : null;
    return new Promise((resolve) => {
      const id = this.nextWaiterId++;
      const timer = setTimeout(() => {
        const waiter = this.waiters.get(id);
        if (!waiter) {
          return;
        }
        this.waiters.delete(id);
        resolve({
          frames: [],
          remaining: this.inboundQueue.length,
          overflow_dropped_total: this.overflowDroppedTotal,
          self_echo_dropped_total: this.selfEchoDroppedTotal,
          type_filter_applied: filterSet ? [...filterSet] : null,
        });
      }, timeoutMs);
      this.waiters.set(id, {
        id,
        cap,
        filterSet,
        timer,
        resolve,
      });
    });
  }

  private flushWaiters(): void {
    if (this.waiters.size === 0) {
      return;
    }
    const ready: InboundWaiter[] = [];
    for (const waiter of this.waiters.values()) {
      const hasMatch =
        waiter.filterSet === null
          ? this.inboundQueue.length > 0
          : this.inboundQueue.some((frame) => {
              const t = typeof frame.type === "string" ? frame.type : "";
              return waiter.filterSet?.has(t) ?? false;
            });
      if (hasMatch) {
        ready.push(waiter);
      }
    }
    for (const waiter of ready) {
      this.waiters.delete(waiter.id);
      clearTimeout(waiter.timer);
      waiter.resolve(
        this.poll(
          waiter.cap,
          waiter.filterSet ? [...waiter.filterSet] : undefined,
        ),
      );
    }
  }

  stats(): InboundStatsResult {
    return {
      queued: this.inboundQueue.length,
      overflow_dropped_total: this.overflowDroppedTotal,
      self_echo_dropped_total: this.selfEchoDroppedTotal,
      queue_max: this.queueMax,
      inbound_poll_disabled: this.queueMax === 0,
    };
  }

  clear(): void {
    this.inboundQueue.length = 0;
    this.overflowDroppedTotal = 0;
    this.selfEchoDroppedTotal = 0;
    for (const waiter of this.waiters.values()) {
      clearTimeout(waiter.timer);
      waiter.resolve({
        frames: [],
        remaining: 0,
        overflow_dropped_total: 0,
        self_echo_dropped_total: 0,
        type_filter_applied: waiter.filterSet ? [...waiter.filterSet] : null,
      });
    }
    this.waiters.clear();
  }
}
