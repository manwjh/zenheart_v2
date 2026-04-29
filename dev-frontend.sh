#!/usr/bin/env bash
# Terminal 2 — Vite dev server :5173 (proxies /v2 → http://127.0.0.1:8090).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/frontend"
if [[ ! -d node_modules ]]; then
  npm install
fi
exec npm run dev
