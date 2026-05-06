#!/usr/bin/env bash
# Offline install bundle for OpenClaw: zenlink-mcp + production node_modules + register script.
# Build on a machine with npm registry access once; target can be air-gapped for npm.
# Does not modify the developer's node_modules (prune runs only on a staged copy).
# Output: v2/packages/zenlink-mcp-offline-v<version>.tar.gz (default) or path given as $1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PACKAGES_DIR="$(cd "${ROOT}/.." && pwd)"
OUT_FILE="${1:-"${PACKAGES_DIR}/zenlink-mcp-offline-v$(node -p "require('${ROOT}/package.json').version").tar.gz"}"

cd "${ROOT}"
echo "==> npm ci (needs registry on this build machine)"
npm ci
echo "==> npm run build"
npm run build

STAGE="$(mktemp -d)"
cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT

VERSION="$(node -p "require('${ROOT}/package.json').version")"
TOP="zenlink-mcp-offline-v${VERSION}"
DEST="${STAGE}/${TOP}/zenlink-mcp"
mkdir -p "${DEST}/scripts"

cp "${ROOT}/package.json" "${DEST}/"
cp -R "${ROOT}/dist" "${DEST}/"
cp -R "${ROOT}/node_modules" "${DEST}/"

echo "==> production node_modules only (staged copy; your repo tree is unchanged)"
( cd "${DEST}" && npm prune --omit=dev )

cp "${ROOT}/scripts/register-openclaw.mjs" "${DEST}/scripts/"
cp "${ROOT}/scripts/openclaw-json-helpers.mjs" "${DEST}/scripts/"
cp "${ROOT}/scripts/openclaw-zenlink-daemon.mjs" "${DEST}/scripts/"
cp "${ROOT}/scripts/launchd-zenlink-mcp-daemon.example.plist" "${STAGE}/${TOP}/"

cat > "${STAGE}/${TOP}/README-OFFLINE.txt" <<EOF
ZenHeart zenlink-mcp — offline bundle for OpenClaw
===================================================

Contents:
  zenlink-mcp/              MCP package: dist/, node_modules/ (production), package.json, scripts/
  install-openclaw.sh       Registers stdio MCP (openclaw mcp set; persists hook + daemon forwarding env)
  upgrade-offline-install.sh   Optional: install/upgrade into a fixed directory (~/.openclaw/zenlink-mcp/current)
  zenlink-deploy.env.example   Copy to zenlink-deploy.env and fill credentials + hook URL/token
  launchd-zenlink-mcp-daemon.example.plist   macOS launchd: use absolute paths (see comments; avoid versioned /tmp extract paths)

Requirements on the target machine:
  - Node.js 18+
  - openclaw CLI available as "openclaw" (for install-openclaw.sh)
  - No public npm registry required for running MCP (dependencies are bundled under zenlink-mcp/node_modules).

Recommended fixed path (launchd / upgrades):
  bash upgrade-offline-install.sh zenlink-mcp-offline-v${VERSION}.tar.gz
  cd "\${HOME}/.openclaw/zenlink-mcp/current" && bash install-openclaw.sh
  node zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs start
  # Restart OpenClaw Gateway if it was already running (so MCP workers reload).

One-command style (extract anywhere):
  1. tar xzf zenlink-mcp-offline-v${VERSION}.tar.gz
  2. cd zenlink-mcp-offline-v${VERSION}
  3. cp zenlink-deploy.env.example zenlink-deploy.env   # edit: agent id, token, hooks
  4. bash install-openclaw.sh

install-openclaw.sh auto-loads, if present: zenlink-deploy.env then .env (KEY=value exports).
It defaults ZENLINK_MCP_USE_DAEMON=1 and ZENLINK_MCP_DAEMON_ADDR_FILE=\${HOME}/.openclaw/tmp/zenlink-mcp-daemon.addr when unset (written into openclaw.json). Opt out: ZENLINK_MCP_USE_DAEMON=0 in zenlink-deploy.env, or ZENLINK_MCP_NO_DEFAULT_DAEMON=1 for a single run.

After you edit zenlink-deploy.env (hooks, token, wake), run install-openclaw.sh again so ~/.openclaw/openclaw.json mcp.servers.*.env is updated — that is what OpenClaw-hosted MCP workers read, NOT the .env file alone.

You must keep zenlink-mcp --daemon running when USE_DAEMON=1: use openclaw-zenlink-daemon.mjs (in zenlink-mcp/scripts/) or launchd.

OpenClaw hooks: Gateway must expose POST /hooks/wake with hooks.token matching ZENLINK_MCP_OPENCLAW_HOOK_TOKEN.
register-openclaw.mjs merges hooks.token from openclaw.json when unset; ZENLINK_MCP_OPENCLAW_WAKE_MODE defaults to "now" when base+token are present.
If hooks are missing, run: openclaw hooks init   (then re-run install-openclaw.sh).

