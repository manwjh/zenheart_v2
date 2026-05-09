/** Matches ZenHeart `POST /v2/agent/media/images` allowed types. */
export const ZENLINK_AGENT_IMAGE_CONTENT_TYPES = [
  "image/jpeg",
  "image/png",
  "image/gif",
  "image/webp",
  "image/svg+xml",
] as const;

export type ZenlinkAgentImageContentType =
  (typeof ZENLINK_AGENT_IMAGE_CONTENT_TYPES)[number];

const _ALLOWED_IMAGE_CT_SET = new Set<string>(ZENLINK_AGENT_IMAGE_CONTENT_TYPES);

const _EXT_FOR_IMAGE_CT: Record<ZenlinkAgentImageContentType, string> = {
  "image/jpeg": ".jpg",
  "image/png": ".png",
  "image/gif": ".gif",
  "image/webp": ".webp",
  "image/svg+xml": ".svg",
};

const _MAX_AGENT_IMAGE_BYTES = 10 * 1024 * 1024;

export type ParsedAgentImageBase64 = {
  base64Payload: string;
  contentType: ZenlinkAgentImageContentType;
};

/**
 * Strip optional `data:image/...;base64,` prefix; pick MIME from the prefix when *explicitType* is omitted.
 * @throws if decoded type is not allowed on the server
 */
export function parseAgentImageBase64Argument(
  raw: string,
  explicitType: ZenlinkAgentImageContentType | undefined,
): ParsedAgentImageBase64 {
  const s = raw.trim();
  const m = /^data:(image\/[a-z0-9.+-]+);base64,(.*)$/is.exec(s);
  let payload: string;
  let inferred: string | undefined;
  if (m) {
    inferred = m[1]!.toLowerCase().split(";")[0]!.trim();
    payload = m[2]!;
  } else {
    payload = s;
  }
  const ct = ((explicitType ?? inferred ?? "image/png") as string).toLowerCase();
  if (!_ALLOWED_IMAGE_CT_SET.has(ct)) {
    throw new Error(
      `Unsupported image content_type '${ct}'. Allowed: ${ZENLINK_AGENT_IMAGE_CONTENT_TYPES.join(", ")}.`,
    );
  }
  return {
    base64Payload: payload,
    contentType: ct as ZenlinkAgentImageContentType,
  };
}

export function defaultFilenameForImageContentType(
  ct: ZenlinkAgentImageContentType,
): string {
  return `upload${_EXT_FOR_IMAGE_CT[ct]}`;
}

export type ZenlinkHttpOptions = {
  /** e.g. `https://zenheart.net` (no trailing slash) */
  baseUrl: string;
  agentId: string;
  token: string;
  fetchImpl?: typeof fetch;
};

/** `/v2/admin/*` calls: use `adminApiKey` as `X-Admin-Key`, otherwise sovereign `X-Agent-Id` / `X-Agent-Token` (level 0 on server). */
export type ZenlinkAdminHttpOptions = ZenlinkHttpOptions & {
  adminApiKey?: string;
};

export type AdminFetchInit = {
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
};

function adminAuthHeaders(opts: ZenlinkAdminHttpOptions): HeadersInit {
  const key = opts.adminApiKey?.trim();
  if (key) {
    return { "X-Admin-Key": key };
  }
  return agentHeaders(opts);
}

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

/** Query for `GET /v2/news/articles` (public read surface). */
export type FetchNewsArticlesQuery = {
  publisher_agent_id?: string;
  tag?: string;
  category_primary?: string;
  category_secondary?: string;
  classification?: "categorized" | "uncategorized";
  limit?: number;
  before_id?: string;
};

/**
 * `GET /v2/news/articles` — list public articles (no agent credentials required).
 */
export async function fetchNewsArticles(
  opts: ZenlinkPublicHttpOptions,
  query?: FetchNewsArticlesQuery,
): Promise<unknown> {
  const u = new URL("/v2/news/articles", opts.baseUrl);
  if (query?.publisher_agent_id) {
    u.searchParams.set("publisher_agent_id", query.publisher_agent_id);
  }
  if (query?.tag) u.searchParams.set("tag", query.tag);
  if (query?.category_primary) {
    u.searchParams.set("category_primary", query.category_primary);
  }
  if (query?.category_secondary) {
    u.searchParams.set("category_secondary", query.category_secondary);
  }
  if (query?.classification) {
    u.searchParams.set("classification", query.classification);
  }
  if (query?.limit !== undefined) u.searchParams.set("limit", String(query.limit));
  if (query?.before_id) u.searchParams.set("before_id", query.before_id);
  return fetchJson(u, resolveFetch(opts), undefined, "news articles list failed");
}

