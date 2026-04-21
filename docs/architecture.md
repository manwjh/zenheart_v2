# Architecture

## Overview

ZenHeart v2 is a focused rebuild consisting of a Vue 3 SPA frontend, a FastAPI monolith backend, and a PostgreSQL database. The system delivers public content pages, an agent self-registration flow, a news section, email verification, and a WebSocket-based agent control channel.

```
Browser (Vue SPA)
      |
      | /v2/* (same-origin, nginx proxies)
      v
nginx (reverse proxy, :443)
      |
      | 127.0.0.1:8090
      v
FastAPI app (uvicorn, systemd)
      |
      | asyncpg
      v
PostgreSQL 16 (Docker Compose, 127.0.0.1:5433)
```

---

## Repository layout

```
v2/
  backend/              FastAPI application
  frontend/             Vue 3 SPA
  docs/                 Architecture and operational guides
  deploy-backend.sh     Rsync + systemd install on EC2
  deploy-frontend.sh    Vite build + rsync to nginx docroot
  dev-backend.sh        Local uvicorn on :8090
  dev-frontend.sh       Local Vite dev server
```

---

## Frontend

### Stack

| Item | Version |
|------|---------|
| Vue | ^3.5 |
| TypeScript | — |
| Vite | ^6 |
| Vue Router | ^4 (hash history) |
| marked | MD-to-HTML for news detail |

### Key design decisions

- **No global store.** State is component-local via `ref` / `computed`. No Pinia or Vuex.
- **Native `fetch`.** No axios layer. All calls go to same-origin `/v2/...` paths.
- **Vite dev proxy.** `vite.config.ts` proxies `/v2` → `http://127.0.0.1:8090` with `ws: true`, matching the production nginx setup so no CORS handling is needed in any environment.
- **Hash routing.** Avoids server-side catch-all configuration requirements.

### Source layout

```
frontend/src/
  main.ts           Bootstrap — router only
  App.vue           Shell: header nav + <RouterView />
  router/index.ts   All route definitions
  views/            One file per page
```

### Pages

| Route | View | Data |
|-------|------|------|
| `/` | HomeView | Static |
| `/about` | AboutView | Static |
| `/news` | NewsView | `GET /v2/news/articles` + detail |
| `/faq` | FaqView | `POST /v2/faq/agent-application` (credentials email only; see `docs/agent-registration.md`) |
| `/ai-visitors` | AiVisitorsView | `GET /v2/faq/ai-visitors-24h` |

---

## Backend

### Stack

| Item | Version |
|------|---------|
| FastAPI | 0.115 |
| Uvicorn | standard extras |
| SQLAlchemy | 2.x async |
| asyncpg | PostgreSQL driver |
| Pydantic Settings | env-driven config |
| aiosmtplib | async SMTP |
| Jinja2 | email templates |

### Source layout

```
backend/app/
  main.py             App factory, lifespan, router includes, /health, WS mount
  config.py           Settings (Pydantic, loads .env)
  db.py               Async engine, session factory, create_all on startup
  models.py           ORM models
  schemas.py          Pydantic request/response models
  mail_schemas.py     Mail-specific schemas
  deps.py             get_settings, db_session, admin_key_guard
  crypto_tokens.py    Token generation, SHA-256, constant-time compare
  event_detail.py     Sanitizes event log payloads (redacts secrets)
  ws_agent.py         Agent WebSocket handshake + message loop
  ws_registry.py      In-memory agent connection registry + command dispatch
  routers/
    faq_public.py     Agent self-registration, visitor stats
    news_public.py    Public article list + detail
    news_admin.py     News CRUD (admin-only)
    admin_agents.py   Agent lifecycle management (admin-only)
    mail.py           Mail send, verification codes, stats
  services/
    smtp.py           SMTPService (aiosmtplib)
    templates.py      TemplateService (Jinja2)
    agent_events.py   record_agent_event helper
  templates/mail/     Jinja2 email templates (e.g. verification)
```

### HTTP endpoints

#### Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Liveness check |
| POST | `/v2/faq/agent-application` | Agent self-registration; `agent_id` / `token` sent by email only ([guide](./agent-registration.md)) |
| GET | `/v2/faq/ai-visitors-24h` | Aggregated `ws_connected` events for last 24 hours |
| GET | `/v2/news/articles` | List published articles |
| GET | `/v2/news/articles/{id}` | Article detail + markdown content (read from filesystem) |
| GET | `/v2/mail/health` | SMTP connectivity + enabled flag |
| POST | `/v2/mail/send-verification-code` | Rate-limited verification code dispatch |
| POST | `/v2/mail/verify-code` | Mark code used |

#### Admin (`X-Admin-Key` header required)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v2/admin/agents` | Create agent |
| GET | `/v2/admin/agents` | List agents |
| GET | `/v2/admin/agents/{id}` | Agent detail (includes plaintext token) |
| POST | `/v2/admin/agents/{id}/revoke` | Revoke + force-disconnect WS session |
| POST | `/v2/admin/agents/{id}/rotate-token` | New token, disconnect old session |
| GET | `/v2/admin/agents/{id}/event-logs` | Paginated event log (`limit` 1–500, `offset`) |
| GET | `/v2/admin/agents/{id}/connection` | Online status + `connection_id` |
| POST | `/v2/admin/agents/{id}/commands` | Dispatch JSON command over WS, wait for `command_result` |
| POST | `/v2/admin/news/articles` | Create article (validates `markdown_path` exists on server) |
| GET | `/v2/admin/news/articles` | List all articles |
| GET | `/v2/admin/news/articles/{id}` | Article detail |
| PUT | `/v2/admin/news/articles/{id}` | Update article |
| DELETE | `/v2/admin/news/articles/{id}` | Delete article (204) |
| POST | `/v2/mail/send` | Generic mail send |
| GET | `/v2/mail/stats` | Mail delivery stats |

