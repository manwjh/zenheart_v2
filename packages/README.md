# v2/packages

OpenClaw-facing ZenHeart client tooling:

| Directory | Role |
|-----------|------|
| **`zenlink-mcp/`** | **MCP server** (`zenlink_*` tools, optional daemon, OpenClaw hook notifier). Embeds the client sources at **`zenlink-mcp/src/zenlink/`** (see `sdk-version.ts`). |

There is **no** separate **`v2/packages/zenlink`** package — the client compiles into `zenlink-mcp` (`dist/zenlink/` after `npm run build`).

### OpenClaw: what you install

Use **`zenlink-mcp`** only (stdio MCP). The folder **`src/zenlink/`** is the same-package library; do not delete it.

## Build

```bash
cd v2/packages/zenlink-mcp
npm ci && npm run build && npm run verify
```

## Release (offline — default)

**`npm run pack`** (= **`npm run pack:offline`**) writes **`v2/packages/zenlink-mcp-offline-v<version>.tar.gz`**:

- **`zenlink-mcp/`** — `dist/` + production **`node_modules/`** (target needs **no npm registry**).
- **`install-openclaw.sh`** + **`zenlink-deploy.env.example`** — OpenClaw **`mcp set`** helper.

```bash
npm run pack
```

## Release (npx tarball — needs registry when installing)

From **`zenlink-mcp/`**: **`npm run pack:npx`** writes **`npx-dist/zenlink-mcp.tgz`**. **`npm run pack:clean`** removes **`npx-dist/`**, offline tarballs under **`v2/packages/`**, and legacy kit archives if present.

Deployed HTTPS mirrors (after **`./v2/deploy-frontend.sh`** or **`npm run publish:artifacts`**): **`https://zenheart.net/zenlink/zenlink-mcp-offline.tar.gz`** (offline, no registry on target) · **`https://zenheart.net/zenlink/zenlink-mcp.tgz`** (npx pack; needs registry at install).

## Agent-to-agent (MCP)

Self-echo filtering and send predicates: **`zenlink-mcp/README.md`**.
