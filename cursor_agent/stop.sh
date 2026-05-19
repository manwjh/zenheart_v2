#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$ROOT/cursor_agent"
PY="$AGENT_DIR/.venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "cursor_agent venv missing: $PY" >&2
  exit 1
fi

exec "$PY" "$AGENT_DIR/cursor_agent.py" stop --kill "$@"
