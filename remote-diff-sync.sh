#!/usr/bin/env bash
# Compare local v2 trees with EC2 deployment, and pull/push app files over SSH+rsync.
# Uses the same defaults as deploy-backend.sh / deploy-frontend.sh (see --help).
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"
BACKEND="$V2_ROOT/backend"
FRONTEND="$V2_ROOT/frontend"

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/aws/zenheart-ec2.pem}"
ZENHEART_EC2_HOST="${ZENHEART_EC2_HOST:-51.21.54.93}"
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
REMOTE_BACKEND="${ZENHEART_V2_REMOTE_DIR:-/opt/zenheart/services/v2_backend}"
REMOTE_WEB="${ZENHEART_WEB_DIR:-/opt/zenheart/frontend}"
# Home-relative staging dir on EC2 for frontend push (same default as deploy-frontend.sh).
FRONTEND_STAGING="${ZENHEART_V2_STAGING:-zenheart-v2-frontend-dist}"

die() { echo "error: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
usage: remote-diff-sync.sh <diff|pull|push> <backend|frontend> [--checksum]

  diff    Dry-run: show what differs between local and remote (rsync -n).
  pull    Copy remote tree into local (backend: v2/backend; frontend: v2/frontend/dist-remote/).
  push    Copy local tree to remote (backend: same file set as deploy-backend rsync;
          frontend: dist/ → home staging → sudo rsync into web root + nginx reload, like deploy-frontend.sh).

  --checksum   Use rsync -c (slower, compares file checksums, not only size/mtime).

Environment (override any):
  ZENHEART_EC2_KEY       SSH private key (default: ../aws/zenheart-ec2.pem)
  ZENHEART_EC2_HOST      Host (default: 51.21.54.93)
  ZENHEART_EC2_USER      SSH user (default: ec2-user)
  ZENHEART_V2_REMOTE_DIR Backend path on server (default: /opt/zenheart/services/v2_backend)
  ZENHEART_WEB_DIR       Static frontend path on server (default: /opt/zenheart/frontend)
  ZENHEART_V2_STAGING    Home-relative dir for frontend push staging (default: zenheart-v2-frontend-dist)

Notes:
  - Backend pull never overwrites your local .env (excluded). Remote .env stays on the server.
  - Backend push does not upload local .env (matches deploy-backend.sh).
  - Full install (venv, pip, systemd) is still: ./v2/deploy-backend.sh
  - Full frontend install + nginx: ./v2/deploy-frontend.sh
EOF
}

ACTION="${1:-}"
TARGET="${2:-}"
CHECKSUM=0
for a in "$@"; do
  [[ "$a" == "--checksum" ]] && CHECKSUM=1
done

[[ -n "$ACTION" && -n "$TARGET" ]] || { usage >&2; exit 2; }
[[ "$ACTION" == diff || "$ACTION" == pull || "$ACTION" == push ]] || die "first arg must be diff, pull, or push"
[[ "$TARGET" == backend || "$TARGET" == frontend ]] || die "second arg must be backend or frontend"

[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"
chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_BASE=(ssh -i "$ZENHEART_EC2_KEY" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=5 -o ConnectTimeout=15)
RSH="${SSH_BASE[*]}"

RSYNC_BACKEND_EXCLUDES=(
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='*.pyc'
  --exclude='.pytest_cache/'
  --exclude='.git/'
)

RSYNC_N=(-n)
[[ "$CHECKSUM" -eq 1 ]] && RSYNC_N=(-nc)

REMOTE_BACKEND_URI="$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_BACKEND/"
REMOTE_WEB_URI="$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_WEB/"

case "$TARGET" in
  backend)
    [[ -d "$BACKEND" ]] || die "missing $BACKEND"
    case "$ACTION" in
      diff)
        echo "[diff backend] local $BACKEND/ vs $REMOTE_BACKEND_URI (dry-run)"
        rsync -av "${RSYNC_N[@]}" --delete \
          "${RSYNC_BACKEND_EXCLUDES[@]}" \
          --exclude='.env' \
          -e "$RSH" \
          "$BACKEND/" "$REMOTE_BACKEND_URI"
        ;;
      pull)
        echo "[pull backend] $REMOTE_BACKEND_URI -> $BACKEND/ (remote .env excluded; never overwrite local secrets from pull)"
        rsync -avz --delete \
          "${RSYNC_BACKEND_EXCLUDES[@]}" \
          --exclude='.env' \
          -e "$RSH" \
          "$REMOTE_BACKEND_URI" "$BACKEND/"
        echo "[pull backend] done"
        ;;
      push)
        echo "[push backend] $BACKEND/ -> $REMOTE_BACKEND_URI (no venv/pip/systemd; for full deploy run deploy-backend.sh)"
        rsync -avz --delete \
          "${RSYNC_BACKEND_EXCLUDES[@]}" \
          --exclude='.env' \
          -e "$RSH" \
          "$BACKEND/" "$REMOTE_BACKEND_URI"
        echo "[push backend] done (restart service on host if needed: sudo systemctl restart zenheart-v2-backend)"
        ;;
    esac
    ;;
  frontend)
    [[ -d "$FRONTEND" ]] || die "missing $FRONTEND"
    case "$ACTION" in
      diff)
        [[ -d "$FRONTEND/dist" ]] || die "missing $FRONTEND/dist — run: (cd $FRONTEND && npm run build)"
        echo "[diff frontend] local $FRONTEND/dist/ vs $REMOTE_WEB_URI (dry-run)"
        rsync -av "${RSYNC_N[@]}" --delete -e "$RSH" "$FRONTEND/dist/" "$REMOTE_WEB_URI"
        ;;
      pull)
        OUT="$FRONTEND/dist-remote"
        mkdir -p "$OUT"
        echo "[pull frontend] $REMOTE_WEB_URI -> $OUT/"
        rsync -avz --delete -e "$RSH" "$REMOTE_WEB_URI" "$OUT/"
        echo "[pull frontend] done"
        ;;
      push)
        [[ -d "$FRONTEND/dist" ]] || die "missing $FRONTEND/dist — run: (cd $FRONTEND && npm run build)"
        STG_URI="$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$FRONTEND_STAGING/"
        echo "[push frontend] $FRONTEND/dist/ -> $STG_URI then sudo install -> $REMOTE_WEB (nginx reload)"
        rsync -avz --delete -e "$RSH" "$FRONTEND/dist/" "$STG_URI"
        "${SSH_BASE[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
          env REMOTE_WEB="$REMOTE_WEB" STAGING_DIR="$FRONTEND_STAGING" \
          bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
WEB_DIR="${REMOTE_WEB:?}"
STG="${HOME}/${STAGING_DIR:?}"
sudo mkdir -p "$WEB_DIR"
if id nginx >/dev/null 2>&1; then U=nginx
elif id www-data >/dev/null 2>&1; then U=www-data
else U=root
fi
sudo rsync -a --delete "$STG/" "$WEB_DIR/"
sudo chown -R "$U:$U" "$WEB_DIR"
rm -rf "$STG"
sudo nginx -t
sudo systemctl reload nginx
echo "ok: $WEB_DIR"
REMOTE_SCRIPT
        echo "[push frontend] done"
        ;;
    esac
    ;;
esac
