#!/usr/bin/env bash
# Full ZenHeart v2 production refresh on EC2: backend then SPA.
# - deploy-backend.sh: pack/upload v2/backend (+ v2/docs + v2/skills unless ZENHEART_V2_SKIP_DOCS_SKILLS_BUNDLE=1)
# - deploy-faq-files.sh: rsync docs + skills only (not called here; use when prose changes often)
# - deploy-frontend.sh: npm run build, rsync dist/ (excludes zenlink/ on server; use deploy-zenlink-public.sh for bundles)
#
# Prerequisites: v2/.deploy-env (copy from .deploy-env.example) with ZENHEART_EC2_HOST and SSH host key handling.
# Same variables as the individual scripts; backend deploy rotates ADMIN_API_KEY unless ZENHEART_V2_NO_ROTATE_ADMIN_KEY=1.
#
# Usage from repository root:
#   chmod +x v2/deploy-production.sh
#   ./v2/deploy-production.sh
#
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=============================================================================="
echo "[deploy-production] ZenHeart v2 — backend, then frontend"
echo "[deploy-production] v2 root: $V2_ROOT"
echo "=============================================================================="

"$V2_ROOT/deploy-backend.sh"
"$V2_ROOT/deploy-frontend.sh"

echo "=============================================================================="
echo "[deploy-production] done — API + static assets updated on target host"
echo "=============================================================================="
