/**
 * Optional push: after ZenHeart inbound WS frames are enqueued, POST OpenClaw
 * POST {hookBase}/wake with { text, mode } — see OpenClaw automation webhook docs.
 */

import type { JsonFrame } from "zenlink";

export type OpenClawPushRuntimeConfig = {
  hookWakeUrl: string;
  token: string;
  wakeMode: "now" | "next-heartbeat";
  frameTypes: Set<string>;
  dedupeMs: number;
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

/**
 * When both ZENLINK_MCP_OPENCLAW_HOOK_BASE and ZENLINK_MCP_OPENCLAW_HOOK_TOKEN are set,
 * returns config; otherwise returns undefined (push disabled).
 */
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
  return { hookWakeUrl, token, wakeMode, frameTypes, dedupeMs };
}

export function describeOpenClawPushPublic(
  cfg: OpenClawPushRuntimeConfig | undefined,
): {
  enabled: boolean;
  hook_wake_url: string | null;
  wake_mode: "now" | "next-heartbeat" | null;
  frame_types: string[];
  dedupe_ms: number;
} {
  if (!cfg) {
    return {
      enabled: false,
      hook_wake_url: null,
      wake_mode: null,
      frame_types: [],
      dedupe_ms: 0,
    };
  }
  return {
    enabled: true,
    hook_wake_url: cfg.hookWakeUrl,
    wake_mode: cfg.wakeMode,
    frame_types: [...cfg.frameTypes],
    dedupe_ms: cfg.dedupeMs,
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
    const snippet = text.length > 280 ? `${text.slice(0, 280)}…` : text;
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

  constructor(config: OpenClawPushRuntimeConfig) {
    this.cfg = config;
  }

  status(): {
    last_error: string | null;
    last_ok_at_ms: number | null;
  } {
    return {
      last_error: this.lastError,
      last_ok_at_ms: this.lastOkAt,
    };
  }

  /** Fire-and-forget wake when an inbound frame is queued for zenlink_inbound_poll. */
  notifyInboundQueued(frame: JsonFrame): void {
    const cfg = this.cfg;
    const t = strField(frame, "type");
    if (!cfg.frameTypes.has(t)) {
      return;
    }

    const dk = dedupeKeyForFrame(frame);
    if (!dedupeAllows(dk, cfg.dedupeMs)) {
      return;
    }

    const body = {
      text: wakeText(frame),
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
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        this.lastError = msg;
        console.error(`zenlink-mcp: OpenClaw wake failed: ${msg}`);
      }
    })();
  }
}
