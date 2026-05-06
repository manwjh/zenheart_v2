/** ZenlinkSession environment readers (fail fast on invalid values). */

export function readWsWaitTimeoutMs(): number {
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

export function readLongLivedAutostart(): boolean {
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

export function readInboundQueueMax(): number {
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

export function readInboundDropTypes(): Set<string> {
  const raw = process.env["ZENLINK_MCP_INBOUND_DROP_TYPES"];
  if (raw === undefined || raw.trim() === "") {
    return new Set(["ping", "pong"]);
  }
  return new Set(
    raw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean),
  );
}

export function readClientPingIntervalMs(): number {
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
