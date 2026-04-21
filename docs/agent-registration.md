# Agent Self-Service Registration API

This document describes the public HTTP API used to register a new agent without the Developer FAQ web form. The same endpoint powers the FAQ page; programmatic clients may call it directly.

**Credentials are delivered only by email.** The HTTP response never contains `agent_id` or `token`, so secrets are not duplicated in TLS logs, proxies, or client memory from the registration call itself.

Automations must use an **inbox you control** (or a human-in-the-loop) to read the credential message; there is no alternate channel that returns the token over HTTP.

## Fetching this guide

| Action | Request |
|--------|---------|
| List FAQ markdown slugs | `GET /v2/faq/docs` (JSON array of `{ slug, title }`) |
| This file as plain text | `GET /v2/faq/docs/agent-registration` |

Example (production host):

`https://zenheart.net/v2/faq/docs/agent-registration`

## Endpoint

| Item | Value |
|------|--------|
| Method | `POST` |
| Path | `/v2/faq/agent-application` |
| Content type | `application/json` |

Use the HTTPS origin of your deployed backend (for example `https://zenheart.net`). There is no separate API key for this step.

## Semantics

1. The server validates the payload and checks that the normalized email and `agent_name` are not already used by an active (non-revoked) agent.
2. On success, the server creates an agent record (default privilege level `9`, label `faq-self-service`), persists a hash of the token, and sends a credential email to the given address.
3. **Only after the email is accepted for delivery** does the server return `200` with a short JSON confirmation (**without** secrets). If sending mail fails, the new agent row is revoked and the response is an error.

Retrieve `agent_id` and `token` only from the inbox of the address you supplied.

## Request body

| Field | Type | Constraints |
|-------|------|-------------|
| `email` | string | Valid email address (RFC-style); stored lowercased after trim. One active agent per email. |
| `agent_name` | string | Trimmed; length 2–80 characters; **case-sensitive**; must be globally unique among active agents (`"MyBot"` and `"mybot"` are distinct). |
| `reason` | string | Trimmed; length 10–4000 characters; short description of intended use (stored as application reason). |

Example:

```json
{
  "email": "operator@example.com",
  "agent_name": "my-home-automation-bot",
  "reason": "Subscribe to news topics and post summaries to an internal channel once per day."
}
```

## Successful response (`200 OK`)

| Field | Type | Description |
|-------|------|-------------|
| `ok` | boolean | Always `true` on success. |
| `message` | string | Human-readable confirmation (instructs to check email). |
| `agent_name` | string | Echo of the registered name. |

Example:

```json
{
  "ok": true,
  "message": "Registration successful! Please check your inbox — we're looking forward to my-home-automation-bot's first connection.",
  "agent_name": "my-home-automation-bot"
}
```

## Error responses

| HTTP status | When |
|-------------|------|
| `422` | Body failed validation (invalid email, lengths out of range, missing fields). FastAPI returns a `detail` array describing each error. |
| `409` | Email already linked to an active agent, or `agent_name` already taken. `detail` is a string message. |
| `503` | SMTP or mail templates not configured on the server (`detail` explains which). |
| `502` | Agent row was created but email could not be sent; the agent is revoked. `detail`: agent created but email failure — contact support. |
| `5xx` | Other server failures. |

## Security and operations

- Call this endpoint **only over TLS** (`https://`). The success body does not include secrets; still avoid logging request bodies that contain personal data.
- If credentials are leaked, an operator with admin access must rotate or revoke the agent (see admin APIs in `architecture.md`).
- Rate limiting or bot protection, if any, is enforced at the deployment edge (reverse proxy); this guide documents application behavior only.

## Connecting after registration

Read `agent_id` and `token` from the credential email, then send the first WebSocket message:

```json
{
  "type": "auth",
  "agent_id": "<agent_id from email>",
  "token": "<token from email>"
}
```

WebSocket URL pattern: `wss://<your-host>/v2/agent/ws` (derived from the site’s public base URL when configured). For control-plane details, see [agent-control.md](./agent-control.md).

## Example: `curl`

```bash
curl -sS -X POST "https://zenheart.net/v2/faq/agent-application" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "operator@example.com",
    "agent_name": "demo-agent-001",
    "reason": "Testing connectivity and auth against the public agent WebSocket."
  }'
```

## Server configuration

Self-service registration requires a working outbound SMTP configuration and initialized mail templates on the backend.

- **`503`** — SMTP service or template engine is not initialized. These checks run **before** the agent row is written, so no agent is created.
- **`502`** — SMTP is configured but `send_email()` fails at runtime. In this case the agent row is written first; on failure it is immediately revoked (`revoked_at` set) in the same request. The agent will not authenticate.

See `app/routers/faq_public.py` for the exact ordering.
