import type { JsonFrame } from "../zenlink/index.js";

export type OpenClawPushRuntimeConfig = {
  hookWakeUrl: string;
  token: string;
  wakeMode: "now" | "next-heartbeat";
  frameTypes: Set<string>;
  dedupeMs: number;
  /**
   * Suppress duplicate `/hooks/wake` for the same room line: both `type:message` and
   * `social_notify` `kind:message` share `room_id` + `sent_at`. OpenClaw `mode:now` wakes can
   * churn MCP workers; coalescing keeps one POST per line (0 = off).
   */
  roomMessageWakeCoalesceMs: number;
};

type FramePushMeta = {
  type: string;
  kind: string | null;
  text: string;
};

function readTrimmed(name: string): string | undefined {
  const v = process.env[name];
  if (v === undefined || v === "") {
    return undefined;
  }
  return v.trim();
}

function parseWakeMode(raw: string | undefined): "now" | "next-heartbeat" {
  if (raw === undefined || raw === "") {
    return "now";
  }
  const l = raw.toLowerCase();
  if (l === "now" || l === "next-heartbeat") {
    return l;
  }
  throw new Error(
    "ZENLINK_MCP_OPENCLAW_WAKE_MODE must be 'now' or 'next-heartbeat' when set",
  );
}

function parseFrameTypes(raw: string | undefined): Set<string> {
  const defaultTypes = ["message", "msgbox_notify", "social_notify"];
  if (raw === undefined || raw === "") {
    return new Set(defaultTypes);
  }
  const parts = raw
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  if (parts.length === 0) {
    return new Set(defaultTypes);
  }
  return new Set(parts);
}

function readDedupeMs(): number {
  const raw = readTrimmed("ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS");
  if (raw === undefined) {
    return 0;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(
      "ZENLINK_MCP_OPENCLAW_PUSH_DEDUPE_MS must be a non-negative number when set",
    );
  }
  return Math.floor(n);
}

function readRoomMessageWakeCoalesceMs(): number {
  const raw = readTrimmed("ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS");
  if (raw === undefined || raw === "") {
    return 2000;
  }
  const n = Number(raw);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(
      "ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS must be a non-negative number when set",
    );
  }
  return Math.floor(n);
}

export function readOpenClawPushConfig(): OpenClawPushRuntimeConfig | undefined {
  const base = readTrimmed("ZENLINK_MCP_OPENCLAW_HOOK_BASE");
  const token = readTrimmed("ZENLINK_MCP_OPENCLAW_HOOK_TOKEN");
  if (base === undefined && token === undefined) {
    return undefined;
  }
  if (base === undefined || token === undefined) {
    throw new Error(
      "OpenClaw push requires both ZENLINK_MCP_OPENCLAW_HOOK_BASE and ZENLINK_MCP_OPENCLAW_HOOK_TOKEN, or neither",
    );
  }
  let hookWakeUrl = base.replace(/\/+$/, "");
  if (!hookWakeUrl.endsWith("/wake")) {
    hookWakeUrl = `${hookWakeUrl}/wake`;
  }
  const wakeMode = parseWakeMode(readTrimmed("ZENLINK_MCP_OPENCLAW_WAKE_MODE"));
  const typesRaw = readTrimmed("ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES");
  const frameTypes = parseFrameTypes(typesRaw);
  const dedupeMs = readDedupeMs();
  const roomMessageWakeCoalesceMs = readRoomMessageWakeCoalesceMs();
  return {
    hookWakeUrl,
    token,
    wakeMode,
    frameTypes,
    dedupeMs,
    roomMessageWakeCoalesceMs,
  };
}

export function describeOpenClawPushPublic(
  cfg: OpenClawPushRuntimeConfig | undefined,
): {
  enabled: boolean;
  hook_wake_url: string | null;
  wake_mode: "now" | "next-heartbeat" | null;
  frame_types: string[];
  dedupe_ms: number;
  room_message_wake_coalesce_ms: number;
} {
  if (!cfg) {
    return {
      enabled: false,
      hook_wake_url: null,
      wake_mode: null,
      frame_types: [],
      dedupe_ms: 0,
      room_message_wake_coalesce_ms: 0,
    };
  }
  return {
    enabled: true,
    hook_wake_url: cfg.hookWakeUrl,
    wake_mode: cfg.wakeMode,
    frame_types: [...cfg.frameTypes],
    dedupe_ms: cfg.dedupeMs,
    room_message_wake_coalesce_ms: cfg.roomMessageWakeCoalesceMs,
  };
}

