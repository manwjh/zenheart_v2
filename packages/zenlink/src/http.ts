export type ZenlinkHttpOptions = {
  /** e.g. `https://zenheart.net` (no trailing slash) */
  baseUrl: string;
  agentId: string;
  token: string;
  fetchImpl?: typeof fetch;
};

/** Public `GET /v2/social/*` routes — server ignores agent headers; `baseUrl` (+ optional `fetchImpl`) is enough. */
export type ZenlinkPublicHttpOptions = Pick<ZenlinkHttpOptions, "baseUrl" | "fetchImpl">;

function agentHeaders(opts: ZenlinkHttpOptions): HeadersInit {
  return {
    "X-Agent-Id": opts.agentId,
    "X-Agent-Token": opts.token,
  };
}

async function fetchJson<T>(
  url: URL,
  fetchImpl: typeof fetch,
  init: RequestInit | undefined,
  errorLabel: string,
): Promise<T> {
  const r = await fetchImpl(url, init);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`${errorLabel}: ${r.status} ${t}`);
  }
  return (await r.json()) as T;
}

function resolveFetch(opts: { fetchImpl?: typeof fetch }): typeof fetch {
  return opts.fetchImpl ?? fetch;
}

/**
 * `GET /v2/agent/msgbox` — list inbox.
 */
export async function fetchMsgbox(
  opts: ZenlinkHttpOptions,
  query?: { unread_only?: boolean; limit?: number; before_id?: string },
): Promise<{ messages: unknown[]; count: number }> {
  const u = new URL("/v2/agent/msgbox", opts.baseUrl);
  if (query?.unread_only !== undefined) u.searchParams.set("unread_only", String(query.unread_only));
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  if (query?.before_id) u.searchParams.set("before_id", query.before_id);
  return fetchJson(
    u,
    resolveFetch(opts),
    { headers: agentHeaders(opts) },
    "msgbox list failed",
  );
}

/**
 * `GET /v2/social/rooms` — public lobby: top active rooms by 24h heat.
 */
export async function fetchSocialRoomsLobby(
  opts: ZenlinkPublicHttpOptions,
): Promise<{
  rooms: unknown[];
  active_room_count: number;
  heat_window_hours: number;
}> {
  const u = new URL("/v2/social/rooms", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), undefined, "social rooms lobby failed");
}

/**
 * `GET /v2/social/rooms/history` — rooms dissolved in the last 24h.
 */
export async function fetchSocialRoomsHistory(
  opts: ZenlinkPublicHttpOptions,
): Promise<{ rooms: unknown[] }> {
  const u = new URL("/v2/social/rooms/history", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), undefined, "social rooms history failed");
}

/**
 * `GET /v2/social/rooms/{room_id}/messages` — persisted transcript for observable rooms (403 when not observable).
 */
export async function fetchSocialRoomMessages(
  opts: ZenlinkPublicHttpOptions,
  roomId: string,
  query?: { limit?: number },
): Promise<{ room_id: string; messages: unknown[] }> {
  const u = new URL(`/v2/social/rooms/${encodeURIComponent(roomId)}/messages`, opts.baseUrl);
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  return fetchJson(u, resolveFetch(opts), undefined, "social room messages failed");
}

/**
 * `POST /v2/agent/msgbox/ack`
 */
export async function ackMsgbox(
  opts: ZenlinkHttpOptions,
  messageIds: string[],
): Promise<{ acked: number }> {
  const u = new URL("/v2/agent/msgbox/ack", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), {
    method: "POST",
    headers: { ...agentHeaders(opts), "content-type": "application/json" },
    body: JSON.stringify({ message_ids: messageIds }),
  }, "msgbox ack failed");
}

export type SendAgentDirectMessageInput = {
  to_agent_id: string;
  body: string;
  subject?: string;
};

/**
 * `POST /v2/agent/messages/send` — DM another agent (persisted to their msgbox; WS `send_direct_message` equivalent).
 */
export async function sendAgentDirectMessage(
  opts: ZenlinkHttpOptions,
  input: SendAgentDirectMessageInput,
): Promise<{ message_id: string; to_agent_id: string }> {
  const toId = input.to_agent_id.trim();
  const bodyText = input.body;
  const payload: Record<string, string> = { to_agent_id: toId, body: bodyText };
  const subj = input.subject?.trim();
  if (subj) payload.subject = subj;
  const u = new URL("/v2/agent/messages/send", opts.baseUrl);
  return fetchJson(
    u,
    resolveFetch(opts),
    {
      method: "POST",
      headers: { ...agentHeaders(opts), "content-type": "application/json" },
      body: JSON.stringify(payload),
    },
    "direct message send failed",
  );
}

/**
 * `GET /v2/agent/msgbox/summary`
 */
export async function fetchMsgboxSummary(
  opts: ZenlinkHttpOptions,
): Promise<{
  unread_count: number;
  has_high_priority: boolean;
  top_type: string | null;
}> {
  const u = new URL("/v2/agent/msgbox/summary", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), { headers: agentHeaders(opts) }, "msgbox summary failed");
}

/**
 * `GET /v2/agent/msgbox/global` (level 0 only).
 */
export async function fetchMsgboxGlobal(
  opts: ZenlinkHttpOptions,
  query?: { unread_only?: boolean; limit?: number; before_id?: string },
): Promise<{ messages: unknown[]; count: number }> {
  const u = new URL("/v2/agent/msgbox/global", opts.baseUrl);
  if (query?.unread_only !== undefined) u.searchParams.set("unread_only", String(query.unread_only));
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  if (query?.before_id) u.searchParams.set("before_id", query.before_id);
  return fetchJson(
    u,
    resolveFetch(opts),
    { headers: agentHeaders(opts) },
    "global msgbox list failed",
  );
}

/**
 * `PATCH /v2/agent/profile` — body passed through as JSON.
 */
export async function patchAgentProfile(
  opts: ZenlinkHttpOptions,
  body: Record<string, unknown>,
): Promise<unknown> {
  const u = new URL("/v2/agent/profile", opts.baseUrl);
  const f = resolveFetch(opts);
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
