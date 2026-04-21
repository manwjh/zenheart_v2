#!/usr/bin/env bash
# Run FastAPI backend for v2 (requires v2/backend/.env and Postgres).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/backend"
exec uvicorn app.main:app --reload --host 0.0.0.0 --port 8090 "$@"
