#!/usr/bin/env bash
# Build v2 Vue app and sync dist/ to production nginx docroot.
# Defaults match aws/AWS_ACCESS_GUIDE.md; override with env vars.
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"
FRONTEND="$V2_ROOT/frontend"

die() { echo "error: $*" >&2; exit 1; }

# Optional local deploy secrets (gitignored). Copy from .deploy-env.example.
if [[ -f "$V2_ROOT/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$V2_ROOT/.deploy-env"
  set +a
fi

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/aws/zenheart-ec2.pem}"
ZENHEART_EC2_HOST="${ZENHEART_EC2_HOST:-}"
[[ -n "$ZENHEART_EC2_HOST" ]] || die "ZENHEART_EC2_HOST is not set (export ZENHEART_EC2_HOST=<ip>)"
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
ZENHEART_WEB_DIR="${ZENHEART_WEB_DIR:-/opt/zenheart/frontend}"
STAGING_DIR="${ZENHEART_V2_STAGING:-zenheart-v2-frontend-dist}"

[[ -d "$FRONTEND" ]] || die "missing $FRONTEND"
[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"

chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh -i "$ZENHEART_EC2_KEY"
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=5
  -o ConnectTimeout=15
)

echo "[v2] npm run build → $FRONTEND"
(cd "$FRONTEND" && npm run build)

echo "[v2] rsync dist/ → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$STAGING_DIR/"
rsync -avz --delete \
  -e "${SSH_CMD[*]}" \
  "$FRONTEND/dist/" \
  "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$STAGING_DIR/"

echo "[v2] install to $ZENHEART_WEB_DIR and reload nginx"
"${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" bash <<EOF
set -euo pipefail
WEB_DIR="$ZENHEART_WEB_DIR"
STG="\$HOME/$STAGING_DIR"
sudo mkdir -p "\$WEB_DIR"
if id nginx >/dev/null 2>&1; then U=nginx
elif id www-data >/dev/null 2>&1; then U=www-data
else U=root
fi
# Exclude news/ so the persistent news/images symlink survives --delete.
sudo rsync -a --delete --exclude=news/ "\$STG/" "\$WEB_DIR/"
sudo chown -R "\$U:\$U" "\$WEB_DIR"
rm -rf "\$STG"
# Restore the news/images symlink if it was removed or never created.
NEWS_IMAGES_LINK="\$WEB_DIR/news/images"
if [[ ! -e "\$NEWS_IMAGES_LINK" && ! -L "\$NEWS_IMAGES_LINK" ]]; then
  sudo mkdir -p "\$WEB_DIR/news"
  sudo ln -s /opt/zenheart/news/images "\$NEWS_IMAGES_LINK"
  echo "created symlink: \$NEWS_IMAGES_LINK -> /opt/zenheart/news/images"
fi
sudo nginx -t
sudo systemctl reload nginx
echo "ok: \$WEB_DIR (user \$U)"
ls -la "\$WEB_DIR" | head -16
EOF

echo "[v2] deploy-frontend.sh done"
