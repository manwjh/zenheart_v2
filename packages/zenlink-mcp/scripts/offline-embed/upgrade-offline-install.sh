#!/usr/bin/env bash
ZENLINK_OFFLINE_BUNDLE_ID="${ZENLINK_OFFLINE_BUNDLE_ID:-}"
ZENLINK_OFFLINE_MCP_VERSION="${ZENLINK_OFFLINE_MCP_VERSION:-}"
# Upgrade or first-install the offline tarball into a stable path so supervisors / docs need not
# change when the version suffix changes.
#
# Usage:
#   bash upgrade-offline-install.sh /path/to/zenlink-mcp-openclaw-macos-vX.tar.gz
#   bash upgrade-offline-install.sh /path/to/zenlink-mcp-openclaw-linux-vX.tar.gz
#
# Environment:
#   ZENLINK_MCP_OFFLINE_INSTALL_ROOT  default: $HOME/.openclaw/zenlink-mcp
#   ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP=1  skip stop/--require-dead before swapping current/ (unsafe)
#   ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE=0  skip install-openclaw.sh after swapping current/
#   ZENLINK_MCP_UPGRADE_REPORT=0      disable ZENLINK_UPGRADE_REPORT_JSON= stderr line
#   ZENLINK_MCP_UPGRADE_PHASE_EVENTS=0 disable ZENLINK_UPGRADE_PHASE_JSON= lines
#
set -euo pipefail
NEW_TAR="${1:?usage: $0 path/to/zenlink-mcp-openclaw-<macos|linux>-vX.tar.gz}"
ROOT="${ZENLINK_MCP_OFFLINE_INSTALL_ROOT:-${HOME}/.openclaw/zenlink-mcp}"
CUR="${ROOT}/current"
UPGRADE_AUTO_ACTIVATED=0
UPGRADE_AUTO_ACTIVATE_SKIPPED=0

SCRIPT_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PE="${SCRIPT_HOME}/pipeline-phase-emit.mjs"

resolve_offline_metadata() {
  if ! command -v node >/dev/null 2>&1; then
    return 0
  fi
  local meta
  meta="$(ZENLINK_OFFLINE_BUNDLE_ID="$ZENLINK_OFFLINE_BUNDLE_ID" \
    ZENLINK_OFFLINE_MCP_VERSION="$ZENLINK_OFFLINE_MCP_VERSION" \
    SCRIPT_HOME="$SCRIPT_HOME" \
    node --input-type=module -e "
      import { readFileSync } from 'node:fs';
      import { join } from 'node:path';

      const scriptHome = process.env.SCRIPT_HOME || '.';
      let bundleId = process.env.ZENLINK_OFFLINE_BUNDLE_ID || '';
      let version = process.env.ZENLINK_OFFLINE_MCP_VERSION || '';

      function readJson(path) {
        try {
          return JSON.parse(readFileSync(path, 'utf8'));
        } catch {
          return null;
        }
      }

      const manifest = readJson(join(scriptHome, 'zenlink-bundle.manifest.json'));
      if (manifest) {
        if (!bundleId && typeof manifest.bundle_id === 'string') bundleId = manifest.bundle_id;
        if (!version && typeof manifest.zenlink_mcp_version === 'string') version = manifest.zenlink_mcp_version;
      }

      const pkg = readJson(join(scriptHome, 'zenlink-mcp', 'package.json'));
      if (!version && pkg && typeof pkg.version === 'string') version = pkg.version;

      console.log(JSON.stringify({ bundleId, version }));
    " 2>/dev/null)" || return 0
  ZENLINK_OFFLINE_BUNDLE_ID="$(node --input-type=module -e "const m = JSON.parse(process.argv[1]); console.log(m.bundleId || '')" "$meta" 2>/dev/null || printf '%s' "$ZENLINK_OFFLINE_BUNDLE_ID")"
  ZENLINK_OFFLINE_MCP_VERSION="$(node --input-type=module -e "const m = JSON.parse(process.argv[1]); console.log(m.version || '')" "$meta" 2>/dev/null || printf '%s' "$ZENLINK_OFFLINE_MCP_VERSION")"
  export ZENLINK_OFFLINE_BUNDLE_ID ZENLINK_OFFLINE_MCP_VERSION
}

resolve_offline_metadata

zenlink_upgrade_phase() {
  local phase="${1:?}"
  shift || true
  local detail=""
  if [[ "$#" -gt 0 ]]; then
    detail="$*"
  fi
  [[ -f "${PE}" ]] || return 0
  command -v node >/dev/null 2>&1 || return 0
  if [[ "${ZENLINK_MCP_UPGRADE_PHASE_EVENTS:-1}" == "0" ]] || [[ "${ZENLINK_MCP_UPGRADE_PHASE_EVENTS:-}" == "false" ]]; then
    return 0
  fi
  if [[ -n "${detail}" ]]; then
    node "${PE}" upgrade "${SCRIPT_HOME}" "${phase}" "${detail}" >&2 || true
  else
    node "${PE}" upgrade "${SCRIPT_HOME}" "${phase}" >&2 || true
  fi
}

