#!/usr/bin/env bash
# Deploy v2 FastAPI backend to EC2: rsync code, venv+pip, optional psql client, migrations, systemd.
# Defaults match aws/AWS_ACCESS_GUIDE.md. Requires a populated remote .env (see docs).
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"
BACKEND="$V2_ROOT/backend"

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
if [[ -z "$ZENHEART_EC2_HOST" ]]; then
  if [[ ! -f "$V2_ROOT/.deploy-env" ]]; then
    die "ZENHEART_EC2_HOST is not set (EC2 IP or DNS). Create $V2_ROOT/.deploy-env from .deploy-env.example and set export ZENHEART_EC2_HOST=... — e.g. cp \"$V2_ROOT/.deploy-env.example\" \"$V2_ROOT/.deploy-env\""
  fi
  die "ZENHEART_EC2_HOST is not set (EC2 IP or DNS). Edit $V2_ROOT/.deploy-env: set export ZENHEART_EC2_HOST=<ip-or-dns> to a non-empty value."
fi
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
REMOTE_DIR="${ZENHEART_V2_REMOTE_DIR:-/opt/zenheart/services/v2_backend}"
SERVICE_NAME="${ZENHEART_V2_SERVICE_NAME:-zenheart-v2-backend}"
ZENHEART_V2_SKIP_NGINX="${ZENHEART_V2_SKIP_NGINX:-0}"
# Default 0: do not ship sovereign-admin FAQ markdown or admin OpenClaw skill to production (leak risk).
# Set ZENHEART_V2_DEPLOY_INCLUDE_ADMIN=1 in .deploy-env for a staging host that needs the full bundle.
ZENHEART_V2_DEPLOY_INCLUDE_ADMIN="${ZENHEART_V2_DEPLOY_INCLUDE_ADMIN:-0}"

DOCS_RSYNC_EXCLUDES=()
SKILLS_RSYNC_EXCLUDES=()
if [[ "${ZENHEART_V2_DEPLOY_INCLUDE_ADMIN}" != "1" ]]; then
  DOCS_RSYNC_EXCLUDES=(
    --exclude='admin-websocket.md'
  )
  SKILLS_RSYNC_EXCLUDES=(
    --exclude='zenheart-admin-agent/'
  )
  echo "[v2-backend] FAQ sync excludes sovereign-admin skill folder zenheart-admin-agent/ (and admin-websocket.md). Set ZENHEART_V2_DEPLOY_INCLUDE_ADMIN=1 to include."
fi

[[ -d "$BACKEND" ]] || die "missing $BACKEND"
[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"

chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh -i "$ZENHEART_EC2_KEY"
  -o StrictHostKeyChecking=accept-new
  -o ServerAliveInterval=5
  -o ConnectTimeout=15
)

echo "[v2-backend] rsync → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_DIR/"
rsync -avz --delete \
  -e "${SSH_CMD[*]}" \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache/' \
  --exclude='.env' \
  --exclude='.git/' \
  "$BACKEND/" \
  "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_DIR/"

# FAQ markdown guides: app resolves DOCS_DIR to "$(dirname REMOTE_DIR)/docs" on the server.
DOCS_STAGING="${ZENHEART_V2_DOCS_STAGING:-zenheart-v2-docs-staging}"
SYNCED_DOCS=0
if [[ -d "$V2_ROOT/docs" ]]; then
  SYNCED_DOCS=1
  echo "[v2-backend] rsync markdown guides → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$DOCS_STAGING/"
  rsync -avz --delete \
    -e "${SSH_CMD[*]}" \
    "${DOCS_RSYNC_EXCLUDES[@]}" \
    "$V2_ROOT/docs/" \
    "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$DOCS_STAGING/"
fi