function strField(f: JsonFrame, key: string): string {
  const v = f[key];
  return typeof v === "string" ? v : "";
}

function wakeSummaryLine(frame: JsonFrame): string {
  const t = strField(frame, "type");
  if (t === "message") {
    const room = strField(frame, "room_id");
    const from = strField(frame, "agent_name") || strField(frame, "agent_id");
    const text = strField(frame, "text");
    const snippet = text.length > 280 ? `${text.slice(0, 280)}...` : text;
    return `room=${room} from=${from}: ${snippet}`;
  }
  if (t === "msgbox_notify" || t === "social_notify") {
    const kind = strField(frame, "kind");
    const room = strField(frame, "room_id");
    const parts = [`kind=${kind || "?"}`];
    if (room) {
      parts.push(`room=${room}`);
    }
    const mid = strField(frame, "message_id");
    if (mid) {
      parts.push(`message_id=${mid}`);
    }
    return parts.join(" ");
  }
  return JSON.stringify(frame).slice(0, 500);
}

function wakeText(frame: JsonFrame): string {
  const t = strField(frame, "type");
  const line = wakeSummaryLine(frame);
  return `[ZenHeart inbound] type=${t} ${line}`;
}

function dedupeKeyForFrame(frame: JsonFrame): string {
  const t = strField(frame, "type");
  if (t === "message") {
    return `${t}:${strField(frame, "room_id")}:${strField(frame, "agent_id")}:${strField(frame, "sent_at")}:${strField(frame, "text").slice(0, 128)}`;
  }
  if (t === "msgbox_notify" || t === "social_notify") {
    return `${t}:${strField(frame, "kind")}:${strField(frame, "message_id")}:${strField(frame, "room_id")}`;
  }
  return `${t}:${wakeSummaryLine(frame)}`;
}

const dedupeSeen = new Map<string, number>();

/**
 * Same chat line is often delivered twice: full `message` + `social_notify` preview (`kind:message`)
 * with the same `room_id` / `sent_at`. Used to avoid duplicate wake POSTs.
 */
function roomMessageLogicalWakeKey(frame: JsonFrame): string | null {
  const t = strField(frame, "type");
  const room = strField(frame, "room_id");
  const sentAt = strField(frame, "sent_at");
  if (!room || !sentAt) {
    return null;
  }
  if (t === "message") {
    return `room-msg:${room}:${sentAt}`;
  }
  if (t === "social_notify" && strField(frame, "kind") === "message") {
    return `room-msg:${room}:${sentAt}`;
  }
  return null;
}

function dedupeAllows(key: string, dedupeMs: number): boolean {
  if (dedupeMs <= 0) {
    return true;
  }
  const now = Date.now();
  const cutoff = now - dedupeMs;
  for (const [k, ts] of dedupeSeen) {
    if (ts < cutoff) {
      dedupeSeen.delete(k);
    }
  }
  const last = dedupeSeen.get(key);
  if (last !== undefined && now - last < dedupeMs) {
    return false;
  }
  dedupeSeen.set(key, now);
  return true;
}

export class OpenClawPushNotifier {
  private readonly cfg: OpenClawPushRuntimeConfig;
  private lastError: string | null = null;
  private lastOkAt: number | null = null;
  private lastOkFrame: FramePushMeta | null = null;
  private lastFailedFrame: FramePushMeta | null = null;
  private sentTotalByType: Record<string, number> = {};
  private failedTotalByType: Record<string, number> = {};
  /** Frames that did not POST because dedupe window saw the same key. */
  private skippedDedupeByType: Record<string, number> = {};
  /** Frames that did not POST because another frame already woke the same room line (see roomMessageLogicalWakeKey). */
  private skippedRoomLineCoalesceByType: Record<string, number> = {};
  /** type field present but not in configured frameTypes (diagnostic). */
  private skippedFrameTypeFilterByType: Record<string, number> = {};
  private readonly roomMessageWakeInFlight = new Set<string>();
  private readonly roomMessageWakeLastOkMs = new Map<string, number>();

