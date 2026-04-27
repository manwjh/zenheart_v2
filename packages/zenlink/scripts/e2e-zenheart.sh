#!/usr/bin/env bash
# End-to-end smoke on a machine that can reach ZenHeart (e.g. bot02 on your LAN).
# Set credentials only in the environment or a file you source — never commit secrets.
# Usage on bot02:
#   export ZENLINK_AGENT_ID=agt_…
#   export ZENLINK_TOKEN=…
#   ./e2e-zenheart.sh
# Optional: ZENLINK_HOST=… (defaults to zenheart.net)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${ZENLINK_HOST:=${ZENHEART_HOST:-${ZENHEART_V2_HOST:-zenheart.net}}}"
: "${ZENLINK_AGENT_ID:=${ZENHEART_AGENT_ID:-${ZENHEART_V2_AGENT_ID:-}}}"
: "${ZENLINK_TOKEN:=${ZENHEART_TOKEN:-${ZENHEART_V2_TOKEN:-}}}"

if [[ -z "$ZENLINK_AGENT_ID" || -z "$ZENLINK_TOKEN" ]]; then
  echo "error: set ZENLINK_AGENT_ID, ZENLINK_TOKEN (or ZENHEART_* / ZENHEART_V2_*)" >&2
  exit 1
fi

BASE="https://${ZENLINK_HOST}"
if [[ "${ZENLINK_USE_TLS:-1}" == "0" || "${ZENHEART_USE_TLS:-}" == "0" ]]; then
  BASE="http://${ZENLINK_HOST}"
fi

echo "== 1) HTTP $BASE/v2/health"
curl -sS -o /tmp/zh-health.txt -w "http_code=%{http_code}\n" "$BASE/v2/health" || true
head -c 500 /tmp/zh-health.txt; echo
echo

echo "== 2) WebSocket auth (zenlink CLI)"
if [[ -f "$ROOT/dist/cli.js" ]]; then
  node "$ROOT/dist/cli.js"
else
  echo "no dist/cli.js — run: cd \"$ROOT\" && npm ci && npm run build" >&2
  npm ci
  npm run build
  node "$ROOT/dist/cli.js"
fi

echo
echo "e2e-zenheart.sh: done"
