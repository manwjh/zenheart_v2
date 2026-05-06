#!/usr/bin/env bash
# Build zenlink-mcp from source (embeds SDK at src/zenlink/).
# Kit layout: single top-level **zenlink-mcp/**, or monorepo **v2/packages/zenlink-mcp/**.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_root() {
  # Explicit kit root with zenlink-mcp/
  if [[ -n "${1:-}" && -d "$1/zenlink-mcp" ]]; then
    cd "$1" && pwd
    return
  fi
  # install.sh copied next to zenlink-mcp/
  if [[ -f "${SCRIPT_DIR}/zenlink-mcp/package.json" ]]; then
    echo "${SCRIPT_DIR}"
    return
  fi
  # Monorepo: .../packages/zenlink-mcp
  local mcp_root
  mcp_root="$(cd "${SCRIPT_DIR}/.." && pwd)"
  if [[ -f "${mcp_root}/package.json" ]] && [[ -f "${mcp_root}/src/zenlink/sdk-version.ts" ]]; then
    echo "${mcp_root}"
    return
  fi
  echo ""
}

ROOT="$(resolve_root "$@")"
if [[ -z "${ROOT}" ]]; then
  echo "error: could not find zenlink-mcp (embedded SDK expected at src/zenlink/)." >&2
  exit 1
fi

if [[ -f "${ROOT}/zenlink-mcp/package.json" ]]; then
  ZM="${ROOT}/zenlink-mcp"
elif [[ -f "${ROOT}/package.json" ]] && [[ -f "${ROOT}/src/zenlink/sdk-version.ts" ]]; then
  ZM="${ROOT}"
else
  echo "error: unsupported tree at ${ROOT}" >&2
  exit 1
fi

echo "Using zenlink-mcp at: ${ZM}"

echo "==> npm ci && npm run build"
( cd "${ZM}" && npm ci && npm run build && chmod +x dist/cli.js )

echo "==> verify"
( cd "${ZM}" && npm run verify )

echo "==> cli sanity"
( cd "${ZM}" && node dist/cli.js --help >/dev/null )

echo "OK. Next:"
echo "  1) export ZENLINK_AGENT_ID=... ZENLINK_TOKEN=..."
echo "  2) Register MCP per zenlink-mcp/README.md"
echo "  3) Start OpenClaw / MCP host"