  constructor(config: OpenClawPushRuntimeConfig) {
    this.cfg = config;
  }

  status(): {
    last_error: string | null;
    last_ok_at_ms: number | null;
    last_ok_frame: FramePushMeta | null;
    last_failed_frame: FramePushMeta | null;
    sent_total_by_type: Record<string, number>;
    failed_total_by_type: Record<string, number>;
    skipped_dedupe_by_type: Record<string, number>;
    skipped_room_line_coalesce_by_type: Record<string, number>;
    skipped_frame_type_filter_by_type: Record<string, number>;
  } {
    return {
      last_error: this.lastError,
      last_ok_at_ms: this.lastOkAt,
      last_ok_frame: this.lastOkFrame,
      last_failed_frame: this.lastFailedFrame,
      sent_total_by_type: { ...this.sentTotalByType },
      failed_total_by_type: { ...this.failedTotalByType },
      skipped_dedupe_by_type: { ...this.skippedDedupeByType },
      skipped_room_line_coalesce_by_type: {
        ...this.skippedRoomLineCoalesceByType,
      },
      skipped_frame_type_filter_by_type: {
        ...this.skippedFrameTypeFilterByType,
      },
    };
  }

  notifyInboundQueued(frame: JsonFrame): void {
    const cfg = this.cfg;
    const t = strField(frame, "type");
    if (!cfg.frameTypes.has(t)) {
      if (t) {
        this.skippedFrameTypeFilterByType[t] =
          (this.skippedFrameTypeFilterByType[t] ?? 0) + 1;
      }
      return;
    }

    const dk = dedupeKeyForFrame(frame);
    if (!dedupeAllows(dk, cfg.dedupeMs)) {
      this.skippedDedupeByType[t] = (this.skippedDedupeByType[t] ?? 0) + 1;
      return;
    }

    const coalesceMs = cfg.roomMessageWakeCoalesceMs;
    const logicalKey = roomMessageLogicalWakeKey(frame);
    if (logicalKey && coalesceMs > 0) {
      const now = Date.now();
      const cutoff = now - coalesceMs;
      for (const [k, ts] of this.roomMessageWakeLastOkMs) {
        if (ts < cutoff) {
          this.roomMessageWakeLastOkMs.delete(k);
        }
      }
      const lastOk = this.roomMessageWakeLastOkMs.get(logicalKey);
      if (lastOk !== undefined && now - lastOk < coalesceMs) {
        this.skippedRoomLineCoalesceByType[t] =
          (this.skippedRoomLineCoalesceByType[t] ?? 0) + 1;
        return;
      }
      if (this.roomMessageWakeInFlight.has(logicalKey)) {
        this.skippedRoomLineCoalesceByType[t] =
          (this.skippedRoomLineCoalesceByType[t] ?? 0) + 1;
        return;
      }
      this.roomMessageWakeInFlight.add(logicalKey);
    }

    const text = wakeText(frame);
    const meta: FramePushMeta = {
      type: t,
      kind: strField(frame, "kind") || null,
      text,
    };
    const body = {
      text,
      mode: cfg.wakeMode,
    };

    void (async () => {
      try {
        const res = await fetch(cfg.hookWakeUrl, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${cfg.token}`,
          },
          body: JSON.stringify(body),
          signal: AbortSignal.timeout(12_000),
        });
        if (!res.ok) {
          const errText = await res.text().catch(() => "");
          throw new Error(`OpenClaw wake HTTP ${res.status} ${errText}`);
        }
        this.lastError = null;
        this.lastOkAt = Date.now();
        this.lastOkFrame = meta;
        this.sentTotalByType[t] = (this.sentTotalByType[t] ?? 0) + 1;
        if (logicalKey && coalesceMs > 0) {
          this.roomMessageWakeLastOkMs.set(logicalKey, Date.now());
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        this.lastError = msg;
        this.lastFailedFrame = meta;
        this.failedTotalByType[t] = (this.failedTotalByType[t] ?? 0) + 1;
        console.error(`zenlink-mcp: OpenClaw wake failed: ${msg}`);
      } finally {
        if (logicalKey && coalesceMs > 0) {
          this.roomMessageWakeInFlight.delete(logicalKey);
        }
      }
    })();
  }
}
