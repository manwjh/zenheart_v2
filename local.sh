#!/usr/bin/env bash
# ZenHeart v2 — 唯一本地入口：Postgres(Docker) + venv + .env + Uvicorn + Vite
#
#   ./local.sh                全流程（含 pip），前台 Vite；退出 Vite 会停掉本会话起的后端
#   ./local.sh --quick        跳过 pip/升级依赖；仍起 Docker、自检、双进程（无 venv 时会自动补装）
#   ./local.sh --bootstrap-only   只做环境（库+配置），不启 Uvicorn/Vite
#   ./local.sh --verify-only      只检查 .env / 配置 / 5433 / 可选 :8090
#   ./local.sh --backend-only     只前台跑 Uvicorn（调试用）
#   ./local.sh --frontend-only    只前台跑 Vite（需后端已在跑）
#
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"
FRONT_PORT="${FRONT_PORT:-5173}"
QUICK=0
MODE=run

usage() {
  cat <<'EOF'
ZenHeart v2 — 唯一本地入口

  ./local.sh                  全流程；退出 Vite 会停掉本会话起的后端
  ./local.sh --quick          跳过 pip（已有 venv 时）；仍起 Docker + 双进程
  ./local.sh --bootstrap-only  只准备 Docker / venv / .env
  ./local.sh --verify-only    只检查 .env、配置、5433、可选 :8090
  ./local.sh --backend-only   只跑 Uvicorn（前台）
  ./local.sh --frontend-only  只跑 Vite（前台）
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --quick) QUICK=1; shift ;;
    --bootstrap-only) MODE=bootstrap; shift ;;
    --verify-only) MODE=verify; shift ;;
    --backend-only) MODE=backend; shift ;;
    --frontend-only) MODE=frontend; shift ;;
    -h | --help) usage; exit 0 ;;
    *)
      echo "Unknown option: $1 (try --help)" >&2
      exit 1
      ;;
  esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# If a dev server is already listening, stop it so this script can bind again.
stop_listener_on_port() {
  local port="$1"
  local label="${2:-$port}"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pids
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Stopping existing listener on ${label} (TCP ${port})…"
  echo "$pids" | xargs kill 2>/dev/null || true
  sleep 1
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
  fi
}

resolve_py311() {
  PY311=""
  if command -v python3.11 >/dev/null 2>&1; then
    PY311="$(command -v python3.11)"
  elif [[ -x "/opt/homebrew/bin/python3.11" ]]; then
    PY311="/opt/homebrew/bin/python3.11"
  fi
  if [[ -z "$PY311" ]]; then
    echo "python3.11 not found. Install Python 3.11+." >&2
    exit 1
  fi
}

python_run() {
  if [[ -x "$BACKEND/.venv_py311/bin/python" ]]; then
    echo "$BACKEND/.venv_py311/bin/python"
  elif command -v python3.11 >/dev/null 2>&1; then
    command -v python3.11
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    echo "No Python 3 interpreter found." >&2
    return 1
  fi
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Docker CLI not found. Install Docker Desktop." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "Docker daemon not running. Start Docker Desktop, then:" >&2
    echo "  cd $ROOT && ./local.sh" >&2
    exit 1
  fi
}

docker_up_pg() {
  echo "Starting PostgreSQL (docker compose)…"
  docker compose -f "$BACKEND/docker-compose.yml" up -d
}

wait_postgres() {
  echo "Waiting for PostgreSQL on 127.0.0.1:5433…"
  local ready=0
  local _
  for _ in $(seq 1 45); do
    if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 5433 2>/dev/null; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" != "1" ]]; then
    echo "Port 5433 did not open. Check: docker compose -f $BACKEND/docker-compose.yml logs" >&2
    exit 1
  fi
}

