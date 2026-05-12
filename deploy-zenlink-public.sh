#!/usr/bin/env bash
# Build zenlink-mcp OpenClaw installers + tarballs, refresh release-manifest.json, upload to production
# nginx docroot .../zenlink/, and remove older versioned OpenClaw files on the server.
#
# Requires v2/.deploy-env (see v2/.deploy-env.example): ZENHEART_EC2_HOST, ZENHEART_SSH_KNOWN_HOSTS
# (or rely on publish script fallbacks). Same SSH key vars as v2/deploy-frontend.sh.
#
# Usage (from repo root):
#   chmod +x v2/deploy-zenlink-public.sh
#   ./v2/deploy-zenlink-public.sh
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${V2_ROOT}/packages/zenlink-mcp/scripts/publish-zenlink-artifacts.sh"
