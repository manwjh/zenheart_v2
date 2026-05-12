import { formatZenlinkHttpErrorBody } from "../zenlink/errors.js";
import { WakePolicy, frameTypeOf, parseSignalList, signalOf } from "./wake-policy.js";
import type { WakePolicyStatus } from "./wake-policy.js";

export interface WakeNotifierStatus {
  enabled: boolean;
  hook_base: string | null;
  delivery_mode: string;
  wake_mode: string;
  openclaw_agent_id: string | null;
  session_key: string | null;
  pending_wake_count: number;
  dropped_wake_count: number;
  retry_count: number;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_http_status: number | null;
  sent_total: number;
  sent_total_by_type: Record<string, number>;
  sent_total_by_signal: Record<string, number>;
  skipped_frame_type_filter_by_type: Record<string, number>;
  skipped_signal_policy_by_signal: Record<string, number>;
  skipped_dedupe_by_type: Record<string, number>;
  skipped_room_line_coalesce_by_type: Record<string, number>;
  wake_policy: WakePolicyStatus;
  last_ok_frame: unknown | null;
  last_failed_frame: unknown | null;
}

export interface WakeNotifierOptions {
  hookBase?: string;
  hookToken?: string;
  wakeMode?: string;
  openClawAgentId?: string;
  sessionKey?: string;
  frameTypes?: string[];
  wakeSignals?: string[];
  wakePolicy?: WakePolicy;
  dedupeMs?: number;
  roomLineCoalesceMs?: number;
  maxPending?: number;
  retryBaseMs?: number;
  inboundQueueDepth?: () => number;
  fetchImpl?: typeof fetch;
}

interface PendingWake {
  frame: unknown;
  frameType: string;
  signal: string;
  text: string;
  attempt: number;
}

const DEFAULT_WAKE_MODE = "now";
const DEFAULT_OPENCLAW_AGENT_ID = "main";
const DEFAULT_DEDUPE_MS = 1_000;
const DEFAULT_ROOM_LINE_COALESCE_MS = 2_000;
const DEFAULT_MAX_PENDING = 128;
const DEFAULT_RETRY_BASE_MS = 1_000;
const WAKE_ACTION_PREFIX =
  "[ZenHeart inbound] Action required: call zenlink_wake_drain before replying. Wake text is a summary, not the full payload.";
const WAKE_DRAIN_EXAMPLE =
  'Required tool call: zenlink_wake_drain({"timeout_ms":1000,"limit":32,"inbox_limit":10}). If remaining_inbound_queue_depth is greater than 0, call it again before replying.';

export class OpenClawWakeNotifier {
  private readonly hookBase: string;
  private readonly hookToken: string;
  private readonly wakeMode: string;
  private readonly openClawAgentId: string;
  private readonly sessionKey: string;
  private readonly frameTypes: Set<string> | null;
  private readonly wakePolicy: WakePolicy;
  private readonly dedupeMs: number;
  private readonly roomLineCoalesceMs: number;
  private readonly maxPending: number;
  private readonly retryBaseMs: number;
  private readonly inboundQueueDepth: (() => number) | null;
  private readonly fetchImpl: typeof fetch;
  private readonly pending: PendingWake[] = [];
  private readonly sentTotalByType: Record<string, number> = {};
  private readonly sentTotalBySignal: Record<string, number> = {};
  private readonly skippedFrameTypeByType: Record<string, number> = {};
  private readonly skippedSignalPolicyBySignal: Record<string, number> = {};
  private readonly skippedDedupeByType: Record<string, number> = {};
  private readonly skippedRoomLineByType: Record<string, number> = {};
  private readonly recentKeys = new Map<string, number>();
  private retryTimer: NodeJS.Timeout | null = null;
  private flushing = false;
  private droppedWakeCount = 0;
  private retryCount = 0;
  private lastAttemptAt: string | null = null;
  private lastSuccessAt: string | null = null;
  private lastError: string | null = null;
  private lastHttpStatus: number | null = null;
  private sentTotal = 0;
  private lastOkFrame: unknown | null = null;
  private lastFailedFrame: unknown | null = null;