venv_and_pip() {
  resolve_py311
  if [[ ! -d "$BACKEND/.venv_py311" ]]; then
    echo "Creating .venv_py311 …"
    "$PY311" -m venv "$BACKEND/.venv_py311"
    QUICK=0
  fi
  if [[ "$QUICK" == 1 ]]; then
    return 0
  fi
  # shellcheck disable=SC1091
  source "$BACKEND/.venv_py311/bin/activate"
  pip install -q --upgrade pip
  pip install -q -r "$BACKEND/requirements.txt"
}

ensure_env_file() {
  if [[ -f "$BACKEND/.env" ]]; then
    return 0
  fi
  echo "No backend/.env — creating from .env.example (local news/media paths)…"
  cp "$BACKEND/.env.example" "$BACKEND/.env"
  resolve_py311
  ROOT="$ROOT" "$PY311" <<'PY'
import os
from pathlib import Path

root = Path(os.environ["ROOT"]).resolve() / "backend"
p = root / ".env"
text = p.read_text(encoding="utf-8")
out: list[str] = []
for line in text.splitlines(keepends=True):
    if line.startswith("NEWS_MARKDOWN_ROOT="):
        out.append(f"NEWS_MARKDOWN_ROOT={root / 'local-data' / 'news'}\n")
    elif line.startswith("MEDIA_ROOT="):
        out.append(f"MEDIA_ROOT={root / 'local-data' / 'media'}\n")
    else:
        out.append(line)
p.write_text("".join(out), encoding="utf-8")
PY
  echo "Edit ADMIN_API_KEY in $BACKEND/.env before any real deploy."
  echo ""
}

mkdir_data() {
  mkdir -p "$BACKEND/local-data/news" "$BACKEND/local-data/media/images"
}

export_local_overrides() {
  export NEWS_MARKDOWN_ROOT="${NEWS_MARKDOWN_ROOT:-$BACKEND/local-data/news}"
  export MEDIA_ROOT="${MEDIA_ROOT:-$BACKEND/local-data/media}"
}

verify_core() {
  cd "$BACKEND"
  if [[ ! -f .env ]]; then
    echo -e "${RED}FAIL${NC} Missing $BACKEND/.env — run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    return 1
  fi
  echo -e "${GREEN}OK${NC} .env present"
  local pb
  pb="$(python_run)" || true
  if [[ -z "${pb:-}" ]] || [[ ! -x "$pb" ]]; then
    echo -e "${RED}FAIL${NC} No Python / venv — run full ./local.sh once." >&2
    return 1
  fi
  export_local_overrides
  if ! "$pb" -c "from app.config import load_settings; load_settings()" 2>/tmp/zenheart_local_settings.err; then
    echo -e "${RED}FAIL${NC} Settings did not load:" >&2
    cat /tmp/zenheart_local_settings.err >&2 || true
    return 1
  fi
  echo -e "${GREEN}OK${NC} Settings (pydantic)"
  if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 5433 2>/dev/null; then
    echo -e "${GREEN}OK${NC} PostgreSQL on 127.0.0.1:5433"
  else
    echo -e "${RED}FAIL${NC} Nothing on 127.0.0.1:5433 — start DB with ./local.sh --bootstrap-only" >&2
    return 1
  fi
  return 0
}