# Skills: app resolves SKILLS_DIR to "$(dirname REMOTE_DIR)/skills" on the server.
SKILLS_STAGING="${ZENHEART_V2_SKILLS_STAGING:-zenheart-v2-skills-staging}"
SYNCED_SKILLS=0
if [[ -d "$V2_ROOT/skills" ]]; then
  SYNCED_SKILLS=1
  echo "[v2-backend] rsync skills → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$SKILLS_STAGING/"
  rsync -avz --delete \
    -e "${SSH_CMD[*]}" \
    "${SKILLS_RSYNC_EXCLUDES[@]}" \
    "$V2_ROOT/skills/" \
    "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$SKILLS_STAGING/"
fi

echo "[v2-backend] remote install (venv, pip, psql client, migrations, systemd, optional nginx)"
"${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
  env REMOTE_DIR="$REMOTE_DIR" SERVICE_NAME="$SERVICE_NAME" SKIP_NGINX="$ZENHEART_V2_SKIP_NGINX" \
  SYNCED_DOCS="$SYNCED_DOCS" DOCS_STAGING="$DOCS_STAGING" \
  SYNCED_SKILLS="$SYNCED_SKILLS" SKILLS_STAGING="$SKILLS_STAGING" \
  bash -s <<'REMOTE_SCRIPT'
set -euo pipefail

sudo mkdir -p "$REMOTE_DIR" /etc/nginx/snippets
sudo chown -R "$(id -un):$(id -gn)" "$REMOTE_DIR"

# Create media directory for agent-uploaded images.
MEDIA_DIR="${ZENHEART_MEDIA_ROOT:-/opt/zenheart/media}"
sudo mkdir -p "$MEDIA_DIR/images"
sudo chown -R "$(id -un):$(id -gn)" "$MEDIA_DIR"

if [[ "${SYNCED_DOCS:-0}" == "1" && -n "${DOCS_STAGING:-}" && -d "$HOME/$DOCS_STAGING" ]]; then
  DOCS_REMOTE="$(dirname "$REMOTE_DIR")/docs"
  echo "[v2-backend] install markdown guides → $DOCS_REMOTE/"
  sudo mkdir -p "$DOCS_REMOTE"
  sudo rsync -a --delete "$HOME/$DOCS_STAGING/" "$DOCS_REMOTE/"
  sudo chown -R "$(id -un):$(id -gn)" "$DOCS_REMOTE"
  rm -rf "$HOME/$DOCS_STAGING"
fi

if [[ "${SYNCED_SKILLS:-0}" == "1" && -n "${SKILLS_STAGING:-}" && -d "$HOME/$SKILLS_STAGING" ]]; then
  SKILLS_REMOTE="$(dirname "$REMOTE_DIR")/skills"
  echo "[v2-backend] install skills → $SKILLS_REMOTE/"
  sudo mkdir -p "$SKILLS_REMOTE"
  sudo rsync -a --delete "$HOME/$SKILLS_STAGING/" "$SKILLS_REMOTE/"
  sudo chown -R "$(id -un):$(id -gn)" "$SKILLS_REMOTE"
  rm -rf "$HOME/$SKILLS_STAGING"
fi

if [[ ! -f "$REMOTE_DIR/.env" ]]; then
  if [[ -f "$REMOTE_DIR/.env.example" ]]; then
    cp "$REMOTE_DIR/.env.example" "$REMOTE_DIR/.env"
    chmod 600 "$REMOTE_DIR/.env"
    echo "Created $REMOTE_DIR/.env from .env.example."
    echo "SSH to the host, edit DATABASE_URL, ADMIN_API_KEY, and SMTP values, then run deploy-backend.sh again."
    exit 2
  fi
  echo "error: missing $REMOTE_DIR/.env (and no .env.example to bootstrap)" >&2
  exit 1
fi

# Ensure MEDIA_ROOT is set in .env; add default if missing.
if ! grep -q "^MEDIA_ROOT=" "$REMOTE_DIR/.env"; then
  echo "MEDIA_ROOT=$MEDIA_DIR" >> "$REMOTE_DIR/.env"
  echo "[v2-backend] added MEDIA_ROOT=$MEDIA_DIR to .env"
