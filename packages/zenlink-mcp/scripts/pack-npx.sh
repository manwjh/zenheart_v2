#!/usr/bin/env bash
# Single release artifact: npm pack tarball for `npx --yes ./zenlink-mcp-*.tgz`.
# Output: npx-dist/zenlink-mcp-<version>.tgz and npx-dist/zenlink-mcp.tgz (copy).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${1:-"${ROOT}/npx-dist"}"

mkdir -p "${OUT_DIR}"
echo "==> npm pack -> ${OUT_DIR}"
( cd "${ROOT}" && npm pack --pack-destination "${OUT_DIR}" )

VERSION="$(node -p "require('${ROOT}/package.json').version")"
TGZ="zenlink-mcp-${VERSION}.tgz"
[[ -f "${OUT_DIR}/${TGZ}" ]] || {
  echo "error: expected ${OUT_DIR}/${TGZ}" >&2
  exit 1
}
cp -f "${OUT_DIR}/${TGZ}" "${OUT_DIR}/zenlink-mcp.tgz"
echo "OK: ${OUT_DIR}/${TGZ}"
echo "OK: ${OUT_DIR}/zenlink-mcp.tgz (stable name)"
