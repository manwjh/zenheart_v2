#!/usr/bin/env bash
# Build npm pack tarball (registry-oriented); OpenClaw operators use offline pack instead.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT}"
mkdir -p npx-dist
# Remove only versioned outputs so the glob after npm pack matches exactly one file.
rm -f npx-dist/zenlink-mcp-[0-9]*.tgz
npm pack --pack-destination npx-dist >/dev/null
shopt -s nullglob
PACKED=(npx-dist/zenlink-mcp-*.tgz)
shopt -u nullglob
if [[ ${#PACKED[@]} -ne 1 ]]; then
  echo "error: expected exactly one zenlink-mcp-*.tgz under npx-dist/ after npm pack (got ${#PACKED[@]})" >&2
  exit 1
fi
TARGET="${ROOT}/npx-dist/zenlink-mcp.tgz"
mv -f "${PACKED[0]}" "${TARGET}"
echo "Wrote ${TARGET}"