  constructor(options: WakeNotifierOptions = {}) {
    this.hookBase = options.hookBase ?? process.env.ZENLINK_MCP_OPENCLAW_HOOK_BASE?.trim() ?? "";
    this.hookToken = options.hookToken ?? process.env.ZENLINK_MCP_OPENCLAW_HOOK_TOKEN?.trim() ?? "";
    this.wakeMode = options.wakeMode ?? process.env.ZENLINK_MCP_OPENCLAW_WAKE_MODE?.trim() ?? DEFAULT_WAKE_MODE;
    this.openClawAgentId =
      options.openClawAgentId ?? process.env.ZENLINK_MCP_OPENCLAW_AGENT_ID?.trim() ?? DEFAULT_OPENCLAW_AGENT_ID;
    this.sessionKey = options.sessionKey ?? process.env.ZENLINK_MCP_OPENCLAW_SESSION_KEY?.trim() ?? "";
    this.frameTypes = resolveFrameTypes(options.frameTypes);
    this.wakePolicy =
      options.wakePolicy ??
      new WakePolicy({
        wakeSignals: options.wakeSignals ?? parseSignalList(process.env.ZENLINK_MCP_WAKE_SIGNALS),
        updatedBy: options.wakeSignals
          ? "options"
          : process.env.ZENLINK_MCP_WAKE_SIGNALS?.trim()
            ? "startup_env"
            : "reset",
      });
    this.dedupeMs = options.dedupeMs ?? parseEnvInt("ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS", DEFAULT_DEDUPE_MS);
    this.roomLineCoalesceMs = options.roomLineCoalesceMs ?? parseEnvInt("ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS", DEFAULT_ROOM_LINE_COALESCE_MS);
    this.maxPending = options.maxPending ?? parseEnvInt("ZENLINK_MCP_OPENCLAW_WAKE_MAX_PENDING", DEFAULT_MAX_PENDING);
    this.retryBaseMs = options.retryBaseMs ?? parseEnvInt("ZENLINK_MCP_OPENCLAW_WAKE_RETRY_BASE_MS", DEFAULT_RETRY_BASE_MS);
    this.inboundQueueDepth = options.inboundQueueDepth ?? null;
    this.fetchImpl = options.fetchImpl ?? fetch;
  }

  get enabled(): boolean {
    return Boolean(this.hookBase && this.hookToken);
  }

  status(): WakeNotifierStatus {
    return {
      enabled: this.enabled,
      hook_base: this.hookBase || null,
      delivery_mode: "agent",
      wake_mode: this.wakeMode,
      openclaw_agent_id: this.openClawAgentId || null,
      session_key: this.sessionKey || null,
      pending_wake_count: this.pending.length,
      dropped_wake_count: this.droppedWakeCount,
      retry_count: this.retryCount,
      last_attempt_at: this.lastAttemptAt,
      last_success_at: this.lastSuccessAt,
      last_error: this.lastError,
      last_http_status: this.lastHttpStatus,
      sent_total: this.sentTotal,
      sent_total_by_type: { ...this.sentTotalByType },
      sent_total_by_signal: { ...this.sentTotalBySignal },
      skipped_frame_type_filter_by_type: { ...this.skippedFrameTypeByType },
      skipped_signal_policy_by_signal: { ...this.skippedSignalPolicyBySignal },
      skipped_dedupe_by_type: { ...this.skippedDedupeByType },
      skipped_room_line_coalesce_by_type: { ...this.skippedRoomLineByType },
      wake_policy: this.wakePolicy.status(),
      last_ok_frame: this.lastOkFrame,
      last_failed_frame: this.lastFailedFrame,
    };
  }

  wakePolicyStatus(): WakePolicyStatus {
    return this.wakePolicy.status();
  }

  setWakePolicyAllowlist(signals: string[]): WakePolicyStatus {
    return this.wakePolicy.setAllowlist(signals, "mcp");
  }

  resetWakePolicy(): WakePolicyStatus {
    return this.wakePolicy.reset("reset");
  }