Minimal without env file:
  export ZENLINK_AGENT_ID=... ZENLINK_TOKEN=...
  export ZENLINK_MCP_OPENCLAW_HOOK_BASE=... ZENLINK_MCP_OPENCLAW_HOOK_TOKEN=...
  bash install-openclaw.sh   # still defaults USE_DAEMON + ADDR_FILE into openclaw.json unless NO_DEFAULT_DAEMON=1

Manual MCP command (no OpenClaw CLI): point mcp.servers at:
  command: node
  args: [ "<absolute-path>/zenlink-mcp/dist/cli.js" ]
  env: { ZENLINK_AGENT_ID, ZENLINK_TOKEN, ... }

Optional: global CLI from this folder (still offline if node_modules is present):
  npm install -g ./zenlink-mcp --offline --no-audit
EOF

cat > "${STAGE}/${TOP}/zenlink-deploy.env.example" <<'ENVEOF'
# Copy to zenlink-deploy.env (same folder as install-openclaw.sh). install-openclaw.sh loads it automatically.
ZENLINK_AGENT_ID=
ZENLINK_TOKEN=

# Optional: OpenClaw wake (set both hook lines or omit both — required for zenlink_status.openclaw_push.enabled)
# Base URL for hooks directory (no trailing /wake needed; zenlink-mcp appends /wake).
ZENLINK_MCP_OPENCLAW_HOOK_BASE=http://127.0.0.1:18789/hooks
ZENLINK_MCP_OPENCLAW_HOOK_TOKEN=
# When BASE+TOKEN are set, install/register default wake to "now" unless you override below.
ZENLINK_MCP_OPENCLAW_WAKE_MODE=now

# Daemon forwarding (defaults applied by install-openclaw.sh when lines are omitted — still set explicitly if you prefer)
ZENLINK_MCP_USE_DAEMON=1
ZENLINK_MCP_DAEMON_ADDR_FILE=$HOME/.openclaw/tmp/zenlink-mcp-daemon.addr

# Typical extras (uncomment if needed):
# ZENLINK_MCP_LONG_LIVED=1
# ZENLINK_MCP_OPENCLAW_PUSH_FRAME_TYPES=message,msgbox_notify,social_notify
# ZENLINK_MCP_OPENCLAW_WAKE_COALESCE_ROOM_MESSAGE_MS=2000   # one wake per room line (message + notify preview); 0=disable
ENVEOF

cat > "${STAGE}/${TOP}/install-openclaw.sh" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP="${ROOT}/zenlink-mcp"

load_env_files() {
  local f any=0
  for f in "${ROOT}/zenlink-deploy.env" "${ROOT}/.env"; do
    if [[ -f "$f" ]]; then
      echo "loading: $f"
      set -a
      # shellcheck disable=SC1090
      source "$f"
      set +a
      any=1
    fi
  done
  if [[ "$any" -eq 0 ]]; then
    return 1
  fi
  return 0
}

if ! load_env_files; then
  echo "note: no zenlink-deploy.env or .env next to install-openclaw.sh — using current shell exports only."
  echo "hint: cp zenlink-deploy.env.example zenlink-deploy.env && edit, then re-run."
fi

apply_default_daemon_forwarding() {
  if [[ "${ZENLINK_MCP_NO_DEFAULT_DAEMON:-}" == "1" ]]; then
    return 0
  fi
  local did=0
  if [[ -z "${ZENLINK_MCP_USE_DAEMON// }" ]]; then
    export ZENLINK_MCP_USE_DAEMON=1
    did=1
  fi
  if [[ -z "${ZENLINK_MCP_DAEMON_ADDR_FILE// }" ]]; then
    export ZENLINK_MCP_DAEMON_ADDR_FILE="${HOME}/.openclaw/tmp/zenlink-mcp-daemon.addr"
    did=1
  fi
  mkdir -p "$(dirname "${ZENLINK_MCP_DAEMON_ADDR_FILE}")"
  if [[ "$did" -eq 1 ]]; then
    echo "note: defaulted daemon forwarding for OpenClaw stdio MCP (ZENLINK_MCP_USE_DAEMON=${ZENLINK_MCP_USE_DAEMON}, ZENLINK_MCP_DAEMON_ADDR_FILE=${ZENLINK_MCP_DAEMON_ADDR_FILE})."
    echo "      Persisted by register into mcp.servers.*.env — keep \"zenlink-mcp --daemon\" running:"
    echo "      node \"${MCP}/scripts/openclaw-zenlink-daemon.mjs\" start"
    echo "      Opt out: ZENLINK_MCP_USE_DAEMON=0 in zenlink-deploy.env, or export ZENLINK_MCP_NO_DEFAULT_DAEMON=1 for this run only."
  fi
}
apply_default_daemon_forwarding

