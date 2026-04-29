# v2/packages — Zenlink

Forward layout for **Node 18+** clients that talk to ZenHeart v2 (`/v2/agent/ws` + agent HTTP).

## Layout

| Directory | Role |
|-----------|------|
| **`zenlink/`** | **SDK** — `ZenlinkClient`, HTTP helpers, CLI smoke. Use from any Node service; publish path remains `zenlink-source.tar.gz` on the site. |
| **`zenlink-mcp/`** | **OpenClaw MCP** — stdio server exposing `zenlink_*` tools + optional Gateway **`/hooks/wake`** push. |
| **`zenlink-mcp/skill/`** | **OpenClaw skill** (`zenlink`) — `SKILL.md` + `skill.json` only. Install copy at **`workspaces/skills/zenlink`**. Kits still ship **`skills/zenlink/`** for the same two files. |

There is **no third top-level package** for the skill; it ships **with** the MCP tree to keep the integration unit single-sourced.

## Build order

```bash
cd zenlink && npm ci && npm run build
cd ../zenlink-mcp && npm ci && npm run build && npm run smoke:tools
```

Or from `zenlink-mcp`: `npm run verify` (builds peer `zenlink` then MCP).

## Release kits

From **`zenlink-mcp/`**:

- `npm run bundle:source` — `zenheart-openclaw-zenlink-kit-src-*.tar.gz` in **`v2/packages/`**
- `npm run bundle:offline` — `zenheart-openclaw-zenlink-kit-offline-*.tar.gz` in **`v2/packages/`**

See **`zenlink-mcp/README.md`** and **`zenlink-mcp/INTEGRATION.md`**.
