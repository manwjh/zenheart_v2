#!/usr/bin/env bash
# cursor_agent/start.sh — ZenLink Cursor 测试 daemon
#
# 环境变量简要：
#   CURSOR_AGENT_PROVIDER=rules — 不测 Cursor SDK
#   CURSOR_AGENT_SKIP_SDK_PROBE=1 — 跳过联网密钥探测（离线/代理异常时用）
#   CURSOR_AGENT_QUIET_HINT=1 — 不打印说明横幅
#   CURSOR_AGENT_NONINTERACTIVE=1 — 禁止交互粘贴
#   CURSOR_AGENT_ENV_FILE — 默认: <repo>/backend/.env.zenlink-readiness
#   CURSOR_AGENT_DEBUG_HOST — 传给 daemon 的 debug 绑定地址（默认 127.0.0.1；勿用 localhost 打不开时可试）
#   CURSOR_AGENT_ROOM_ID — own / 或其它 room UUID
#
# 一次性 REST（不启 daemon；需 ZENLINK_AGENT_ID + ZENLINK_TOKEN，可用 --env-file 加载）：
#   python3 cursor_agent/cursor_agent.py msgbox-ack --env-file backend/.env.zenlink-readiness --message-id <id> [--ids a,b]
#   python3 cursor_agent/cursor_agent.py send-dm --env-file backend/.env.zenlink-readiness --to-agent-id <id> --body "..."
# （在仓库根目录执行；也可用完整路径指向本仓库的 cursor_agent.py。）
#
# ⚠️ 交互粘贴密钥后，只要把「密钥」粘进脚本提示里；别把整页终端日志再粘贴到 zsh，否则会出现
#    command not found / parse error。
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$ROOT/cursor_agent"
PY="$AGENT_DIR/.venv/bin/python"

ENV_FILE="${CURSOR_AGENT_ENV_FILE:-$ROOT/backend/.env.zenlink-readiness}"
ROOM_ID="${CURSOR_AGENT_ROOM_ID:-own}"
PROVIDER="${CURSOR_AGENT_PROVIDER:-auto}"
BASE_URL="${ZENLINK_BASE_URL:-https://zenheart.net}"
START_TIMEOUT="${CURSOR_AGENT_START_TIMEOUT:-20}"
DEBUG_PORT="${CURSOR_AGENT_DEBUG_PORT:-8765}"
DEBUG_HOST="${CURSOR_AGENT_DEBUG_HOST:-127.0.0.1}"

if [[ ! -x "${PY}" ]]; then
  echo "missing venv python: ${PY}" >&2
  exit 1
fi

