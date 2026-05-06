#!/usr/bin/env bash
# Remove npm pack output and legacy kit tarballs under v2/packages/.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGES_DIR="$(cd "${ROOT}/.." && pwd)"

rm -rf "${ROOT}/npx-dist"
rm -rf "${ROOT}/offline-dist"
rm -f "${PACKAGES_DIR}"/zenheart-openclaw-zenlink-kit-*.tar.gz 2>/dev/null || true
rm -f "${PACKAGES_DIR}"/zenlink-mcp-offline-v*.tar.gz 2>/dev/null || true

echo "Removed npx-dist/, offline-dist/, and legacy kit / offline tarballs under ${PACKAGES_DIR} (if any)."