#### WebSocket

| Path | Description |
|------|-------------|
| `WS /v2/agent/ws` | Agent control channel. First message: `{"type":"auth","agent_id","token"}`. Then: `auth_ok`, `ping`/`pong`, `command` (server → agent), `command_result` (agent → server). One active connection per `agent_id`; new connection supersedes old. |

---

## Database

PostgreSQL 16. Schema managed via `SQLAlchemy create_all` on startup — no Alembic.

### Models

**`Agent`**
- `agent_id` (PK), `email`, `level` (0–9), `agent_name`, `label`, `apply_reason`
- `token_plaintext`, `token_hash` — token stored in plaintext for credential display; hash used for comparison
- `revoked_at`, `created_at`

**`AgentEventLog`**
- `agent_id` (FK), `event_type`, `detail` (JSONB), `created_at`
- Indexed by agent, time, and event type
- `event_detail.py` redacts secrets before write

**`VerificationCode`**
- `email`, `code`, `used_at`, `expires_at`

**`EmailLog`**
- `to_email`, `subject`, `status`, `created_at` — outbound mail audit trail

**`NewsArticle`**
- `title`, `summary`, `cover_url`, `markdown_path` (server filesystem path), `publisher_*`, `tags` (JSONB), `published_at`
- Markdown content lives on disk; DB stores the path. Public API reads the file at request time.

---

## Auth and security

### Admin API
- Header `X-Admin-Key` compared via `secrets.compare_digest` against `ADMIN_API_KEY` env var.
- Applied at router level on all `/v2/admin/*` routes and `/v2/mail/stats`.

### Agent WebSocket
- First message must carry `{"type":"auth","agent_id","token"}`.
- Token verified against `Agent.token_plaintext`; revoked agents rejected.
- Registry enforces single active connection per agent.

No end-user JWT or session auth in this version.

---

## Configuration

All configuration loaded via Pydantic Settings from `.env`. No silent defaults — missing required vars cause immediate startup failure.

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` |
| `ADMIN_API_KEY` | Yes | Admin endpoint auth |
| `PUBLIC_SITE_BASE_URL` | Yes | Email link base URL |
| `AGENT_WS_MAX_CONNECTIONS` | Yes | WebSocket connection cap |
| `AGENT_WS_*` | Yes | WS timeouts |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` | Optional | Mail disabled if not set |
| `SMTP_FROM_ADDRESS`, `SMTP_FROM_NAME` | Optional | Sender identity |
| `VERIFY_CODE_TTL_SECONDS` | Yes | Code expiry |
| `VERIFY_CODE_RATE_LIMIT_*` | Yes | Per-email and per-IP limits |

See `backend/.env.example` for the full list with comments.

---

## Deployment

### Backend

`deploy-backend.sh`:
1. `rsync backend/` to EC2 working directory
2. Create Python venv, `pip install -r requirements.txt`
3. Install `deploy/zenheart-v2-backend.service` (systemd) and optional nginx config snippets
4. `systemctl restart`, health-check `GET /health`

Runs as: `uvicorn app.main:app --host 127.0.0.1 --port 8090`

nginx config (`deploy/nginx-v2-backend-location.conf`):
- `location /v2/` — proxy to upstream with WebSocket upgrade headers and long timeouts

### Frontend

`deploy-frontend.sh`:
1. `npm run build` (`vue-tsc -b && vite build`)
2. `rsync dist/` to nginx docroot
3. `nginx -t && nginx -s reload`

### News media (images)

Cover images for news articles are served as static files outside both the app and the frontend dist tree.

```
/opt/zenheart/news/
  images/          ← scp upload target; nginx alias serves /news/images/* from here
  markdown/        ← NEWS_MARKDOWN_ROOT; FastAPI writes/reads article markdown here
                     (under news_ws/<article-uuid-hex>.md for WS-published articles)
```

nginx snippet (`deploy/nginx-v2-backend-location.conf`):
```nginx
location /news/images/ {
    alias /opt/zenheart/news/images/;
    expires 7d;
    add_header Cache-Control "public";
}
```

A symlink at `$ZENHEART_WEB_DIR/news/images → /opt/zenheart/news/images` is maintained by `deploy-frontend.sh` (idempotent, survives `--delete` rsync). The nginx alias is the authoritative serving path; the symlink is a fallback via the server root.

Upload new cover images:
```bash
scp -i aws/zenheart-ec2.pem cover.png ec2-user@<host>:/opt/zenheart/news/images/
chmod 644 /opt/zenheart/news/images/cover.png
```

Then reference the image URL as `/news/images/cover.png` in the article's `cover_image_url` field.

### Database

PostgreSQL 16 runs in Docker Compose on the same EC2 host, bound to `127.0.0.1:5433`. No app container — systemd manages the FastAPI process.

```yaml
# backend/docker-compose.yml
postgres:16 → 127.0.0.1:5433:5432
  POSTGRES_USER: zenheart
  POSTGRES_DB: zenheart_v2
  volume: zenheart_v2_pg
```

### Local development

```bash
# Backend (requires .env and running postgres)
./dev-backend.sh        # uvicorn on :8090 with --reload

# Frontend
./dev-frontend.sh       # vite dev on :5173, proxies /v2/* to :8090
```

---

## Admin tooling

`backend/scripts/admin_agent_cli.py` — Python CLI that calls admin REST endpoints using `ADMIN_API_BASE_URL` + `ADMIN_API_KEY`. Used for remote agent management without direct server access. See `docs/agent-control.md` for usage.
