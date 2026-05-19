#!/usr/bin/env bash
# ZenHeart v2 local entrypoint: Docker Postgres + venv + .env + Uvicorn + Vite.
#
#   ./local.sh                  Full stack; foreground Vite stops the backend child on exit.
#   ./local.sh --quick          Skip dependency install when the venv already exists.
#   ./local.sh --bootstrap-only Prepare Docker, venv, .env, and database only.
#   ./local.sh --verify-only    Check .env, settings, database port, and optional backend health.
#   ./local.sh --backend-only   Run Uvicorn in the foreground.
#   ./local.sh --frontend-only  Run Vite in the foreground; backend must already be running.
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
ZenHeart v2 local entrypoint

  ./local.sh                  Full stack; exiting Vite stops the backend child
  ./local.sh --quick          Skip pip install when the venv already exists
  ./local.sh --bootstrap-only Prepare Docker / venv / .env / database
  ./local.sh --verify-only    Check .env, settings, 5433, and optional :8090
  ./local.sh --backend-only   Run Uvicorn in the foreground
  ./local.sh --frontend-only  Run Vite in the foreground
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

# Stop a single TCP listener on $1 so Uvicorn/Vite can bind. Uses kill(1), OS-wide for
# that PID; restricted to non-privileged ports and a small denylist (DB/SSH/etc.).
stop_listener_on_port() {
  local port="$1"
  local label="${2:-$port}"
  local deny
  if ! [[ "$port" =~ ^[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$port" -lt 1024 ]]; then
    echo "Will not kill listeners on privileged port ${port} (${label}). Use PORT/FRONT_PORT >= 1024." >&2
    return 0
  fi
  for deny in 22 5432 5433 3306 6379 27017; do
    if [[ "$port" == "$deny" ]]; then
      return 0
    fi
  done
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pids
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$pids" ]]; then
    return 0
  fi
  echo "Stopping existing listener on ${label} (TCP ${port})..."
  local pid
  for pid in $pids; do
    if [[ "$pid" =~ ^[0-9]+$ ]] && [[ "$pid" -gt 1 ]] && [[ "$pid" -ne $$ ]]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  sleep 1
  pids="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  for pid in $pids; do
    if [[ "$pid" =~ ^[0-9]+$ ]] && [[ "$pid" -gt 1 ]] && [[ "$pid" -ne $$ ]]; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
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
  echo "Starting PostgreSQL (docker compose)..."
  docker compose -f "$BACKEND/docker-compose.yml" up -d
}

wait_postgres() {
  echo "Waiting for PostgreSQL on 127.0.0.1:5433..."
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
    echo "Creating .venv_py311..."
    "$PY311" -m venv "$BACKEND/.venv_py311"
    QUICK=0
  fi
  if [[ "$QUICK" == 1 ]]; then
    return 0
  fi
  local vpy="$BACKEND/.venv_py311/bin/python"
  "$vpy" -m pip install -q --upgrade pip
  "$vpy" -m pip install -q -r "$BACKEND/requirements.txt"
}

ensure_env_file() {
  if [[ -f "$BACKEND/.env" ]]; then
    return 0
  fi
  echo "No backend/.env; creating it from .env.example with local news/media paths."
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
  echo "Edit ADMIN_API_KEY in $BACKEND/.env before any real deployment."
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
    echo -e "${RED}FAIL${NC} Missing $BACKEND/.env; run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    return 1
  fi
  echo -e "${GREEN}OK${NC} .env present"
  local pb
  pb="$(python_run)" || true
  if [[ -z "${pb:-}" ]] || [[ ! -x "$pb" ]]; then
    echo -e "${RED}FAIL${NC} No Python / venv; run full ./local.sh once." >&2
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
    echo -e "${RED}FAIL${NC} Nothing on 127.0.0.1:5433; start DB with ./local.sh --bootstrap-only" >&2
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
      echo -e "${GREEN}OK${NC} Backend :${PORT}/health => $body"
      backend_ok=1
    else
      echo -e "${YELLOW}WARN${NC} Port ${PORT} open but /health not JSON" >&2
      fail=1
    fi
  else
    echo -e "${YELLOW}WARN${NC} Backend not on :${PORT}; expected until ./local.sh or ./local.sh --backend-only"
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
    echo "Missing $BACKEND/.env; run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    exit 1
  fi
  mkdir_data
  export_local_overrides
  echo "Preflight (load settings)..."
  if ! "$pb" -c "from app.config import load_settings; load_settings()" 2>/tmp/zenheart_local_preflight.err; then
    cat /tmp/zenheart_local_preflight.err >&2
    echo "Fix .env (see .env.example) or run: cd $ROOT && ./local.sh --verify-only" >&2
    exit 1
  fi
}

run_backend_migrations() {
  cd "$BACKEND"
  local pb
  pb="$(python_run)" || true
  if [[ -z "${pb:-}" ]]; then
    echo "No Python interpreter. Run: cd $ROOT && ./local.sh --bootstrap-only" >&2
    exit 1
  fi
  export_local_overrides
  echo "Preparing database schema..."
  "$pb" - <<'PY'
import asyncio

from app.config import load_settings
from app.db import create_engine, init_db


async def main() -> None:
    settings = load_settings()
    engine = create_engine(settings)
    try:
        await init_db(engine)
    finally:
        await engine.dispose()


asyncio.run(main())
PY
  echo "Applying database migrations..."
  local database_url
  if ! database_url="$("$pb" - <<'PY'
from app.config import load_settings

print(load_settings().database_url)
PY
  )"; then
    echo "Could not load DATABASE_URL from backend settings." >&2
    exit 1
  fi
  DATABASE_URL="$database_url" "$pb" -u scripts/run_migrations.py scripts/migrations
}

run_backend_fg() {
  stop_listener_on_port "$PORT" "backend"
  preflight_backend
  run_backend_migrations
  stop_listener_on_port "$PORT" "backend"
  local pb
  pb="$(python_run)"
  echo "Uvicorn http://127.0.0.1:${PORT} - docs http://127.0.0.1:${PORT}/docs - WS debug http://127.0.0.1:${PORT}/v2/admin/debug/ws"
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
  echo "------------------------------------------------------------"
  echo "  Local URLs"
  echo "------------------------------------------------------------"
  echo "  PostgreSQL     127.0.0.1:5433"
  echo "  Backend        http://127.0.0.1:${PORT}/   (override with PORT=...)"
  echo "  Frontend       http://127.0.0.1:${FRONT_PORT}/"
  echo "  WS debug       http://127.0.0.1:${PORT}/v2/admin/debug/ws"
  echo "                 http://127.0.0.1:${FRONT_PORT}/v2/admin/debug/ws  (via Vite proxy)"
  echo "------------------------------------------------------------"
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
  run_backend_migrations
  print_urls

  stop_listener_on_port "$PORT" "backend"
  echo "Starting backend in background (http://127.0.0.1:${PORT})..."
  (
    cd "$BACKEND"
    export_local_overrides
    exec "$(python_run)" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
  ) &
  # Not `local`: nested trap cleanup must see this PID under bash 3.x (macOS default).
  BPID=$!

  cleanup() {
    local pid="${BPID:-}"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
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

  echo "Starting frontend. Exiting Vite stops the backend child from this run."
  run_frontend_fg || true
}

bootstrap_only() {
  echo "=== ZenHeart v2 bootstrap only (no dev servers) ==="
  require_docker
  docker_up_pg
  wait_postgres
  venv_and_pip
  mkdir_data
  ensure_env_file
  verify_core || exit 1
  run_backend_migrations
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
    echo "=== ZenHeart v2 local (Docker + API + Vite) ==="
    run_full
    ;;
esac