zenlink_upgrade_phase script_enter "tar_arg_resolved"

zenlink_upgrade_emit_report() {
  local exit_c="${1:?}" msg="${2:-}" env_flag="${3:-0}"
  if [[ "${ZENLINK_MCP_UPGRADE_REPORT:-1}" == "0" ]] || [[ "${ZENLINK_MCP_UPGRADE_REPORT:-}" == "false" ]]; then
    [[ "$exit_c" -eq 0 ]] || exit "$exit_c"
    return 0
  fi
  if ! command -v node >/dev/null 2>&1; then
    [[ "$exit_c" -eq 0 ]] || exit "$exit_c"
    return 0
  fi
  local ok=0
  [[ "$exit_c" -eq 0 ]] && ok=1
  export ZU_OK="$ok"
  export ZU_EXIT="$exit_c"
  export ZU_MSG="$msg"
  export ZU_INSTALL_ROOT="$ROOT"
  export ZU_CURRENT="$CUR"
  export ZU_TAR="$NEW_TAR"
  export ZU_ENV_RESTORED="$env_flag"
  export ZU_PREV="${CUR}.prev"
  export ZU_VERSION="${ZENLINK_OFFLINE_MCP_VERSION:-}"
  export ZU_BUNDLE="${ZENLINK_OFFLINE_BUNDLE_ID:-}"
  export ZU_AUTO_ACTIVATED="$UPGRADE_AUTO_ACTIVATED"
  export ZU_AUTO_ACTIVATE_SKIPPED="$UPGRADE_AUTO_ACTIVATE_SKIPPED"
  node --input-type=module -e "
  const cur = process.env.ZU_CURRENT || '';
  const autoActivated = process.env.ZU_AUTO_ACTIVATED === '1';
  const autoActivateSkipped = process.env.ZU_AUTO_ACTIVATE_SKIPPED === '1';
  const p = {
    schema: 'zenlink_upgrade_report/v1',
    ok: process.env.ZU_OK === '1',
    exit_code: Number(process.env.ZU_EXIT || 0),
    message: process.env.ZU_MSG || '',
    install_root: process.env.ZU_INSTALL_ROOT || '',
    current_path: process.env.ZU_CURRENT || '',
    tarball_path: process.env.ZU_TAR || '',
    zenlink_deploy_env_restored: process.env.ZU_ENV_RESTORED === '1',
    previous_current_path: process.env.ZU_PREV || undefined,
    zenlink_mcp_version: process.env.ZU_VERSION || undefined,
    bundle_id: process.env.ZU_BUNDLE || undefined,
    post_upgrade_activation: autoActivated ? 'completed' : (autoActivateSkipped ? 'skipped' : 'not_completed'),
    recommended_next_commands:
      process.env.ZU_OK === '1'
        ? (autoActivated
            ? [
                'node ' + JSON.stringify(cur + '/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs') + ' status',
                'Verify zenlink_status inside OpenClaw.',
              ]
            : [
                'cd ' + JSON.stringify(cur) + ' && bash install-openclaw.sh',
                'node ' + JSON.stringify(cur + '/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs') + ' start',
                'openclaw gateway restart',
              ])
        : [
            'Fix the error above; if current/ is missing, inspect current.prev for rollback.',
          ],
  };
  console.error('ZENLINK_UPGRADE_REPORT_JSON=' + JSON.stringify(p));
  " >&2 || true
  [[ "$exit_c" -eq 0 ]] || exit "$exit_c"
}

[[ -f "$NEW_TAR" ]] || {
  echo "error: tarball not found: $NEW_TAR" >&2
  zenlink_upgrade_phase tarball_not_found
  zenlink_upgrade_emit_report 1 "tarball not found" 0
}
zenlink_upgrade_phase tarball_open_ok

