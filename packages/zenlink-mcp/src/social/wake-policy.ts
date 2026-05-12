export type WakePolicyMode = "default" | "allowlist";
export type WakePolicyUpdatedBy = "startup_env" | "options" | "mcp" | "reset";

export interface WakePolicyStatus {
  mode: WakePolicyMode;
  wake_signals: string[] | null;
  default_muted_signals: string[];
  known_signals: string[];
  updated_at: string;
  updated_by: WakePolicyUpdatedBy;
}

export interface WakePolicyOptions {
  wakeSignals?: string[];
  updatedBy?: WakePolicyUpdatedBy;
}

export const DEFAULT_MUTED_WAKE_SIGNALS = [
  "room.member_joined",
  "room.member_joined_notify",
  "room.member_left",
  "room.member_left_notify",
] as const;

export const KNOWN_WAKE_SIGNALS = [
  "room.message",
  "room.message_notify",
  "room.topic_suggestions_pending",
  "msgbox.notify",
  "news.signal",
  "system.error",
  "room.door_closed",
  "room.dissolved",
  ...DEFAULT_MUTED_WAKE_SIGNALS,
] as const;

export class WakePolicy {
  private allowlist: Set<string> | null;
  private updatedAt: string;
  private updatedBy: WakePolicyUpdatedBy;

  constructor(options: WakePolicyOptions = {}) {
    this.allowlist = normalizeSignals(options.wakeSignals);
    this.updatedAt = new Date().toISOString();
    this.updatedBy = options.updatedBy ?? (this.allowlist ? "options" : "reset");
  }

  shouldWakeSignal(signal: string): boolean {
    if (this.allowlist) return this.allowlist.has(signal);
    return !DEFAULT_MUTED_WAKE_SIGNALS.includes(signal as typeof DEFAULT_MUTED_WAKE_SIGNALS[number]);
  }

  setAllowlist(signals: string[], updatedBy: WakePolicyUpdatedBy = "mcp"): WakePolicyStatus {
    this.allowlist = normalizeSignals(signals) ?? new Set();
    this.touch(updatedBy);
    return this.status();
  }

  reset(updatedBy: WakePolicyUpdatedBy = "reset"): WakePolicyStatus {
    this.allowlist = null;
    this.touch(updatedBy);
    return this.status();
  }

  status(): WakePolicyStatus {
    return {
      mode: this.allowlist ? "allowlist" : "default",
      wake_signals: this.allowlist ? [...this.allowlist].sort() : null,
      default_muted_signals: [...DEFAULT_MUTED_WAKE_SIGNALS],
      known_signals: [...KNOWN_WAKE_SIGNALS].sort(),
      updated_at: this.updatedAt,
      updated_by: this.updatedBy,
    };
  }

  private touch(updatedBy: WakePolicyUpdatedBy): void {
    this.updatedAt = new Date().toISOString();
    this.updatedBy = updatedBy;
  }
}

export function parseSignalList(raw: string | undefined): string[] | undefined {
  const signals = raw
    ?.split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  return signals && signals.length ? signals : undefined;
}

export function frameTypeOf(frame: unknown): string {
  if (isRecord(frame) && typeof frame.type === "string") return frame.type;
  return "unknown";
}

export function signalOf(frame: unknown): string {
  if (!isRecord(frame)) return "unknown";
  const type = frameTypeOf(frame);
  if (type === "message") return "room.message";
  if (type === "member_joined") return "room.member_joined";
  if (type === "member_left") return "room.member_left";
  if (type === "msgbox_notify") return "msgbox.notify";
  if (type === "news_signal") return "news.signal";
  if (type === "error") return "system.error";
  if (type === "room_door_closed") return "room.door_closed";
  if (type === "topic_suggestions_pending") return "room.topic_suggestions_pending";
  if (type === "social_notify") return socialNotifySignal(frame);
  return `frame.${type}`;
}

function normalizeSignals(signals: string[] | undefined): Set<string> | null {
  if (!signals) return null;
  return new Set(signals.map((signal) => signal.trim()).filter(Boolean));
}

function socialNotifySignal(frame: Record<string, unknown>): string {
  const kind = typeof frame.kind === "string" && frame.kind.trim() ? frame.kind.trim() : "unknown";
  if (kind === "message") return "room.message_notify";
  if (kind === "member_joined") return "room.member_joined_notify";
  if (kind === "member_left") return "room.member_left_notify";
  if (kind === "room_dissolved") return "room.dissolved";
  return `social_notify.${kind}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