fi

if command -v python3.11 &>/dev/null; then PY=python3.11
elif command -v python3.12 &>/dev/null; then PY=python3.12
else PY=python3
fi

if [[ ! -d "$REMOTE_DIR/.venv" ]]; then
  "$PY" -m venv "$REMOTE_DIR/.venv"
fi
"$REMOTE_DIR/.venv/bin/pip" install --upgrade pip -q
"$REMOTE_DIR/.venv/bin/pip" install -r "$REMOTE_DIR/requirements.txt" -q

# Optional: install psql for ad-hoc SQL on the host (migrations use Python + asyncpg).
if ! command -v psql &>/dev/null; then
  echo "[v2-backend] installing PostgreSQL client (psql)"
  if command -v dnf &>/dev/null; then
    sudo dnf install -y postgresql15 &>/dev/null \
      || sudo dnf install -y postgresql16 &>/dev/null \
      || sudo dnf install -y postgresql &>/dev/null \
      || true
  elif command -v yum &>/dev/null; then
    sudo yum install -y postgresql15 &>/dev/null \
      || sudo yum install -y postgresql &>/dev/null \
      || true
  elif command -v apt-get &>/dev/null; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq \
      && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-client &>/dev/null \
      || true
  fi
  if command -v psql &>/dev/null; then
    echo "[v2-backend] psql installed: $(command -v psql)"
  else
    echo "[v2-backend] warn: psql not available after install attempt (migrations still use Python)" >&2
  fi
fi

# Apply schema migrations before restart (PostgreSQL via asyncpg).
set -a
# shellcheck disable=SC1091
source "$REMOTE_DIR/.env"
set +a
if [[ -d "$REMOTE_DIR/scripts/migrations" ]]; then
  echo "[v2-backend] migrations → $REMOTE_DIR/scripts/migrations/"
  "$REMOTE_DIR/.venv/bin/python" "$REMOTE_DIR/scripts/run_migrations.py" "$REMOTE_DIR/scripts/migrations"
fi

sudo cp "$REMOTE_DIR/deploy/zenheart-v2-backend.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sleep 2
if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "error: $SERVICE_NAME failed to start" >&2
  sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager >&2 || true
  exit 1
fi

if curl -sf "http://127.0.0.1:8090/health" | grep -q ok; then
  echo "ok: GET http://127.0.0.1:8090/health"
else
  echo "warn: health check failed on 8090" >&2
fi

if [[ "$SKIP_NGINX" != "1" ]] && command -v nginx &>/dev/null; then
  sudo cp "$REMOTE_DIR/deploy/nginx-v2-backend-upstream.conf" /etc/nginx/conf.d/zenheart-v2-backend-upstream.conf
  sudo cp "$REMOTE_DIR/deploy/nginx-v2-backend-location.conf" /etc/nginx/snippets/zenheart-v2-backend-location.conf
  echo "Installed nginx fragments. Inside your HTTPS server block for zenheart.net add (once):"
  echo "  include /etc/nginx/snippets/zenheart-v2-backend-location.conf;"
  if sudo nginx -t; then
    sudo systemctl reload nginx
    echo "ok: nginx reloaded"
  else
    echo "warn: nginx -t failed — fix config then reload nginx" >&2
  fi
elif [[ "$SKIP_NGINX" == "1" ]]; then
  echo "skip nginx (ZENHEART_V2_SKIP_NGINX=1)"
else
  echo "warn: nginx not installed; skipped nginx fragment install"
fi

echo "remote done: sudo systemctl status $SERVICE_NAME"
REMOTE_SCRIPT

echo "[v2-backend] deploy-backend.sh done"
echo "[v2-backend] admin CLI: $REMOTE_DIR/scripts/admin_agent_cli.py"
echo "[v2-backend] agent WS protocol: v2/docs/news-websocket.md"