  async enqueue(frame: unknown): Promise<void> {
    if (!this.enabled) return;
    const frameType = frameTypeOf(frame);
    if (this.frameTypes && !this.frameTypes.has(frameType)) {
      increment(this.skippedFrameTypeByType, frameType);
      return;
    }
    const signal = signalOf(frame);
    if (!this.shouldWakeSignal(signal)) {
      increment(this.skippedSignalPolicyBySignal, signal);
      return;
    }
    const key = wakeDedupeKey(frame);
    const now = Date.now();
    this.pruneRecent(now);
    const recent = this.recentKeys.get(key);
    if (recent !== undefined && now - recent <= this.dedupeWindowFor(frame)) {
      if (isRoomLineFrame(frame)) {
        increment(this.skippedRoomLineByType, frameType);
      } else {
        increment(this.skippedDedupeByType, frameType);
      }
      return;
    }
    this.recentKeys.set(key, now);
    if (this.pending.length >= this.maxPending) {
      this.pending.shift();
      this.droppedWakeCount++;
    }
    this.pending.push({
      frame,
      frameType,
      signal,
      text: summarizeWakeFrame(frame, this.safeInboundQueueDepth()),
      attempt: 0,
    });
    emitWakeEvent("wake_enqueued", { frame_type: frameType, signal, pending_wake_count: this.pending.length });
    await this.flush();
  }

  async flush(): Promise<void> {
    if (this.flushing || !this.enabled) return;
    this.flushing = true;
    try {
      while (this.pending.length) {
        const current = this.pending[0];
        if (!current) return;
        try {
          await this.postWake(current);
          this.pending.shift();
          this.lastSuccessAt = new Date().toISOString();
          this.lastError = null;
          this.sentTotal++;
          this.lastOkFrame = current.frame;
          increment(this.sentTotalByType, current.frameType);
          increment(this.sentTotalBySignal, current.signal);
          emitWakeEvent("wake_post_ok", {
            frame_type: current.frameType,
            signal: current.signal,
            http_status: this.lastHttpStatus,
            pending_wake_count: this.pending.length,
          });
        } catch (error) {
          current.attempt++;
          this.retryCount++;
          this.lastFailedFrame = current.frame;
          this.lastError = error instanceof Error ? error.message : String(error);
          emitWakeEvent("wake_post_failed", {
            frame_type: current.frameType,
            signal: current.signal,
            error: this.lastError,
            http_status: this.lastHttpStatus,
            attempt: current.attempt,
          });
          this.scheduleRetry(current.attempt);
          return;
        }
      }
    } finally {
      this.flushing = false;
    }
  }

  stop(): void {
    if (this.retryTimer) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private async postWake(wake: PendingWake): Promise<void> {
    this.lastAttemptAt = new Date().toISOString();
    const res = await this.fetchImpl(`${this.hookBase.replace(/\/+$/, "")}/agent`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${this.hookToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(this.postBody(wake)),
    });
    this.lastHttpStatus = res.status;
    if (!res.ok) {
      throw new Error(await formatOpenClawWakeFailure(res));
    }
  }

  private postBody(wake: PendingWake): Record<string, unknown> {
    return {
      message: wake.text,
      name: "ZenHeart inbound",
      agentId: this.openClawAgentId,
      wakeMode: this.wakeMode,
      deliver: "none",
      ...(this.sessionKey ? { sessionKey: this.sessionKey } : {}),
    };
  }

  private scheduleRetry(attempt: number): void {
    if (this.retryTimer) return;
    const delay = Math.min(60_000, this.retryBaseMs * 2 ** Math.min(attempt, 6));
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      void this.flush();
    }, delay);
    emitWakeEvent("wake_retry_scheduled", { delay_ms: delay, attempt });
  }

  private pruneRecent(now: number): void {
    const maxWindow = Math.max(this.dedupeMs, this.roomLineCoalesceMs);
    for (const [key, at] of this.recentKeys) {
      if (now - at > maxWindow) this.recentKeys.delete(key);
    }
  }

  private dedupeWindowFor(frame: unknown): number {
    return isRoomLineFrame(frame) ? this.roomLineCoalesceMs : this.dedupeMs;
  }

  private safeInboundQueueDepth(): number | null {
    if (!this.inboundQueueDepth) return null;
    try {
      const depth = this.inboundQueueDepth();
      if (!Number.isFinite(depth) || depth < 0) return null;
      return Math.floor(depth);
    } catch {
      return null;
    }
  }

  private shouldWakeSignal(signal: string): boolean {
    return this.wakePolicy.shouldWakeSignal(signal);
  }
}

