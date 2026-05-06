#!/usr/bin/env bash
# Build offline tarball + npm pack, refresh frontend manifest, upload to EC2 web dir.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ZENLINK_MCP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGES_DIR="$(cd "${ZENLINK_MCP_DIR}/.." && pwd)"
V2_ROOT="$(cd "${ZENLINK_MCP_DIR}/../.." && pwd)"
REPO_ROOT="$(cd "${V2_ROOT}/.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }

require_env() {
  local key="$1"
  [[ -n "${!key:-}" ]] || die "missing required env: ${key}"
}

if [[ -f "${V2_ROOT}/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${V2_ROOT}/.deploy-env"
  set +a
fi

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-${REPO_ROOT}/aws/zenheart-ec2.pem}"
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
ZENHEART_WEB_DIR="${ZENHEART_WEB_DIR:-/opt/zenheart/frontend}"

require_env ZENHEART_EC2_HOST
require_env ZENHEART_SSH_KNOWN_HOSTS
[[ -f "${ZENHEART_EC2_KEY}" ]] || die "missing SSH key: ${ZENHEART_EC2_KEY}"
[[ -f "${ZENHEART_SSH_KNOWN_HOSTS}" ]] || die "missing known_hosts file: ${ZENHEART_SSH_KNOWN_HOSTS}"

SSH_CMD=(
  ssh -i "${ZENHEART_EC2_KEY}"
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${ZENHEART_SSH_KNOWN_HOSTS}"
  -o GlobalKnownHostsFile=/dev/null
  -o BatchMode=yes
  -o ConnectTimeout=15
)
SCP_CMD=(
  scp -i "${ZENHEART_EC2_KEY}"
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${ZENHEART_SSH_KNOWN_HOSTS}"
  -o GlobalKnownHostsFile=/dev/null
  -o BatchMode=yes
  -o ConnectTimeout=15
)

echo "[publish] offline tarball (registry only on builder)"
( cd "${ZENLINK_MCP_DIR}" && npm run pack:offline )

echo "[publish] npx tarball"
( cd "${ZENLINK_MCP_DIR}" && npm run pack:npx )

echo "[publish] refresh frontend zenlink manifest"
( cd "${V2_ROOT}/frontend" && node scripts/sync-zenlink-public.mjs )

VERSION="$(node -p "require('${ZENLINK_MCP_DIR}/package.json').version")"
OFF="${PACKAGES_DIR}/zenlink-mcp-offline-v${VERSION}.tar.gz"

NXP="${ZENLINK_MCP_DIR}/npx-dist/zenlink-mcp.tgz"
MANIFEST="${V2_ROOT}/frontend/public/zenlink/release-manifest.json"

[[ -f "${OFF}" ]] || die "missing offline tarball: ${OFF}"
[[ -f "${NXP}" ]] || die "missing npm pack: ${NXP}"
[[ -f "${MANIFEST}" ]] || die "missing release manifest: ${MANIFEST}"

echo "[publish] upload to ${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}"
"${SSH_CMD[@]}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}" \
  "sudo mkdir -p '${ZENHEART_WEB_DIR}/zenlink'"

"${SCP_CMD[@]}" "${OFF}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/zenlink-mcp-offline.tar.gz.part"
"${SCP_CMD[@]}" "${NXP}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/zenlink-mcp.tgz"
"${SCP_CMD[@]}" "${MANIFEST}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/zenlink-release-manifest.json"

"${SSH_CMD[@]}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}" \
  env ZENHEART_WEB_DIR="${ZENHEART_WEB_DIR}" bash -s <<'REMOTE'
set -euo pipefail
sudo mv "$HOME/zenlink-mcp-offline.tar.gz.part" "${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp-offline.tar.gz"
sudo mv "$HOME/zenlink-mcp.tgz" "${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp.tgz"
sudo mv "$HOME/zenlink-release-manifest.json" "${ZENHEART_WEB_DIR}/zenlink/release-manifest.json"
REMOTE

echo "[publish] uploaded:"
echo "  ${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp-offline.tar.gz"
echo "  ${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp.tgz"
echo "  ${ZENHEART_WEB_DIR}/zenlink/release-manifest.json"
