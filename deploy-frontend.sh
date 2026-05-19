#!/usr/bin/env bash
# Build v2 Vue app and sync dist/ to production nginx docroot.
# Defaults match aws/AWS_ACCESS_GUIDE.md; override with env vars.
# New routes (e.g. /#/wall) are included automatically in dist/; no extra deploy steps.
#
# zenlink/ under the web root is NOT touched by this script (--exclude=zenlink/), same idea as news/.
# Any legacy or operator-managed static tree there stays until removed on the host manually.
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"
FRONTEND="$V2_ROOT/frontend"

die() { echo "error: $*" >&2; exit 1; }

require_opt_zenheart_path() {
  local p="$1" name="$2"
  [[ "$p" == /* ]] || die "$name must be absolute (got: $p)"
  [[ "$p" == /opt/zenheart/* ]] || die "$name must be under /opt/zenheart/ (got: $p)"
  [[ "$p" != *..* ]] || die "$name must not contain .. (got: $p)"
}

# Staging folder name only (under remote $HOME); no slashes — avoids path tricks in rsync target.
require_staging_name() {
  local n="$1" name="$2"
  [[ "$n" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]] || die "$name must be a single path segment [a-zA-Z0-9._-] (got: $n)"
}

# Optional local deploy secrets (gitignored). Copy from .deploy-env.example.
if [[ -f "$V2_ROOT/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$V2_ROOT/.deploy-env"
  set +a
fi

if [[ -n "${ZENHEART_SSH_KNOWN_HOSTS:-}" ]] && [[ ! -f "$ZENHEART_SSH_KNOWN_HOSTS" ]]; then
  if [[ -f "$V2_ROOT/.ssh/known_hosts" ]]; then
    echo "[v2-frontend] ZENHEART_SSH_KNOWN_HOSTS file missing (${ZENHEART_SSH_KNOWN_HOSTS-}) — using $V2_ROOT/.ssh/known_hosts" >&2
    ZENHEART_SSH_KNOWN_HOSTS="$V2_ROOT/.ssh/known_hosts"
  else
    unset ZENHEART_SSH_KNOWN_HOSTS || true
  fi
fi

SSH_HOSTKEY_ARGS=()
if [[ -n "${ZENHEART_SSH_KNOWN_HOSTS:-}" ]]; then
  [[ -f "$ZENHEART_SSH_KNOWN_HOSTS" ]] || die "ZENHEART_SSH_KNOWN_HOSTS is set but not a regular file: $ZENHEART_SSH_KNOWN_HOSTS"
  SSH_HOSTKEY_ARGS=(
    -o StrictHostKeyChecking=yes
    -o "UserKnownHostsFile=$ZENHEART_SSH_KNOWN_HOSTS"
    -o GlobalKnownHostsFile=/dev/null
  )
elif [[ "${ZENHEART_SSH_ACCEPT_NEW:-0}" == "1" ]]; then
  SSH_HOSTKEY_ARGS=(-o StrictHostKeyChecking=accept-new)
else
  die "SSH host key: set ZENHEART_SSH_KNOWN_HOSTS to a known_hosts file, or set ZENHEART_SSH_ACCEPT_NEW=1 (less safe). Example: mkdir -p \"$V2_ROOT/.ssh\" && ssh-keyscan -H \"\${ZENHEART_EC2_HOST:-<ec2-host>}\" >>\"$V2_ROOT/.ssh/known_hosts\" && export ZENHEART_SSH_KNOWN_HOSTS=\"$V2_ROOT/.ssh/known_hosts\""
fi

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/aws/zenheart-ec2.pem}"
ZENHEART_EC2_HOST="${ZENHEART_EC2_HOST:-}"
if [[ -z "$ZENHEART_EC2_HOST" ]]; then
  if [[ ! -f "$V2_ROOT/.deploy-env" ]]; then
    die "ZENHEART_EC2_HOST is not set (EC2 IP or DNS). Create $V2_ROOT/.deploy-env from .deploy-env.example and set export ZENHEART_EC2_HOST=... — e.g. cp \"$V2_ROOT/.deploy-env.example\" \"$V2_ROOT/.deploy-env\""
  fi
  die "ZENHEART_EC2_HOST is not set (EC2 IP or DNS). Edit $V2_ROOT/.deploy-env: set export ZENHEART_EC2_HOST=<ip-or-dns> to a non-empty value."
fi
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
ZENHEART_WEB_DIR="${ZENHEART_WEB_DIR:-/opt/zenheart/frontend}"
STAGING_DIR="${ZENHEART_V2_STAGING:-zenheart-v2-frontend-dist}"

require_opt_zenheart_path "$ZENHEART_WEB_DIR" "ZENHEART_WEB_DIR"
require_staging_name "$STAGING_DIR" "ZENHEART_V2_STAGING"

[[ -d "$FRONTEND" ]] || die "missing $FRONTEND"
[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"

chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh -i "$ZENHEART_EC2_KEY"
  "${SSH_HOSTKEY_ARGS[@]}"
  -o BatchMode=yes
  -o ServerAliveInterval=5
  -o ConnectTimeout=15
)

RSYNC_RSH="$(printf '%q ' "${SSH_CMD[@]}")"
RSYNC_RSH="${RSYNC_RSH% }"

if [[ -n "${VITE_SOCIAL_OBSERVE_TOKEN:-}" ]]; then
  export VITE_SOCIAL_OBSERVE_TOKEN
  echo "[v2-frontend] VITE_SOCIAL_OBSERVE_TOKEN is set (embedded at build time; match backend SOCIAL_OBSERVE_SHARED_TOKEN)"
else
  echo "[v2-frontend] VITE_SOCIAL_OBSERVE_TOKEN unset — SPA uses open observe unless backend also leaves token empty"
fi
echo "[v2] npm run build → $FRONTEND"
(
  cd "$FRONTEND"
  # Cursor's sandbox may inject npm_config_devdir; npm 11 warns this key is deprecated.
  unset npm_config_devdir
  npm run build
)

echo "[v2] rsync dist/ → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$STAGING_DIR/ (exclude zenlink/: not part of SPA dist)"
rsync -avz --delete --exclude=zenlink/ \
  -e "$RSYNC_RSH" \
  "$FRONTEND/dist/" \
  "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$STAGING_DIR/"

echo "[v2] install to $ZENHEART_WEB_DIR and reload nginx"
"${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
  env "ZENHEART_WEB_DIR=$ZENHEART_WEB_DIR" "ZENHEART_V2_STAGING_NAME=$STAGING_DIR" \
  bash -s <<'REMOTE_INSTALL'
set -euo pipefail
WEB_DIR="${ZENHEART_WEB_DIR:?}"
STG="${HOME:?}/${ZENHEART_V2_STAGING_NAME:?}"
case "$WEB_DIR" in
  /opt/zenheart/*) ;;
  *) echo "error: WEB_DIR must be under /opt/zenheart/ (got: $WEB_DIR)" >&2; exit 1 ;;
esac
[[ "$WEB_DIR" != *..* ]] || { echo "error: WEB_DIR must not contain .." >&2; exit 1; }
sudo mkdir -p "$WEB_DIR"
if id nginx >/dev/null 2>&1; then U=nginx
elif id www-data >/dev/null 2>&1; then U=www-data
else U=root
fi
# Exclude news/ so the persistent news/images symlink survives --delete.
# Exclude zenlink/ so an existing nginx-docroot zenlink/ tree (if any) is not wiped by SPA --delete.
sudo rsync -a --delete --exclude=news/ --exclude=zenlink/ "$STG/" "$WEB_DIR/"
sudo chown -R "$U:$U" "$WEB_DIR"
rm -rf "$STG"
# Restore the news/images symlink if it was removed or never created.
NEWS_IMAGES_LINK="$WEB_DIR/news/images"
if [[ ! -e "$NEWS_IMAGES_LINK" && ! -L "$NEWS_IMAGES_LINK" ]]; then
  sudo mkdir -p "$WEB_DIR/news"
  sudo ln -s /opt/zenheart/news/images "$NEWS_IMAGES_LINK"
  echo "created symlink: $NEWS_IMAGES_LINK -> /opt/zenheart/news/images"
fi
sudo nginx -t
sudo systemctl reload nginx
echo "ok: $WEB_DIR (user $U)"
ls -la "$WEB_DIR" | head -16
REMOTE_INSTALL

echo "[v2] deploy-frontend.sh done"
