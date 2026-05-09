#!/usr/bin/env bash
# Build OpenClaw tarballs + self-extracting installers, refresh frontend manifest, upload versioned files to EC2 web dir.
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

echo "[publish] OpenClaw tarballs + installers (registry only on builder)"
( cd "${ZENLINK_MCP_DIR}" && npm run pack:offline )

echo "[publish] refresh frontend zenlink manifest"
( cd "${V2_ROOT}/frontend" && node scripts/sync-zenlink-public.mjs )

VERSION="$(node -p "require('${ZENLINK_MCP_DIR}/package.json').version")"
OFF_MACOS="${PACKAGES_DIR}/zenlink-mcp-openclaw-macos-v${VERSION}.tar.gz"
OFF_LINUX="${PACKAGES_DIR}/zenlink-mcp-openclaw-linux-v${VERSION}.tar.gz"
INSTALL_MACOS="${PACKAGES_DIR}/install-zenlink-mcp-openclaw-macos-v${VERSION}.sh"
INSTALL_LINUX="${PACKAGES_DIR}/install-zenlink-mcp-openclaw-linux-v${VERSION}.sh"
MANIFEST="${V2_ROOT}/frontend/public/zenlink/release-manifest.json"

[[ -f "${OFF_MACOS}" ]] || die "missing tarball: ${OFF_MACOS}"
[[ -f "${OFF_LINUX}" ]] || die "missing tarball: ${OFF_LINUX}"
[[ -f "${INSTALL_MACOS}" ]] || die "missing installer: ${INSTALL_MACOS}"
[[ -f "${INSTALL_LINUX}" ]] || die "missing installer: ${INSTALL_LINUX}"
[[ -f "${MANIFEST}" ]] || die "missing release manifest: ${MANIFEST}"

echo "[publish] upload to ${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}"
"${SSH_CMD[@]}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}" \
  "sudo mkdir -p '${ZENHEART_WEB_DIR}/zenlink'"

"${SCP_CMD[@]}" "${OFF_MACOS}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/openclaw-macos-v${VERSION}.tar.gz.part"
"${SCP_CMD[@]}" "${OFF_LINUX}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/openclaw-linux-v${VERSION}.tar.gz.part"
"${SCP_CMD[@]}" "${INSTALL_MACOS}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/install-openclaw-macos-v${VERSION}.sh.part"
"${SCP_CMD[@]}" "${INSTALL_LINUX}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/install-openclaw-linux-v${VERSION}.sh.part"
"${SCP_CMD[@]}" "${MANIFEST}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}:~/zenlink-release-manifest.json"

"${SSH_CMD[@]}" "${ZENHEART_EC2_USER}@${ZENHEART_EC2_HOST}" \
  env \
    ZENHEART_WEB_DIR="${ZENHEART_WEB_DIR}" \
    VERSION="${VERSION}" \
  bash -s <<'REMOTE'
set -euo pipefail
W="${ZENHEART_WEB_DIR:?}/zenlink"
sudo mv "$HOME/openclaw-macos-v${VERSION}.tar.gz.part" "${W}/zenlink-mcp-openclaw-macos-v${VERSION}.tar.gz"
sudo mv "$HOME/openclaw-linux-v${VERSION}.tar.gz.part" "${W}/zenlink-mcp-openclaw-linux-v${VERSION}.tar.gz"
sudo mv "$HOME/install-openclaw-macos-v${VERSION}.sh.part" "${W}/install-zenlink-mcp-openclaw-macos-v${VERSION}.sh"
sudo mv "$HOME/install-openclaw-linux-v${VERSION}.sh.part" "${W}/install-zenlink-mcp-openclaw-linux-v${VERSION}.sh"
sudo chmod 755 \
  "${W}/install-zenlink-mcp-openclaw-macos-v${VERSION}.sh" \
  "${W}/install-zenlink-mcp-openclaw-linux-v${VERSION}.sh"
sudo mv "$HOME/zenlink-release-manifest.json" "${W}/release-manifest.json"
REMOTE

echo "[publish] uploaded (version v${VERSION}):"
echo "  ${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp-openclaw-macos-v${VERSION}.tar.gz"
echo "  ${ZENHEART_WEB_DIR}/zenlink/zenlink-mcp-openclaw-linux-v${VERSION}.tar.gz"
echo "  ${ZENHEART_WEB_DIR}/zenlink/install-zenlink-mcp-openclaw-macos-v${VERSION}.sh"
echo "  ${ZENHEART_WEB_DIR}/zenlink/install-zenlink-mcp-openclaw-linux-v${VERSION}.sh"
echo "  ${ZENHEART_WEB_DIR}/zenlink/release-manifest.json"