verify_with_optional_backend() {
  local fail=0 backend_ok=0
  verify_core || fail=1
  if [[ "$fail" != 0 ]]; then
    echo -e "${RED}Fix errors above, then: cd $ROOT && ./local.sh --verify-only${NC}" >&2
    exit 1
  fi
  cd "$BACKEND"
  if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
    local body
    if body=$(curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/health" 2>/dev/null); then
      echo -e "${GREEN}OK${NC} Backend :${PORT}/health → $body"
      backend_ok=1
    else
      echo -e "${YELLOW}WARN${NC} Port ${PORT} open but /health not JSON" >&2
      fail=1
    fi
  else
    echo -e "${YELLOW}WARN${NC} Backend not on :${PORT} — expected until ./local.sh or ./local.sh --backend-only"
  fi
  echo ""
  if [[ "$fail" != 0 ]]; then
    exit 1
  fi
  if [[ "$backend_ok" == 1 ]]; then
    echo -e "${GREEN}All checks passed (including backend).${NC}"
  else
    echo -e "${GREEN}Core checks passed (DB + settings).${NC}"
  fi
}

preflight_backend() {
  cd "$BACKEND"
  local pb
  pb="$(python_run)" || true
  if [[ -z "${pb:-}" ]]; then
    echo "No Python interpreter. Run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    exit 1
  fi
  if [[ ! -f "$BACKEND/.env" ]]; then
    echo "Missing $BACKEND/.env — run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    exit 1
  fi
  mkdir_data
  export_local_overrides
  echo "Preflight (load settings)…"
  if ! "$pb" -c "from app.config import load_settings; load_settings()" 2>/tmp/zenheart_local_preflight.err; then
    cat /tmp/zenheart_local_preflight.err >&2
    echo "Fix .env (see .env.example) or run: cd $ROOT && ./local.sh --verify-only" >&2
    exit 1
  fi
}

run_backend_fg() {
  stop_listener_on_port "$PORT" "backend"
  preflight_backend
  local pb
  pb="$(python_run)"
  echo "Uvicorn http://127.0.0.1:${PORT} — docs http://127.0.0.1:${PORT}/docs — WS debug http://127.0.0.1:${PORT}/v2/admin/debug/ws"
  exec "$pb" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
}

run_frontend_fg() {
  stop_listener_on_port "$FRONT_PORT" "frontend"
  cd "$FRONTEND"
  if [[ ! -d node_modules ]]; then
    npm install
  fi
  npm run dev
}

print_urls() {
  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  本地地址"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  PostgreSQL     127.0.0.1:5433"
  echo "  后端           http://127.0.0.1:${PORT}/   (PORT=… 可覆盖)"
  echo "  前端           http://127.0.0.1:${FRONT_PORT}/"
  echo "  WS 调试        http://127.0.0.1:${PORT}/v2/admin/debug/ws"
  echo "                 http://127.0.0.1:${FRONT_PORT}/v2/admin/debug/ws  (经 Vite 代理)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo ""
}

run_full() {
  stop_listener_on_port "$PORT" "backend"
  stop_listener_on_port "$FRONT_PORT" "frontend"
  require_docker
  docker_up_pg
  wait_postgres
  venv_and_pip
  mkdir_data
  ensure_env_file
  cd "$ROOT"
  verify_core || exit 1
  print_urls

  echo "Starting backend in background (http://127.0.0.1:${PORT})…"
  (
    cd "$BACKEND"
    export_local_overrides
    exec "$(python_run)" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
  ) &
  local BPID=$!

  cleanup() {
    if kill -0 "$BPID" 2>/dev/null; then
      kill "$BPID" 2>/dev/null || true
      wait "$BPID" 2>/dev/null || true
    fi
  }
  trap cleanup EXIT INT TERM

  local _
  for _ in $(seq 1 45); do
    if curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
      echo "Backend healthy."
      break
    fi
    sleep 1
  done
  if ! curl -fsS --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Backend did not respond on :${PORT}/health." >&2
    exit 1
  fi

  echo "Starting frontend (退出 Vite 会结束本脚本并停止上述后端)…"
  run_frontend_fg || true
}

bootstrap_only() {
  echo "=== ZenHeart v2 — bootstrap only (no dev servers) ==="
  require_docker
  docker_up_pg
  wait_postgres
  venv_and_pip
  mkdir_data
  ensure_env_file
  verify_core || exit 1
  print_urls
  echo "Bootstrap done. Run full stack: cd $ROOT && ./local.sh"
  echo "Or: cd $ROOT && ./local.sh --quick"
  echo ""
}

case "$MODE" in
  verify)
    verify_with_optional_backend
    ;;
  bootstrap)
    bootstrap_only
    ;;
  backend)
    run_backend_fg
    ;;
  frontend)
    run_frontend_fg
    ;;
  run)
    echo "=== ZenHeart v2 — local (Docker + API + Vite) ==="
    run_full
    ;;
esac
