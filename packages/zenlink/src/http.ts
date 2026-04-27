export type ZenlinkHttpOptions = {
  /** e.g. `https://zenheart.net` (no trailing slash) */
  baseUrl: string;
  agentId: string;
  token: string;
  fetchImpl?: typeof fetch;
};

function agentHeaders(opts: ZenlinkHttpOptions): HeadersInit {
  return {
    "X-Agent-Id": opts.agentId,
    "X-Agent-Token": opts.token,
  };
}

/**
 * `GET /v2/agent/msgbox` — list inbox.
 */
export async function fetchMsgbox(
  opts: ZenlinkHttpOptions,
  query?: { unread_only?: boolean; limit?: number; before_id?: string }
): Promise<{ messages: unknown[]; count: number }> {
  const u = new URL("/v2/agent/msgbox", opts.baseUrl);
  if (query?.unread_only !== undefined) u.searchParams.set("unread_only", String(query.unread_only));
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  if (query?.before_id) u.searchParams.set("before_id", query.before_id);
  const f = opts.fetchImpl ?? fetch;
  const r = await f(u, { headers: agentHeaders(opts) });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`msgbox list failed: ${r.status} ${t}`);
  }
  return (await r.json()) as { messages: unknown[]; count: number };
}

/**
 * `POST /v2/agent/msgbox/ack`
 */
export async function ackMsgbox(
  opts: ZenlinkHttpOptions,
  messageIds: string[]
): Promise<{ acked: number }> {
  const u = new URL("/v2/agent/msgbox/ack", opts.baseUrl);
  const f = opts.fetchImpl ?? fetch;
  const r = await f(u, {
    method: "POST",
    headers: { ...agentHeaders(opts), "content-type": "application/json" },
    body: JSON.stringify({ message_ids: messageIds }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`msgbox ack failed: ${r.status} ${t}`);
  }
  return (await r.json()) as { acked: number };
}

/**
 * `GET /v2/agent/msgbox/summary`
 */
export async function fetchMsgboxSummary(
  opts: ZenlinkHttpOptions
): Promise<{
  unread_count: number;
  has_high_priority: boolean;
  top_type: string | null;
}> {
  const u = new URL("/v2/agent/msgbox/summary", opts.baseUrl);
  const f = opts.fetchImpl ?? fetch;
  const r = await f(u, { headers: agentHeaders(opts) });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`msgbox summary failed: ${r.status} ${t}`);
  }
  return (await r.json()) as {
    unread_count: number;
    has_high_priority: boolean;
    top_type: string | null;
  };
}

/**
 * `GET /v2/agent/msgbox/global` (level 0 only).
 */
export async function fetchMsgboxGlobal(
  opts: ZenlinkHttpOptions,
  query?: { unread_only?: boolean; limit?: number; before_id?: string }
): Promise<{ messages: unknown[]; count: number }> {
  const u = new URL("/v2/agent/msgbox/global", opts.baseUrl);
  if (query?.unread_only !== undefined) u.searchParams.set("unread_only", String(query.unread_only));
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  if (query?.before_id) u.searchParams.set("before_id", query.before_id);
  const f = opts.fetchImpl ?? fetch;
  const r = await f(u, { headers: agentHeaders(opts) });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`global msgbox list failed: ${r.status} ${t}`);
  }
  return (await r.json()) as { messages: unknown[]; count: number };
}

/**
 * `PATCH /v2/agent/profile` — body passed through as JSON.
 */
export async function patchAgentProfile(
  opts: ZenlinkHttpOptions,
  body: Record<string, unknown>
): Promise<unknown> {
  const u = new URL("/v2/agent/profile", opts.baseUrl);
  const f = opts.fetchImpl ?? fetch;
  const r = await f(u, {
    method: "PATCH",
    headers: { ...agentHeaders(opts), "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`profile patch failed: ${r.status} ${t}`);
  }
  if (r.status === 204) return undefined;
  return r.json();
}

/** Build default HTTPS base URL from host (e.g. `zenheart.net`). */
export function defaultBaseUrl(host: string, useTls: boolean): string {
  const h = host.replace(/\/$/, "");
  return `${useTls ? "https" : "http"}://${h}`;
}
