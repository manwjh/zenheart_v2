#!/usr/bin/env bash
# Terminal 1 — FastAPI + Uvicorn :8090 (reload).
# Requires PostgreSQL reachable per v2/backend/.env (see deploy-local.sh).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/backend"

PYTHON_BIN=""
if [[ -x "$ROOT/backend/.venv_py311/bin/python" ]]; then
  PYTHON_BIN="$ROOT/backend/.venv_py311/bin/python"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "No Python interpreter found. Run ./deploy-local.sh first." >&2
  exit 1
fi

mkdir -p "$ROOT/backend/local-data/news" "$ROOT/backend/local-data/media/images"

# Overrides env file when present so local dirs work without /opt paths.
export NEWS_MARKDOWN_ROOT="${NEWS_MARKDOWN_ROOT:-$ROOT/backend/local-data/news}"
export MEDIA_ROOT="${MEDIA_ROOT:-$ROOT/backend/local-data/media}"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8090}"

echo "Uvicorn http://127.0.0.1:${PORT} — WS debug: http://127.0.0.1:${PORT}/v2/admin/debug/ws"
exec "$PYTHON_BIN" -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --reload
