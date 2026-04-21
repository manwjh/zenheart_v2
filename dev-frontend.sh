#!/usr/bin/env bash
# Local Vite dev server for v2/frontend (pass-through extra args to npm).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT/frontend"
exec npm run dev -- "$@"
