# Embedded client (`src/zenlink`)

This directory is **part of the `zenlink-mcp` package**, not a separate npm project. OpenClaw users install and run **only `zenlink-mcp`**; they do not add another “zenlink” package.

What lives here: the ZenHeart **WebSocket + agent HTTP** client (`managed-connection`, `client`, `http`, …). MCP code imports it via relative paths (e.g. `../zenlink/index.js`). Build output goes to **`dist/zenlink/`** next to **`dist/cli.js`**.

Version label for release notes: **`ZENLINK_SDK_VERSION`** in `sdk-version.ts` (not a second package version in `package.json`).