stop_old_daemon() {
  local sup="${CUR}/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs"
  [[ -f "$sup" ]] || return 0
  if [[ "${ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP:-}" == "1" ]]; then
    echo "warning: ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP=1 — not stopping daemon before upgrade (risk stale listener)" >&2
    zenlink_upgrade_phase daemon_stop_skipped "ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP=1"
    return 0
  fi
  for envf in "${CUR}/zenlink-deploy.env" "${CUR}/.env"; do
    if [[ -f "$envf" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "$envf"
      set +a
      break
    fi
  done
  local daemon_addr_file="${ZENLINK_MCP_DAEMON_ADDR_FILE:-}"
  if [[ -z "${daemon_addr_file// }" ]]; then
    export ZENLINK_MCP_DAEMON_ADDR_FILE="${HOME}/.openclaw/tmp/zenlink-mcp-daemon.addr"
  fi
  echo "stopping prior zenlink daemon via addr file: ${ZENLINK_MCP_DAEMON_ADDR_FILE}" >&2
  echo "daemon diagnostics: addr=${ZENLINK_MCP_DAEMON_ADDR_FILE} token=${ZENLINK_MCP_DAEMON_ADDR_FILE}.token status=${ZENLINK_MCP_DAEMON_ADDR_FILE}.status.json log=${ZENLINK_MCP_DAEMON_ADDR_FILE}.log" >&2
  node "$sup" stop --require-dead
}

BK=""
if [[ -d "$CUR" ]]; then
  zenlink_upgrade_phase replacing_prior_current
  BK="$(mktemp -d)"
  [[ -f "${CUR}/zenlink-deploy.env" ]] && cp "${CUR}/zenlink-deploy.env" "$BK/"
  [[ -f "${CUR}/.env" ]] && cp "${CUR}/.env" "$BK/"
  stop_old_daemon || {
    zenlink_upgrade_phase daemon_stop_failed
    zenlink_upgrade_emit_report 1 "daemon stop --require-dead failed for addr_file=${ZENLINK_MCP_DAEMON_ADDR_FILE:-${HOME}/.openclaw/tmp/zenlink-mcp-daemon.addr}; inspect addr/token/status/log siblings; fix listener or set ZENLINK_MCP_UPGRADE_SKIP_DAEMON_STOP=1" 0
  }
  rm -rf "${CUR}.prev"
  mv "$CUR" "${CUR}.prev"
fi

TMP="$(mktemp -d)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT
if ! tar xzf "$NEW_TAR" -C "$TMP"; then
  zenlink_upgrade_phase tar_extract_failed
  zenlink_upgrade_emit_report 1 "tar extract failed" 0
fi
zenlink_upgrade_phase tar_extract_ok
SRC=""
for d in \
  "$TMP"/zenlink-mcp-openclaw-macos-v* \
  "$TMP"/zenlink-mcp-openclaw-linux-v* \
  "$TMP"/zenlink-mcp-openclaw_macos-v* \
  "$TMP"/zenlink-mcp-offline-v*; do
  if [[ -d "$d" ]]; then
    SRC="$d"
    break
  fi
done
[[ -n "$SRC" ]] || {
  echo "error: could not find zenlink-mcp-openclaw-*-v* or legacy zenlink-mcp-offline-v* top directory in archive" >&2
  zenlink_upgrade_phase bundle_inner_root_resolve_failed
  zenlink_upgrade_emit_report 1 "could not find extracted bundle top directory in tarball" 0
}
zenlink_upgrade_phase bundle_inner_root_resolved

mkdir -p "$ROOT"
cp -a "$SRC" "$CUR"
zenlink_upgrade_phase copied_to_current
ENV_FLAG=0
if [[ -n "$BK" ]]; then
  [[ -f "${BK}/zenlink-deploy.env" ]] && cp "${BK}/zenlink-deploy.env" "${CUR}/"
  [[ -f "${BK}/.env" ]] && cp "${BK}/.env" "${CUR}/"
  rm -rf "$BK"
  [[ -f "${CUR}/zenlink-deploy.env" ]] && ENV_FLAG=1
fi

auto_activate_after_upgrade() {
  if [[ "${ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE:-1}" == "0" ]] || [[ "${ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE:-}" == "false" ]]; then
    echo "note: skipped post-upgrade activation because ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE=0"
    zenlink_upgrade_phase auto_activate_skipped "ZENLINK_MCP_UPGRADE_AUTO_ACTIVATE=0"
    UPGRADE_AUTO_ACTIVATE_SKIPPED=1
    return 0
  fi
  zenlink_upgrade_phase auto_activate_enter
  (
    cd "$CUR"
    bash install-openclaw.sh
  ) || {
    zenlink_upgrade_phase auto_activate_failed
    zenlink_upgrade_emit_report 1 "post-upgrade install-openclaw.sh activation failed" "$ENV_FLAG"
  }
  UPGRADE_AUTO_ACTIVATED=1
  zenlink_upgrade_phase auto_activate_ok
}

auto_activate_after_upgrade

echo "Installed to: $CUR"
if [[ "$UPGRADE_AUTO_ACTIVATED" -eq 1 ]]; then
  echo "Activated: install-openclaw.sh completed post-upgrade activation."
else
  echo "Next:"
  echo "  cd \"$CUR\" && bash install-openclaw.sh"
  echo "  node \"$CUR/zenlink-mcp/scripts/openclaw-zenlink-daemon.mjs\" start"
  echo "  openclaw gateway restart"
fi

zenlink_upgrade_phase emitting_final_upgrade_report_slice
zenlink_upgrade_emit_report 0 "Extracted bundle to current." "$ENV_FLAG"