if [[ ! -f "${MCP}/dist/cli.js" ]]; then
  echo "error: missing ${MCP}/dist/cli.js" >&2
  exit 1
fi
if [[ ! -d "${MCP}/node_modules" ]]; then
  echo "error: missing ${MCP}/node_modules (invalid offline bundle)" >&2
  exit 1
fi

HB="${ZENLINK_MCP_OPENCLAW_HOOK_BASE:-}"
HT="${ZENLINK_MCP_OPENCLAW_HOOK_TOKEN:-}"
if [[ -z "${HB// }" || -z "${HT// }" ]]; then
  echo "warning: OpenClaw push disabled until both ZENLINK_MCP_OPENCLAW_HOOK_BASE and ZENLINK_MCP_OPENCLAW_HOOK_TOKEN are set."
  echo "        Fix: add them to zenlink-deploy.env or export before this script; re-run this script after editing."
  echo "        (launchd and other supervisors do not source zenlink-deploy.env — see launchd-zenlink-mcp-daemon.example.plist)"
else
  if [[ -z "${ZENLINK_MCP_OPENCLAW_WAKE_MODE+x}" ]]; then
    export ZENLINK_MCP_OPENCLAW_WAKE_MODE=now
  fi
fi

exec node "${MCP}/scripts/register-openclaw.mjs"
EOS
chmod +x "${STAGE}/${TOP}/install-openclaw.sh"

cat > "${STAGE}/${TOP}/upgrade-offline-install.sh" <<'UPGEOF'
#!/usr/bin/env bash
# Upgrade or first-install the offline tarball into a stable path so launchd / docs need not
# change when the version suffix (v0.12.x) changes.
#
# Usage:
#   bash upgrade-offline-install.sh /path/to/zenlink-mcp-offline-vX.tar.gz
#
# Environment:
#   ZENLINK_MCP_OFFLINE_INSTALL_ROOT  default: $HOME/.openclaw/zenlink-mcp
#
set -euo pipefail
NEW_TAR="${1:?usage: $0 path/to/zenlink-mcp-offline-vX.tar.gz}"
ROOT="${ZENLINK_MCP_OFFLINE_INSTALL_ROOT:-${HOME}/.openclaw/zenlink-mcp}"
CUR="${ROOT}/current"

stop_old_daemon() {
  local sup="${CUR}/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs"
  [[ -f "$sup" ]] || return 0
  for envf in "${CUR}/zenlink-deploy.env" "${CUR}/.env"; do
    if [[ -f "$envf" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$envf"
      set +a
      break
    fi
  done
  node "$sup" stop 2>/dev/null || true
}

BK=""
if [[ -d "$CUR" ]]; then
  BK="$(mktemp -d)"
  [[ -f "${CUR}/zenlink-deploy.env" ]] && cp "${CUR}/zenlink-deploy.env" "$BK/"
  [[ -f "${CUR}/.env" ]] && cp "${CUR}/.env" "$BK/"
  stop_old_daemon
  rm -rf "${CUR}.prev"
  mv "$CUR" "${CUR}.prev"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
tar xzf "$NEW_TAR" -C "$TMP"
SRC=""
for d in "$TMP"/zenlink-mcp-offline-v*; do
  if [[ -d "$d" ]]; then
    SRC="$d"
    break
  fi
done
[[ -n "$SRC" ]] || { echo "error: could not find zenlink-mcp-offline-v* top directory in archive" >&2; exit 1; }

mkdir -p "$ROOT"
cp -a "$SRC" "$CUR"
if [[ -n "$BK" ]]; then
  [[ -f "${BK}/zenlink-deploy.env" ]] && cp "${BK}/zenlink-deploy.env" "${CUR}/"
  [[ -f "${BK}/.env" ]] && cp "${BK}/.env" "${CUR}/"
  rm -rf "$BK"
fi

echo "Installed to: $CUR"
echo "Next:"
echo "  cd \"$CUR\" && bash install-openclaw.sh"
echo "  node \"$CUR/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs\" start"
echo "  Restart OpenClaw Gateway if needed so MCP workers reload config."
UPGEOF
chmod +x "${STAGE}/${TOP}/upgrade-offline-install.sh"

mkdir -p "$(dirname "${OUT_FILE}")"
( cd "${STAGE}" && tar czf "${OUT_FILE}" "${TOP}" )
echo "Wrote ${OUT_FILE}"
ls -la "${OUT_FILE}"
