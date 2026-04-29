#!/usr/bin/env bash
# ZenHeart ↔ OpenClaw integration kit (offline): zenlink + zenlink-mcp + OpenClaw skill (staged as skills/zenlink/) + production node_modules.
# Run on a machine with npm registry once; unpack target needs Node 18+ only.
# Default output: v2/packages/<archive>.tar.gz — override with first CLI arg.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGES_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ZENLINK_SRC="${PACKAGES_DIR}/zenlink"
ZENLINK_MCP_SRC="${PACKAGES_DIR}/zenlink-mcp"
SKILL_ZENLINK_SRC="${ZENLINK_MCP_SRC}/skill"
OUT_DIR="${1:-"${PACKAGES_DIR}"}"

if [[ ! -f "${ZENLINK_SRC}/package.json" ]] || [[ ! -f "${ZENLINK_MCP_SRC}/package.json" ]]; then
  echo "error: expected zenlink and zenlink-mcp under ${PACKAGES_DIR}" >&2
  exit 1
fi
if [[ ! -f "${SKILL_ZENLINK_SRC}/skill.json" ]] || [[ ! -f "${SKILL_ZENLINK_SRC}/SKILL.md" ]]; then
  echo "error: expected OpenClaw skill at ${SKILL_ZENLINK_SRC}" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT

# Stable unpack path (no OS in folder name); archive filename encodes OS/arch.
KIT_ROOT_NAME="zenheart-openclaw-zenlink-kit-offline"
BUNDLE_TOP="${STAGE}/${KIT_ROOT_NAME}"
mkdir -p "${BUNDLE_TOP}/zenlink" "${BUNDLE_TOP}/zenlink-mcp" "${BUNDLE_TOP}/skills/zenlink"

echo "Staging sources..."
( cd "${ZENLINK_SRC}" && tar cf - --exclude=node_modules --exclude=dist . ) | ( cd "${BUNDLE_TOP}/zenlink" && tar xf - )
( cd "${ZENLINK_MCP_SRC}" && tar cf - --exclude=node_modules --exclude=dist --exclude=offline-dist --exclude=source-dist . ) | ( cd "${BUNDLE_TOP}/zenlink-mcp" && tar xf - )
( cd "${SKILL_ZENLINK_SRC}" && tar cf - SKILL.md skill.json ) | ( cd "${BUNDLE_TOP}/skills/zenlink" && tar xf - )

echo "Installing and building zenlink..."
( cd "${BUNDLE_TOP}/zenlink" && npm ci && npm run build && npm prune --omit=dev )

echo "Installing and building zenlink-mcp..."
( cd "${BUNDLE_TOP}/zenlink-mcp" && npm ci && npm run build && npm prune --omit=dev )

VERSION="$(node -p "require('${BUNDLE_TOP}/zenlink-mcp/package.json').version")"
SKILL_VERSION="$(node -p "require('${SKILL_ZENLINK_SRC}/skill.json').version")"
OS_LABEL="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH_LABEL="$(uname -m)"
ARCHIVE="zenheart-openclaw-zenlink-kit-offline-v${VERSION}-${OS_LABEL}-${ARCH_LABEL}.tar.gz"

cat > "${BUNDLE_TOP}/README-KIT.txt" <<EOF
ZenHeart ↔ OpenClaw zenlink integration kit (offline)
======================================================

Full bundle: **zenlink/** (SDK), **zenlink-mcp/** (MCP server), **skills/zenlink/** (OpenClaw skill).

Versions:
  zenlink-mcp (kit anchor): ${VERSION}
  zenlink skill:             ${SKILL_VERSION}

Requirements on the unpack machine:
  Node.js 18+ only — no npm registry after unpack

Run MCP server:

  export ZENLINK_AGENT_ID=...
  export ZENLINK_TOKEN=...
  node zenlink-mcp/dist/cli.js

(from directory ${KIT_ROOT_NAME}/)

Optional env: ZENLINK_HOST, ZENLINK_USE_TLS, ZENLINK_MCP_* (see zenlink-mcp/README.md)

OpenClaw: register MCP server pointing Node at zenlink-mcp/dist/cli.js; install this skill under **workspaces/skills/zenlink** (from **skills/zenlink** in this kit).

Note: node_modules built on host OS/arch — use a bundle built for the same class (e.g. darwin-arm64 vs linux-x64).

Upgrade: unpack newer kit archive; update MCP path; restart host.

Uninstall: remove MCP entry; delete unpacked **${KIT_ROOT_NAME}/** if unused.
EOF

BUILD_LABEL="${OS_LABEL}-${ARCH_LABEL}"
echo "" >> "${BUNDLE_TOP}/README-KIT.txt"
echo "BUILD_LABEL=${BUILD_LABEL}" >> "${BUNDLE_TOP}/README-KIT.txt"

mkdir -p "${OUT_DIR}"
( cd "${STAGE}" && tar czf "${OUT_DIR}/${ARCHIVE}" "${KIT_ROOT_NAME}" )

echo "Wrote ${OUT_DIR}/${ARCHIVE}"
ls -la "${OUT_DIR}/${ARCHIVE}"
