#!/usr/bin/env bash
# One-shot: start Postgres (Docker), Python 3.11 venv + pip, local data dirs, print next steps.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

echo "=== ZenHeart v2 — local deploy bootstrap ==="

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker CLI not found. Install Docker Desktop and retry." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker Desktop, wait until it is ready, then run:" >&2
  echo "  $ROOT/deploy-local.sh" >&2
  exit 1
fi

echo "Starting PostgreSQL (docker compose)…"
docker compose -f "$ROOT/backend/docker-compose.yml" up -d

echo "Waiting for PostgreSQL on 127.0.0.1:5433…"
ready=0
for _ in $(seq 1 45); do
  if command -v nc >/dev/null 2>&1 && nc -z 127.0.0.1 5433 2>/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "Port 5433 did not open in time. Check: docker compose -f $ROOT/backend/docker-compose.yml logs" >&2
  exit 1
fi

PY311=""
if command -v python3.11 >/dev/null 2>&1; then
  PY311="$(command -v python3.11)"
elif [[ -x "/opt/homebrew/bin/python3.11" ]]; then
  PY311="/opt/homebrew/bin/python3.11"
else
  echo "python3.11 not found. Install Python 3.11+ and retry." >&2
  exit 1
fi

if [[ ! -d "$ROOT/backend/.venv_py311" ]]; then
  echo "Creating .venv_py311 …"
  "$PY311" -m venv "$ROOT/backend/.venv_py311"
fi
# shellcheck disable=SC1091
source "$ROOT/backend/.venv_py311/bin/activate"
pip install -q --upgrade pip
pip install -q -r "$ROOT/backend/requirements.txt"

mkdir -p "$ROOT/backend/local-data/news" "$ROOT/backend/local-data/media/images"

echo ""
echo "Bootstrap done."
echo ""
echo "1. Ensure v2/backend/.env exists (copy from .env.example): DATABASE_URL must match Docker Postgres."
echo "   postgresql+asyncpg://zenheart:zenheart@127.0.0.1:5433/zenheart_v2"
echo ""
echo "2. Terminal A — backend:"
echo "     cd $ROOT && ./dev-backend.sh"
echo ""
echo "3. Terminal B — frontend:"
echo "     cd $ROOT && ./dev-frontend.sh"
echo ""
echo "WebSocket 调试页（需管理员 Key 轮询 /feed）："
echo "   http://127.0.0.1:8090/v2/admin/debug/ws"
echo "   或 Vite 代理  http://127.0.0.1:5173/v2/admin/debug/ws"
echo ""
