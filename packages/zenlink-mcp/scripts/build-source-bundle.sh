#!/usr/bin/env bash
# ZenHeart ↔ OpenClaw integration kit (source): zenlink SDK + zenlink-mcp + OpenClaw skill (staged as skills/zenlink/).
# No node_modules / dist — targets run npm ci locally.
# Default output: v2/packages/<KIT_ROOT_NAME>.tar.gz — override with first CLI arg.
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
  echo "error: expected OpenClaw skill at ${SKILL_ZENLINK_SRC} (SKILL.md + skill.json)" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT

MCP_VERSION="$(node -p "require('${ZENLINK_MCP_SRC}/package.json').version")"
ZENLINK_VERSION="$(node -p "require('${ZENLINK_SRC}/package.json').version")"
SKILL_VERSION="$(node -p "require('${SKILL_ZENLINK_SRC}/skill.json').version")"

# One top-level directory name = archive basename (without .tar.gz); reflects full kit, not "mcp-only".
KIT_ROOT_NAME="zenheart-openclaw-zenlink-kit-src-v${MCP_VERSION}-zenlink-v${ZENLINK_VERSION}-skill-v${SKILL_VERSION}"
BUNDLE_TOP="${STAGE}/${KIT_ROOT_NAME}"
mkdir -p "${BUNDLE_TOP}/zenlink" "${BUNDLE_TOP}/zenlink-mcp" "${BUNDLE_TOP}/skills/zenlink"

echo "Staging sources (excluding build artifacts)..."

tar_exclude=(
  --exclude=node_modules
  --exclude=dist
  --exclude=offline-dist
  --exclude=source-dist
  --exclude='.DS_Store'
)

( cd "${ZENLINK_SRC}" && tar cf - "${tar_exclude[@]}" . ) | ( cd "${BUNDLE_TOP}/zenlink" && tar xf - )
( cd "${ZENLINK_MCP_SRC}" && tar cf - "${tar_exclude[@]}" . ) | ( cd "${BUNDLE_TOP}/zenlink-mcp" && tar xf - )
( cd "${SKILL_ZENLINK_SRC}" && tar cf - SKILL.md skill.json ) | ( cd "${BUNDLE_TOP}/skills/zenlink" && tar xf - )

cat > "${BUNDLE_TOP}/README-KIT.txt" <<EOF
ZenHeart ↔ OpenClaw zenlink integration kit (source)
=====================================================

This archive is the **full integration bundle**: ZenHeart SDK (**zenlink/**), MCP server (**zenlink-mcp/**),
and OpenClaw skill (**skills/zenlink/**). It is **not** “zenlink-mcp alone.”

Versions:
  zenlink:       ${ZENLINK_VERSION}
  zenlink-mcp:   ${MCP_VERSION}
  zenlink skill: ${SKILL_VERSION} (OpenClaw SKILL.md + skill.json)

Requirements:
  Node.js 18+
  npm (or compatible) with access to the npm registry for dependencies

Build (from this directory):

  cd zenlink && npm ci && npm run build
  cd ../zenlink-mcp && npm ci && npm run build

Run MCP stdio (expects a **running daemon** by default — see “mandatory” section above):

  export ZENLINK_AGENT_ID=...
  export ZENLINK_TOKEN=...
  cd zenlink-mcp && npm run daemon
  # Leave that process running — in another terminal or via launchd:
  # cd zenlink-mcp && node dist/cli.js   # MCP stdio for OpenClaw

Build already ran `npm run build`; `npm run daemon` is `node dist/cli.js --daemon`.

zenlink-mcp depends on zenlink via "file:../zenlink" — keep both folders as siblings under this kit root.

OpenClaw skill: copy the folder skills/zenlink into your workspace as workspaces/skills/zenlink (slug zenlink), or register skills/zenlink on your host, so agents load env and zenlink-mcp/INTEGRATION.md guidance.

Upgrade: replace this tree or unpack a newer kit archive; rebuild zenlink then zenlink-mcp; restart MCP host.

Uninstall: remove MCP server from host config; delete unpacked kit directory if unused.
EOF

ARCHIVE="${KIT_ROOT_NAME}.tar.gz"
mkdir -p "${OUT_DIR}"
( cd "${STAGE}" && tar czf "${OUT_DIR}/${ARCHIVE}" "${KIT_ROOT_NAME}" )

echo "Wrote ${OUT_DIR}/${ARCHIVE}"
ls -la "${OUT_DIR}/${ARCHIVE}"