function resolveFrameTypes(explicit?: string[]): Set<string> | null {
  const raw =
    explicit ??
    process.env.ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES
      ?.split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  return raw && raw.length ? new Set(raw) : null;
}

function parseEnvInt(name: string, fallback: number): number {
  const raw = process.env[name]?.trim();
  if (!raw) return fallback;
  const value = Number(raw);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error(`${name} must be a non-negative integer`);
  }
  return Math.floor(value);
}

function wakeDedupeKey(frame: unknown): string {
  if (!isRecord(frame)) return JSON.stringify(frame);
  const type = frameTypeOf(frame);
  const roomId = typeof frame.room_id === "string" ? frame.room_id : "";
  const messageId = typeof frame.message_id === "string" ? frame.message_id : "";
  const text = typeof frame.text === "string" ? frame.text : "";
  const sender = typeof frame.agent_id === "string" ? frame.agent_id : "";
  return [type, roomId, messageId, sender, text].join("|");
}

function isRoomLineFrame(frame: unknown): boolean {
  if (!isRecord(frame)) return false;
  if (frame.type === "message") return true;
  return frame.type === "social_notify" && frame.kind === "message";
}

function summarizeWakeFrame(frame: unknown, inboundQueueDepth: number | null): string {
  const queueLine =
    inboundQueueDepth === null ? "" : `\nQueued inbound frames now: ${inboundQueueDepth}.`;
  if (isRecord(frame)) {
    const type = frameTypeOf(frame);
    if (type === "topic_suggestions_pending") {
      const roomId = typeof frame.room_id === "string" ? ` room=${frame.room_id}` : "";
      const topics = frame.topics;
      if (Array.isArray(topics) && topics.length > 0) {
        const lines: string[] = [];
        for (let i = 0; i < topics.length; i += 1) {
          const row = topics[i];
          if (isRecord(row) && typeof row.text === "string") {
            lines.push(`#${i + 1}: ${truncate(row.text, 220)}`);
          } else {
            lines.push(`#${i + 1}: (no text)`);
          }
        }
        return `${WAKE_ACTION_PREFIX}\n${WAKE_DRAIN_EXAMPLE}${queueLine}\nSummary: ${type}${roomId}\n${lines.join("\n")}`;
      }
      return `${WAKE_ACTION_PREFIX}\n${WAKE_DRAIN_EXAMPLE}${queueLine}\nSummary: ${type}${roomId} (no pending lines)`;
    }
    const roomId = typeof frame.room_id === "string" ? ` room=${frame.room_id}` : "";
    const sender = typeof frame.agent_id === "string" ? ` from=${frame.agent_id}` : "";
    const text = typeof frame.text === "string" ? ` ${truncate(frame.text, 280)}` : "";
    if (text) return `${WAKE_ACTION_PREFIX}\n${WAKE_DRAIN_EXAMPLE}${queueLine}\nSummary: ${type}${roomId}${sender}:${text}`;
    return `${WAKE_ACTION_PREFIX}\n${WAKE_DRAIN_EXAMPLE}${queueLine}\nSummary: ${type}${roomId}${sender}: ${truncate(JSON.stringify(frame), 500)}`;
  }
  return `${WAKE_ACTION_PREFIX}\n${WAKE_DRAIN_EXAMPLE}${queueLine}\nSummary: ${truncate(JSON.stringify(frame), 500)}`;
}

function truncate(value: string, max: number): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 3)}...`;
}

function increment(map: Record<string, number>, key: string): void {
  map[key] = (map[key] ?? 0) + 1;
}

async function formatOpenClawWakeFailure(response: Response): Promise<string> {
  const text = await response.text();
  const formatted = parseOpenClawErrorText(text);
  return formatted
    ? `OpenClaw wake failed with HTTP ${response.status}: ${formatted}`
    : `OpenClaw wake failed with HTTP ${response.status}`;
}

function parseOpenClawErrorText(text: string): string | null {
  try {
    return formatZenlinkHttpErrorBody(JSON.parse(text), "OpenClaw wake failed");
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function emitWakeEvent(event: string, fields: Record<string, unknown>): void {
  console.error(JSON.stringify({ component: "openclaw_wake_notifier", event, ...fields }));
}
