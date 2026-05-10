import type { JsonFrame } from "./types.js";

export class ZenlinkAuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ZenlinkAuthError";
  }
}

export class ZenlinkProtocolError extends Error {
  readonly frame: JsonFrame;
  readonly code: string;
  readonly hint?: string;
  readonly retryable?: boolean;
  readonly category?: string;
  readonly action?: string;

  constructor(frame: JsonFrame, fallback = "ZenHeart protocol error") {
    super(formatZenlinkErrorFrame(frame, fallback));
    this.name = "ZenlinkProtocolError";
    this.frame = frame;
    this.code = zenlinkErrorCode(frame, fallback);
    this.hint = typeof frame.hint === "string" ? frame.hint : undefined;
    this.retryable = typeof frame.retryable === "boolean" ? frame.retryable : undefined;
    this.category = typeof frame.category === "string" ? frame.category : undefined;
    this.action = typeof frame.action === "string" ? frame.action : undefined;
  }
}

export function isZenlinkErrorFrame(frame: JsonFrame): boolean {
  return frame.type === "error" || frame.type === "auth_fail" || frame.type === "subscribe_fail";
}

export function formatZenlinkErrorFrame(frame: JsonFrame, fallback = "ZenHeart error"): string {
  const code = zenlinkErrorCode(frame, fallback);
  const message = typeof frame.message === "string" ? frame.message : fallback;
  const hint = typeof frame.hint === "string" ? frame.hint : "";
  return hint ? `${code}: ${message} Hint: ${hint}` : `${code}: ${message}`;
}

export function formatZenlinkHttpErrorBody(body: unknown, fallback: string): string | null {
  if (!isRecord(body)) return null;
  const error = body.error;
  if (isRecord(error)) {
    return formatZenlinkErrorFrame(error, fallback);
  }
  return null;
}

function zenlinkErrorCode(frame: JsonFrame, fallback: string): string {
  if (typeof frame.code === "string") return frame.code;
  if (typeof frame.reason === "string") return frame.reason;
  return fallback;
}

function isRecord(value: unknown): value is JsonFrame {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