_trim_space_var() {
  local _name="$1"
  local _v="${!_name:-}"
  _v="${_v#"${_v%%[![:space:]]*}"}"
  _v="${_v%"${_v##*[![:space:]]}"}"
  printf -v "${_name}" '%s' "${_v}"
}

dotenv_value() {
  local _file="$1" _want="$2" _line _k _v
  [[ -f "${_file}" ]] || return 1
  while IFS= read -r _line || [[ -n ${_line:+x} ]]; do
    _line="${_line#"${_line%%[![:space:]]*}"}"
    _line="${_line%"${_line##*[![:space:]]}"}"
    [[ -z "${_line}" || "${_line}" == \#* ]] && continue
    [[ "${_line}" == *=* ]] || continue
    _k="${_line%%=*}"
    _v="${_line#*=}"
    _k="${_k#"${_k%%[![:space:]]*}"}"
    _k="${_k%"${_k##*[![:space:]]}"}"
    _v="${_v#"${_v%%[![:space:]]*}"}"
    _v="${_v%"${_v##*[![:space:]]}"}"
    [[ "${_k}" == "${_want}" ]] || continue
    if [[ "${_v}" == \"*\" ]]; then _v="${_v#\"}"; _v="${_v%\"}"; fi
    if [[ "${_v}" == \'*\' ]]; then _v="${_v#\'}"; _v="${_v%\'}"; fi
    printf '%s' "${_v}"
    return 0
  done <"${_file}"
  return 1
}

layers_fill_cursor_key() {
  _trim_space_var CURSOR_API_KEY
  [[ -n "${CURSOR_API_KEY:+x}" ]] && export CURSOR_API_KEY && return 0
  local _f _v
  for _f in "${ENV_FILE}" "${AGENT_DIR}/.cursor-agent.env" "${ROOT}/backend/.cursor-agent.env"; do
    _v="$(dotenv_value "${_f}" CURSOR_API_KEY)" || continue
    local _junk="${_v}"
    _junk="${_junk#"${_junk%%[![:space:]]*}"}"
    _junk="${_junk%"${_junk##*[![:space:]]}"}"
    [[ -z "${_junk}" ]] && continue
    export CURSOR_API_KEY="${_junk}"
    return 0
  done
  export CURSOR_API_KEY=""
}

needs_sdk() {
  [[ "${PROVIDER}" == "auto" || "${PROVIDER}" == "cursor-sdk" ]]
}

dashboard_open_url() {
  local _h="$1" _p="$2"
  if [[ -z "${_h}" || "${_h}" == "0.0.0.0" || "${_h}" == "::" ]]; then
    printf '%s' "http://127.0.0.1:${_p}/"
    return 0
  fi
  if [[ "${_h}" == "::1" ]]; then
    printf '%s' "http://[::1]:${_p}/"
    return 0
  fi
  printf '%s' "http://${_h}:${_p}/"
}

# 轮询 HTTP；优先 127.0.0.1（避免浏览器用 localhost→::1 而进程只监听 IPv4）
wait_dashboard_http() {
  local _p="$1" _try _urls _u
  _urls=(
    "http://127.0.0.1:${_p}/"
    "http://[::1]:${_p}/"
  )
  for ((_try = 1; _try <= 24; _try++)); do
    for _u in "${_urls[@]}"; do
      if command -v curl >/dev/null 2>&1; then
        curl -sf -m 1 -o /dev/null "${_u}" || continue
      else
        "${PY}" -c "import urllib.request; urllib.request.urlopen('${_u}', timeout=1)" >/dev/null 2>&1 || continue
      fi
      printf '%s' "${_u}"
      return 0
    done
    sleep 0.25
  done
  return 1
}

summarize_start_json() {
  local _jf="$1"
  "${PY}" "$AGENT_DIR/summarize_start_stdout.py" "${_jf}" || sed -n '1p' "${_jf}"
}

pretty_print_failure_json() {
  local _jf="$1"
  if "${PY}" -m json.tool <"${_jf}" >/dev/null 2>&1; then
    printf '%s\n' "--- cursor_agent.py start stderr (formatted) ---" >&2
    "${PY}" -m json.tool <"${_jf}" >&2 || true
  else
    cat "${_jf}" >&2 || true
  fi
}

hint_banner() {
  [[ "${CURSOR_AGENT_QUIET_HINT:-}" == "1" ]] && return 0
  needs_sdk || return 0
  cat >&2 <<'TXT'
------------------------------------------------------------
CURSOR_API_KEY · provider=auto|cursor-sdk

  Env file order: CURSOR_AGENT_ENV_FILE (default backend/.env.zenlink-readiness)
                  -> cursor_agent/.cursor-agent.env -> backend/.cursor-agent.env

  Skip Cursor API : CURSOR_AGENT_PROVIDER=rules
  Skip sdk-probe : CURSOR_AGENT_SKIP_SDK_PROBE=1
  Quiet banner   : CURSOR_AGENT_QUIET_HINT=1
  Integrations    : https://cursor.com/dashboard/integrations

------------------------------------------------------------
TXT
}

key_paste_feedback() {
  local _n="${#CURSOR_API_KEY}"
  local _fp=""
  if command -v shasum >/dev/null 2>&1; then
    _fp="$(LC_ALL=C printf '%s' "${CURSOR_API_KEY}" | shasum -a 256 2>/dev/null | cut -c1-8 || true)"
  fi
  if [[ -n "${_fp}" ]]; then
    printf '%s\n' "[cursor_agent] key length=${_n}; sha256 prefix=${_fp}" >&2
  else
    printf '%s\n' "[cursor_agent] key length=${_n}; (no shasum, skip fingerprint)" >&2
  fi
}

prompt_key_hidden() {
  local _banner="$1"
  local _reply
  if [[ "${CURSOR_AGENT_NONINTERACTIVE:-}" == "1" ]]; then
    echo "CURSOR_AGENT_NONINTERACTIVE=1 — set CURSOR_API_KEY or use CURSOR_AGENT_SKIP_SDK_PROBE." >&2
    return 2
  fi
  if [[ ! -t 0 || ! -t 1 ]]; then
    echo "Not a tty — export CURSOR_API_KEY or CURSOR_AGENT_SKIP_SDK_PROBE=1 ./start.sh" >&2
    return 2
  fi

  printf '%s\n' "${_banner}" >&2
  echo "Paste ONLY the api key itself (avoid pasting logs into zsh)." >&2
  if [[ "${CURSOR_AGENT_API_KEY_VISIBLE:-}" == "1" ]]; then
    IFS= read -r -p $'VISIBLE key paste, Enter:\n> ' _reply || true
  else
    IFS= read -r -s -p $'Hidden paste, Enter:\n> ' _reply || true
    printf '\n' >&2
  fi

  export CURSOR_API_KEY="${_reply}"
  _trim_space_var CURSOR_API_KEY
  if [[ -z "${CURSOR_API_KEY:+x}" ]]; then
    echo "empty key." >&2
    return 1
  fi
  key_paste_feedback
  return 0
}

pretty_probe_first_line() {
  local _f="$1"
  local _pretty
  if [[ ! -s "${_f}" ]]; then
    printf '%s\n' "(sdk-probe: empty stdout)" >&2
    return 0
  fi
  printf '%s\n' "--- sdk-probe stdout (JSON) ---" >&2
  _pretty="$(mktemp)"
  if "${PY}" -m json.tool <"${_f}" >"${_pretty}" 2>/dev/null; then
    head -n 40 "${_pretty}" >&2 || true
  else
    sed -n '1p' "${_f}" >&2 || true
  fi
  rm -f "${_pretty}"
}

ensure_sdk_key_probe() {
  needs_sdk || return 0

  local _max="${CURSOR_AGENT_API_KEY_RETRIES:-5}"
  local _probe_out _probe_rc=-1 _try

  layers_fill_cursor_key

  _try=0
  while ((_try < _max)); do
    ((_try++)) || true

    layers_fill_cursor_key
    _trim_space_var CURSOR_API_KEY

    if [[ -z "${CURSOR_API_KEY:+x}" ]]; then
      if ((_try == 1)); then
        prompt_key_hidden "No CURSOR_API_KEY in shell + env chain." || return 1
      else
        prompt_key_hidden "Paste a new CURSOR_API_KEY." || return 1
      fi
      _trim_space_var CURSOR_API_KEY
      [[ -n "${CURSOR_API_KEY:+x}" ]] || return 1
    fi

    if [[ "${CURSOR_AGENT_SKIP_SDK_PROBE:-}" == "1" ]]; then
      return 0
    fi

    _probe_out="$(mktemp)"

    "${PY}" "${AGENT_DIR}/cursor_agent.py" sdk-probe \
      --env-file "${ENV_FILE}" \
      --provider "${PROVIDER}" \
      >"${_probe_out}"

    _probe_rc=$?

    if [[ "${_probe_rc}" -eq 0 ]]; then
      rm -f "${_probe_out}"
      return 0
    fi

    echo "--- sdk-probe failed (exit ${_probe_rc}) ---" >&2
    pretty_probe_first_line "${_probe_out}"
    rm -f "${_probe_out}"

    if [[ "${_probe_rc}" -eq 2 ]]; then
      echo "--- unauthenticated (${_try} of ${_max}) — paste a new key ---" >&2
      prompt_key_hidden "" || return 1
      continue
    fi

    if [[ "${_probe_rc}" -eq 5 ]]; then
      prompt_key_hidden "Still missing CURSOR_API_KEY for probe." || return 1
      continue
    fi

    printf '%s\n' \
      "--- sdk-probe network/runtime error (${_probe_rc}). Offline? Try CURSOR_AGENT_SKIP_SDK_PROBE=1 ./start.sh --- " \
      >&2
    return 1
  done

  echo "--- max retries (${_max}) ---" >&2
  return 1
}

hint_banner

ensure_sdk_key_probe || exit 1

_start_out="$(mktemp)"
trap 'rm -f "${_start_out}"' EXIT
start_rc=-1

set +e
"${PY}" "${AGENT_DIR}/cursor_agent.py" start \
  --room-id "${ROOM_ID}" \
  --provider "${PROVIDER}" \
  --base-url "${BASE_URL}" \
  --env-file "${ENV_FILE}" \
  --debug-host "${DEBUG_HOST}" \
  --debug-port "${DEBUG_PORT}" \
  --start-timeout "${START_TIMEOUT}" \
  "$@" >"${_start_out}"
start_rc=$?
set -e

if [[ "${start_rc}" -eq 0 ]]; then
  summarize_start_json "${_start_out}"
  echo ""
  rm -f "${_start_out}"
  trap - EXIT

  _open="$(dashboard_open_url "${DEBUG_HOST}" "${DEBUG_PORT}")"
  printf '%s\n' "--- open in browser (${_open}) — using 127.0.0.1 avoids some localhost IPv6 issues ---"

  _verified="$(wait_dashboard_http "${DEBUG_PORT}" || true)"
  if [[ -n "${_verified}" ]]; then
    printf '%s\n' "  dashboard: ${_verified} (HTTP OK)"
  else
    _open="$(dashboard_open_url "${DEBUG_HOST}" "${DEBUG_PORT}")"
    printf '%s\n' "  dashboard: ${_open}" \
      "  (HTTP probe timed out — macOS Safari/Chrome sometimes needs 127.0.0.1 not «localhost». Try pasting ${_open})" >&2
  fi
  printf '%s\n' \
    "  status: ${AGENT_DIR}/status.sh" \
    "  logs:   ${AGENT_DIR}/logs.sh" \
    "  stop:   ${AGENT_DIR}/stop.sh"
else
  echo "--- start failed exit=${start_rc} ---" >&2
  pretty_print_failure_json "${_start_out}"
  echo "hint: bootstrap log at ${AGENT_DIR}/.tmp/bootstrap.log" >&2
  exit "${start_rc}"
fi

if needs_sdk && [[ -z "${CURSOR_API_KEY:+x}" ]]; then
  echo "(note: child loads dotenv CURSOR_* / ZENLINK_* from files)" >&2
fi

echo
