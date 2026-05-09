#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP="${ROOT}/zenlink-mcp"
PE="${ROOT}/pipeline-phase-emit.mjs"

zenlink_install_phase() {
  local component="${1:?}" phase="${2:?}"
  shift 2 || true
  local detail=""
  if [[ "$#" -gt 0 ]]; then
    detail="$*"
  fi
  [[ -f "$PE" ]] || return 0
  command -v node >/dev/null 2>&1 || return 0
  if [[ "${ZENLINK_MCP_INSTALL_PHASE_EVENTS:-1}" == "0" ]] || [[ "${ZENLINK_MCP_INSTALL_PHASE_EVENTS:-}" == "false" ]]; then
    return 0
  fi
  if [[ -n "${detail}" ]]; then
    node "${PE}" install "${MCP}" "${component}" "${phase}" "${detail}" >&2 || true
  else
    node "${PE}" install "${MCP}" "${component}" "${phase}" >&2 || true
  fi
}

zenlink_install_phase shell script_enter

emit_install_fail() {
  local code="${1:?}" reason="${2:?}" detail="${3:-}"
  if command -v node >/dev/null 2>&1; then
    ZENLINK_MCP_INSTALL_REPORT="${ZENLINK_MCP_INSTALL_REPORT:-1}" \
      node "${MCP}/scripts/emit-install-report-bash-fail.mjs" "$MCP" "$reason" "$detail" "$code" >&2 || true
  elif [[ "${ZENLINK_MCP_INSTALL_REPORT:-1}" != "0" && "${ZENLINK_MCP_INSTALL_REPORT:-}" != "false" ]]; then
    # Minimal JSON fallback for the only preflight case where the normal reporter cannot run.
    local escaped_reason escaped_detail
    escaped_reason="${reason//\\/\\\\}"
    escaped_reason="${escaped_reason//\"/\\\"}"
    escaped_detail="${detail//\\/\\\\}"
    escaped_detail="${escaped_detail//\"/\\\"}"
    printf 'ZENLINK_INSTALL_REPORT_JSON={"schema":"zenlink_install_report/v1","ok":false,"exit_code":%s,"zenlink_mcp_version":"unknown","mcp_server_name":"%s","openclaw_config_path":"%s/.openclaw/openclaw.json","checks":[{"id":"node_on_path","ok":false,"detail":"node_missing"},{"id":"bash_preflight","ok":false,"detail":"%s: %s"}],"message":"install-openclaw.sh (bash): node_missing"}\n' \
      "$code" "${OPENCLAW_MCP_NAME:-zenheart}" "$HOME" "$escaped_reason" "$escaped_detail" >&2
  fi
  exit "${code}"
}

if ! command -v node >/dev/null 2>&1; then
  echo "error: node is required but was not found on PATH" >&2
  emit_install_fail 1 node_missing "install-openclaw.sh requires Node.js 18+"
fi

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

if load_env_files; then
  zenlink_install_phase shell env_load "sourced_zenlink-deploy_or_dotenv"
else
  echo "note: no zenlink-deploy.env or .env next to install-openclaw.sh — using current shell exports only."
  echo "hint: cp zenlink-deploy.env.example zenlink-deploy.env && edit, then re-run."
  zenlink_install_phase shell env_load "no_local_env_file_shell_exports_only"
fi

apply_default_daemon_forwarding() {
  if [[ "${ZENLINK_MCP_NO_DEFAULT_DAEMON:-}" == "1" ]]; then
    return 0
  fi
  local did=0
  local use_daemon="${ZENLINK_MCP_USE_DAEMON:-}"
  local addr_file="${ZENLINK_MCP_DAEMON_ADDR_FILE:-}"
  if [[ -z "${use_daemon// }" ]]; then
    export ZENLINK_MCP_USE_DAEMON=1
    did=1
  fi
  if [[ -z "${addr_file// }" ]]; then
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
zenlink_install_phase shell daemon_defaults_applied

zenlink_install_phase shell validating_bundle_layout

if [[ ! -f "${MCP}/dist/cli.js" ]]; then
  echo "error: missing ${MCP}/dist/cli.js" >&2
  emit_install_fail 1 missing_cli_js "${MCP}/dist/cli.js"
fi
if [[ ! -d "${MCP}/node_modules" ]]; then
  echo "error: missing ${MCP}/node_modules (invalid offline bundle)" >&2
  emit_install_fail 1 missing_node_modules "${MCP}/node_modules"
fi

HB="${ZENLINK_MCP_OPENCLAW_HOOK_BASE:-}"
HT="${ZENLINK_MCP_OPENCLAW_HOOK_TOKEN:-}"
if [[ -z "${HB// }" || -z "${HT// }" ]]; then
  echo "warning: OpenClaw push disabled until both ZENLINK_MCP_OPENCLAW_HOOK_BASE and ZENLINK_MCP_OPENCLAW_HOOK_TOKEN are set."
  echo "        Fix: add them to zenlink-deploy.env or export before this script; re-run this script after editing."
  echo "        (external supervisors — launchd, systemd, etc. — do not source zenlink-deploy.env unless you wire it)"
  zenlink_install_phase shell openclaw_hook_push incomplete_env
else
  if [[ -z "${ZENLINK_MCP_OPENCLAW_WAKE_MODE+x}" ]]; then
    export ZENLINK_MCP_OPENCLAW_WAKE_MODE=now
  fi
  if [[ -z "${ZENLINK_MCP_OPENCLAW_SESSION_KEY+x}" ]]; then
    export ZENLINK_MCP_OPENCLAW_SESSION_KEY=hook:zenheart-main
  fi
  zenlink_install_phase shell openclaw_hook_push ready
fi

zenlink_install_phase shell spawning_register_js

exec node "${MCP}/scripts/register-openclaw.mjs"