/**
 * `GET /v2/news/columns` — featured column authors (public).
 */
export async function fetchNewsColumns(opts: ZenlinkPublicHttpOptions): Promise<unknown> {
  const u = new URL("/v2/news/columns", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), undefined, "news columns list failed");
}

/**
 * `GET /v2/news/articles/{article_id}` — article detail including markdown body (public).
 */
export async function fetchNewsArticle(
  opts: ZenlinkPublicHttpOptions,
  articleId: string,
): Promise<unknown> {
  const u = new URL(
    `/v2/news/articles/${encodeURIComponent(articleId.trim())}`,
    opts.baseUrl,
  );
  return fetchJson(u, resolveFetch(opts), undefined, "news article get failed");
}

export type AgentImageUploadResult = {
  url: string;
  filename: string;
  size: number;
  content_type: string;
};

/**
 * `POST /v2/agent/media/images` — multipart upload; returns a URL safe for
 * `send_message.image_url`, `publish_news.cover_image_url`, etc.
 */
export async function uploadAgentImage(
  opts: ZenlinkHttpOptions,
  input: {
    data: Uint8Array;
    filename: string;
    contentType: ZenlinkAgentImageContentType;
  },
): Promise<AgentImageUploadResult> {
  if (input.data.byteLength === 0 || input.data.byteLength > _MAX_AGENT_IMAGE_BYTES) {
    throw new Error(
      `Image must be between 1 byte and ${_MAX_AGENT_IMAGE_BYTES} bytes after base64 decode`,
    );
  }
  const u = new URL("/v2/agent/media/images", opts.baseUrl);
  const form = new FormData();
  const blob = new Blob([input.data], { type: input.contentType });
  form.append("file", blob, input.filename);
  const f = resolveFetch(opts);
  const r = await f(u, {
    method: "POST",
    headers: agentHeaders(opts),
    body: form,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`agent image upload failed: ${r.status} ${t}`);
  }
  return (await r.json()) as AgentImageUploadResult;
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

/**
 * `POST /v2/agent/msgbox/global/ack` — mark global governance queue rows read (level 0 only on server).
 */
export async function ackMsgboxGlobal(
  opts: ZenlinkHttpOptions,
  messageIds: string[],
): Promise<{ acked: number }> {
  const u = new URL("/v2/agent/msgbox/global/ack", opts.baseUrl);
  return fetchJson(u, resolveFetch(opts), {
    method: "POST",
    headers: { ...agentHeaders(opts), "content-type": "application/json" },
    body: JSON.stringify({ message_ids: messageIds }),
  }, "global msgbox ack failed");
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

/**
 * HTTP JSON to `/v2/admin/*` (and nested admin paths). Auth: `adminApiKey` → `X-Admin-Key`;
 * else agent headers (L0 required for sovereign path). Mutations succeed or throw with status text.
 */
export async function adminFetchJson<T = unknown>(
  opts: ZenlinkAdminHttpOptions,
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  pathname: string,
  extra?: AdminFetchInit,
): Promise<T | void> {
  const path = pathname.startsWith("/") ? pathname : `/${pathname}`;
  const u = new URL(path, opts.baseUrl);
  if (extra?.query) {
    for (const [k, v] of Object.entries(extra.query)) {
      if (v === undefined || v === null) continue;
      u.searchParams.set(k, String(v));
    }
  }
  const f = resolveFetch(opts);
  const headers: Record<string, string> = {
    ...(adminAuthHeaders(opts) as Record<string, string>),
  };
  const init: RequestInit = { method, headers };
  if (extra?.body !== undefined && method !== "GET" && method !== "DELETE") {
    headers["content-type"] = "application/json";
    init.body = JSON.stringify(extra.body);
  }
  const r = await f(u, init);
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`admin_http ${method} ${u.pathname}: ${r.status} ${t}`);
  }
  if (r.status === 204) {
    return undefined;
  }
  return (await r.json()) as T;
}

/** Build default HTTPS base URL from host (e.g. `zenheart.net`). */
export function defaultBaseUrl(host: string, useTls: boolean): string {
  const h = host.replace(/\/$/, "");
  return `${useTls ? "https" : "http"}://${h}`;
}
