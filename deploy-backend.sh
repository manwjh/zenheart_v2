#!/usr/bin/env bash
# Deploy v2 FastAPI backend to EC2: upload tarballs, extract, venv+pip, optional psql client, migrations, systemd.
# Defaults match aws/AWS_ACCESS_GUIDE.md. Requires a populated remote .env (see docs).
# The full tree under v2/backend/ is synced — new API routes (e.g. /v2/wall/*) need no extra deploy steps.
# FAQ markdown / skills only (no service restart): use deploy-faq-files.sh.
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"
BACKEND="$V2_ROOT/backend"

die() { echo "error: $*" >&2; exit 1; }

# Optional: rotate ADMIN_API_KEY on every deploy (default on). Writes to remote .env before restart,
# prints new key in the SSH transcript. Disable: export ZENHEART_V2_NO_ROTATE_ADMIN_KEY=1
# Copy last key to repo (gitignored): export ZENHEART_V2_SAVE_LAST_ADMIN_KEY=1
#
# Remote paths touched with sudo rm/rsync must stay under /opt/zenheart to limit blast radius.
require_opt_zenheart_path() {
  local p="$1" name="$2"
  [[ "$p" == /* ]] || die "$name must be absolute (got: $p)"
  [[ "$p" == /opt/zenheart/* ]] || die "$name must be under /opt/zenheart/ (got: $p)"
  [[ "$p" != *..* ]] || die "$name must not contain .. (got: $p)"
}

# Optional local deploy secrets (gitignored). Copy from .deploy-env.example.
# Must load before SSH host-key check so ZENHEART_SSH_KNOWN_HOSTS from .deploy-env applies.
if [[ -f "$V2_ROOT/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$V2_ROOT/.deploy-env"
  set +a
fi

# If .deploy-env references a known_hosts path from another machine/checkout, fall back to this v2/.ssh/known_hosts.
if [[ -n "${ZENHEART_SSH_KNOWN_HOSTS:-}" ]] && [[ ! -f "$ZENHEART_SSH_KNOWN_HOSTS" ]]; then
  if [[ -f "$V2_ROOT/.ssh/known_hosts" ]]; then
    echo "[v2-backend] ZENHEART_SSH_KNOWN_HOSTS file missing (${ZENHEART_SSH_KNOWN_HOSTS-}) — using $V2_ROOT/.ssh/known_hosts" >&2
    ZENHEART_SSH_KNOWN_HOSTS="$V2_ROOT/.ssh/known_hosts"
  else
    unset ZENHEART_SSH_KNOWN_HOSTS || true
  fi
fi

# SSH: require a pinned host key file, or explicit opt-in to accept-new (TOFU / MITM on first connect).
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
  die "SSH host key: set ZENHEART_SSH_KNOWN_HOSTS to a known_hosts file, or set ZENHEART_SSH_ACCEPT_NEW=1 (less safe). Example: mkdir -p \"$V2_ROOT/.ssh\" && ssh-keyscan -H \"\$ZENHEART_EC2_HOST\" >>\"$V2_ROOT/.ssh/known_hosts\" && export ZENHEART_SSH_KNOWN_HOSTS=\"$V2_ROOT/.ssh/known_hosts\""
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

require_opt_zenheart_path "$REMOTE_DIR" "ZENHEART_V2_REMOTE_DIR"
if [[ -n "${ZENHEART_MEDIA_ROOT:-}" ]]; then
  require_opt_zenheart_path "$ZENHEART_MEDIA_ROOT" "ZENHEART_MEDIA_ROOT"
fi

[[ -d "$BACKEND" ]] || die "missing $BACKEND"
[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY (set ZENHEART_EC2_KEY)"

chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh -i "$ZENHEART_EC2_KEY"
  "${SSH_HOSTKEY_ARGS[@]}"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=3
)
SCP_CMD=(
  scp -i "$ZENHEART_EC2_KEY"
  "${SSH_HOSTKEY_ARGS[@]}"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=3
)
# Entire remote install (pip, migrations, systemd, nginx) — cap whole SSH so a stuck remote
# does not block the deploy host forever. Override: ZENHEART_V2_REMOTE_SSH_MAX_S=3600
ZENHEART_V2_REMOTE_SSH_MAX_S="${ZENHEART_V2_REMOTE_SSH_MAX_S:-1800}"
_SSH_TIME_PREFIX=()
TIMEOUT_CMD=""
if command -v timeout &>/dev/null; then
  TIMEOUT_CMD="timeout"
elif command -v gtimeout &>/dev/null; then
  TIMEOUT_CMD="gtimeout"
fi
if [[ -n "$TIMEOUT_CMD" ]]; then
  _SSH_TIME_PREFIX=("$TIMEOUT_CMD" "$ZENHEART_V2_REMOTE_SSH_MAX_S")
fi

TAR_CREATE_CMD="tar"
if command -v gtar &>/dev/null; then
  TAR_CREATE_CMD="gtar"
fi

TMP_ARCHIVE_DIR="$(mktemp -d)"
cleanup_archives() {
  rm -rf "$TMP_ARCHIVE_DIR"
}
trap cleanup_archives EXIT

BACKEND_ARCHIVE_LOCAL="$TMP_ARCHIVE_DIR/backend.tar.gz"
BACKEND_ARCHIVE_NAME="${ZENHEART_V2_BACKEND_ARCHIVE_NAME:-zenheart-v2-backend.tar.gz}"
echo "[v2-backend] pack backend → $BACKEND_ARCHIVE_LOCAL"
COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 "$TAR_CREATE_CMD" -C "$BACKEND" -czf "$BACKEND_ARCHIVE_LOCAL" \
  --exclude='.venv' \
  --exclude='.venv_*' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='.env' \
  --exclude='.git' \
  .
echo "[v2-backend] upload backend archive → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$BACKEND_ARCHIVE_NAME"
"${SCP_CMD[@]}" "$BACKEND_ARCHIVE_LOCAL" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$BACKEND_ARCHIVE_NAME"

# FAQ markdown guides: app resolves DOCS_DIR to "$(dirname REMOTE_DIR)/docs" on the server.
DOCS_ARCHIVE_NAME="${ZENHEART_V2_DOCS_ARCHIVE_NAME:-zenheart-v2-docs.tar.gz}"
SYNCED_DOCS=0
if [[ -d "$V2_ROOT/docs" ]]; then
  SYNCED_DOCS=1
  DOCS_ARCHIVE_LOCAL="$TMP_ARCHIVE_DIR/docs.tar.gz"
  echo "[v2-backend] pack markdown guides → $DOCS_ARCHIVE_LOCAL"
  COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 "$TAR_CREATE_CMD" -C "$V2_ROOT/docs" -czf "$DOCS_ARCHIVE_LOCAL" .
  echo "[v2-backend] upload markdown guides archive → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$DOCS_ARCHIVE_NAME"
  "${SCP_CMD[@]}" "$DOCS_ARCHIVE_LOCAL" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$DOCS_ARCHIVE_NAME"
fi

# Skills: app resolves SKILLS_DIR to "$(dirname REMOTE_DIR)/skills" on the server.
SKILLS_ARCHIVE_NAME="${ZENHEART_V2_SKILLS_ARCHIVE_NAME:-zenheart-v2-skills.tar.gz}"
SYNCED_SKILLS=0
if [[ -d "$V2_ROOT/skills" ]]; then
  SYNCED_SKILLS=1
  SKILLS_ARCHIVE_LOCAL="$TMP_ARCHIVE_DIR/skills.tar.gz"
  echo "[v2-backend] pack skills → $SKILLS_ARCHIVE_LOCAL"
  COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 "$TAR_CREATE_CMD" -C "$V2_ROOT/skills" -czf "$SKILLS_ARCHIVE_LOCAL" .
  echo "[v2-backend] upload skills archive → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$SKILLS_ARCHIVE_NAME"
  "${SCP_CMD[@]}" "$SKILLS_ARCHIVE_LOCAL" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$SKILLS_ARCHIVE_NAME"
fi

if ((${#_SSH_TIME_PREFIX[@]})); then
  echo "[v2-backend] remote install (venv, pip, psql client, migrations, systemd, optional nginx) max ${ZENHEART_V2_REMOTE_SSH_MAX_S}s"
else
  if [[ "$(uname -s)" == "Darwin" ]]; then
    echo "[v2-backend] remote install (venv, pip, psql client, migrations, systemd, optional nginx) (warn: no 'timeout' on PATH; whole SSH is uncapped; install Homebrew coreutils for gtimeout)" >&2
  else
    echo "[v2-backend] remote install (venv, pip, psql client, migrations, systemd, optional nginx) (warn: no 'timeout' on PATH; whole SSH is uncapped)" >&2
  fi
fi
# Build argv without leading empty array (bash 3.2 + set -u errors on "${empty[@]}").
_CMD=()
if ((${#_SSH_TIME_PREFIX[@]} > 0)); then
  _CMD+=("${_SSH_TIME_PREFIX[@]}")
fi
_CMD+=(
  "${SSH_CMD[@]}"
  "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST"
  env REMOTE_DIR="$REMOTE_DIR" SERVICE_NAME="$SERVICE_NAME" SKIP_NGINX="$ZENHEART_V2_SKIP_NGINX" \
    ZENHEART_MEDIA_ROOT="${ZENHEART_MEDIA_ROOT:-}" \
    ZENHEART_V2_NO_ROTATE_ADMIN_KEY="${ZENHEART_V2_NO_ROTATE_ADMIN_KEY:-0}" \
    ZENHEART_V2_BOOTSTRAP_ENV="${ZENHEART_V2_BOOTSTRAP_ENV:-0}" \
    ZENHEART_V2_STANDARDIZE_CHECKIN_SYSTEM="${ZENHEART_V2_STANDARDIZE_CHECKIN_SYSTEM:-0}" \
    BACKEND_ARCHIVE_NAME="$BACKEND_ARCHIVE_NAME" \
    SYNCED_DOCS="$SYNCED_DOCS" DOCS_ARCHIVE_NAME="$DOCS_ARCHIVE_NAME" \
    SYNCED_SKILLS="$SYNCED_SKILLS" SKILLS_ARCHIVE_NAME="$SKILLS_ARCHIVE_NAME" \
    bash -s
)
set +e
"${_CMD[@]}" <<'REMOTE_SCRIPT'
set -euo pipefail

require_opt_zenheart_path() {
  local p="$1" name="$2"
  [[ "$p" == /* ]] || { echo "error: $name must be absolute (got: $p)" >&2; exit 1; }
  [[ "$p" == /opt/zenheart/* ]] || { echo "error: $name must be under /opt/zenheart/ (got: $p)" >&2; exit 1; }
  [[ "$p" != *..* ]] || { echo "error: $name must not contain .. (got: $p)" >&2; exit 1; }
}

TAR_WARN_FLAGS=()
if tar --warning=no-unknown-keyword --version >/dev/null 2>&1; then
  TAR_WARN_FLAGS+=(--warning=no-unknown-keyword)
fi

sudo mkdir -p "$REMOTE_DIR" /etc/nginx/snippets
if [[ -z "${BACKEND_ARCHIVE_NAME:-}" || ! -f "$HOME/$BACKEND_ARCHIVE_NAME" ]]; then
  echo "error: missing backend archive $HOME/$BACKEND_ARCHIVE_NAME" >&2
  exit 1
fi
echo "[v2-backend] install backend from archive → $REMOTE_DIR/"
sudo mkdir -p "$REMOTE_DIR"
BACKEND_STAGE="$(mktemp -d)"
tar "${TAR_WARN_FLAGS[@]}" -xzf "$HOME/$BACKEND_ARCHIVE_NAME" -C "$BACKEND_STAGE"
sudo rsync -a --delete \
  --exclude='.env' \
  --exclude='.venv/' \
  "$BACKEND_STAGE/" "$REMOTE_DIR/"
sudo chown -R "$(id -un):$(id -gn)" "$REMOTE_DIR"
rm -rf "$BACKEND_STAGE"
rm -f "$HOME/$BACKEND_ARCHIVE_NAME"

# Create media directory for agent-uploaded images.
MEDIA_DIR="${ZENHEART_MEDIA_ROOT:-/opt/zenheart/media}"
require_opt_zenheart_path "$MEDIA_DIR" "MEDIA_DIR (ZENHEART_MEDIA_ROOT or default)"
sudo mkdir -p "$MEDIA_DIR/images"
sudo chown -R "$(id -un):$(id -gn)" "$MEDIA_DIR"

if [[ "${SYNCED_DOCS:-0}" == "1" && -n "${DOCS_ARCHIVE_NAME:-}" && -f "$HOME/$DOCS_ARCHIVE_NAME" ]]; then
  DOCS_REMOTE="$(dirname "$REMOTE_DIR")/docs"
  echo "[v2-backend] install markdown guides → $DOCS_REMOTE/"
  sudo rm -rf "$DOCS_REMOTE"
  sudo mkdir -p "$DOCS_REMOTE"
  sudo tar "${TAR_WARN_FLAGS[@]}" -xzf "$HOME/$DOCS_ARCHIVE_NAME" -C "$DOCS_REMOTE"
  sudo chown -R "$(id -un):$(id -gn)" "$DOCS_REMOTE"
  rm -f "$HOME/$DOCS_ARCHIVE_NAME"
fi

if [[ "${SYNCED_SKILLS:-0}" == "1" && -n "${SKILLS_ARCHIVE_NAME:-}" && -f "$HOME/$SKILLS_ARCHIVE_NAME" ]]; then
  SKILLS_REMOTE="$(dirname "$REMOTE_DIR")/skills"
  echo "[v2-backend] install skills → $SKILLS_REMOTE/"
  sudo rm -rf "$SKILLS_REMOTE"
  sudo mkdir -p "$SKILLS_REMOTE"
  sudo tar "${TAR_WARN_FLAGS[@]}" -xzf "$HOME/$SKILLS_ARCHIVE_NAME" -C "$SKILLS_REMOTE"
  sudo chown -R "$(id -un):$(id -gn)" "$SKILLS_REMOTE"
  rm -f "$HOME/$SKILLS_ARCHIVE_NAME"
fi

if [[ ! -f "$REMOTE_DIR/.env" ]]; then
  if [[ -f "$REMOTE_DIR/.env.example" && "${ZENHEART_V2_BOOTSTRAP_ENV:-0}" == "1" ]]; then
    cp "$REMOTE_DIR/.env.example" "$REMOTE_DIR/.env"
    chmod 600 "$REMOTE_DIR/.env"
    echo "Created $REMOTE_DIR/.env from .env.example (ZENHEART_V2_BOOTSTRAP_ENV=1)."
    echo "SSH to the host, edit DATABASE_URL, ADMIN_API_KEY, SMTP, SOCIAL_OBSERVE_SHARED_TOKEN (HTTPS sites), optional PUBLIC_WALL_* (message wall; see .env.example), then run deploy-backend.sh again."
    exit 2
  fi
  if [[ -f "$REMOTE_DIR/.env.example" ]]; then
    echo "error: missing $REMOTE_DIR/.env. Create it on the host, or re-run with ZENHEART_V2_BOOTSTRAP_ENV=1 once to copy from .env.example (then fill secrets)." >&2
    exit 1
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
_pip_t=900
if command -v timeout &>/dev/null; then
  timeout "$_pip_t" "$REMOTE_DIR/.venv/bin/pip" install --upgrade pip -q \
    || { echo "error: pip upgrade exceeded ${_pip_t}s or failed" >&2; exit 1; }
  timeout "$_pip_t" "$REMOTE_DIR/.venv/bin/pip" install -r "$REMOTE_DIR/requirements.txt" -q \
    || { echo "error: pip install -r requirements exceeded ${_pip_t}s or failed" >&2; exit 1; }
else
  "$REMOTE_DIR/.venv/bin/pip" install --upgrade pip -q
  "$REMOTE_DIR/.venv/bin/pip" install -r "$REMOTE_DIR/requirements.txt" -q
fi

# Rotate ADMIN_API_KEY before migrations/restart so the running process loads the new key.
if [[ "${ZENHEART_V2_NO_ROTATE_ADMIN_KEY:-0}" != "1" ]]; then
  echo "[v2-backend] rotate ADMIN_API_KEY in $REMOTE_DIR/.env (skip: ZENHEART_V2_NO_ROTATE_ADMIN_KEY=1)"
  _admin_key="$("$REMOTE_DIR/.venv/bin/python" -c "import secrets; print(secrets.token_urlsafe(48))")"
  "$REMOTE_DIR/.venv/bin/python" "$REMOTE_DIR/scripts/replace_admin_api_key_env_line.py" "$REMOTE_DIR/.env" "$_admin_key"
  chmod 600 "$REMOTE_DIR/.env"
  echo ""
  echo "=============================================================================="
  echo "[v2-backend] NEW ADMIN_API_KEY (written to $REMOTE_DIR/.env) — header X-Admin-Key"
  echo "=============================================================================="
  printf '%s\n' "$_admin_key"
  echo "=============================================================================="
  echo ""
else
  echo "[v2-backend] skip ADMIN_API_KEY rotation (ZENHEART_V2_NO_ROTATE_ADMIN_KEY=1)"
fi

# Optional: install psql for ad-hoc SQL on the host (migrations use Python + asyncpg).
if ! command -v psql &>/dev/null; then
  echo "[v2-backend] installing PostgreSQL client (psql)"
  if command -v dnf &>/dev/null; then
    # Prefer client major matching typical PG 16+ (e.g. Docker postgres:16) so pg_dump is not too old.
    sudo dnf install -y postgresql16 &>/dev/null \
      || sudo dnf install -y postgresql15 &>/dev/null \
      || sudo dnf install -y postgresql &>/dev/null \
      || true
  elif command -v yum &>/dev/null; then
    sudo yum install -y postgresql16 &>/dev/null \
      || sudo yum install -y postgresql15 &>/dev/null \
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

# Apply schema migrations before restart (PostgreSQL via asyncpg). Do not source .env (arbitrary shell).
if [[ -d "$REMOTE_DIR/scripts/migrations" ]]; then
  _db_url="$("$REMOTE_DIR/.venv/bin/python" - "$REMOTE_DIR/.env" <<'PY'
import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
if not path.is_file():
    print("error: .env is not a file", file=sys.stderr)
    sys.exit(1)
text = path.read_text(encoding="utf-8", errors="strict")
for raw in text.splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    m = re.match(r"^DATABASE_URL\s*=\s*(.*)$", line)
    if not m:
        continue
    val = m.group(1).strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        val = val[1:-1]
    if val:
        sys.stdout.write(val)
        sys.exit(0)
print("error: DATABASE_URL not found or empty in .env", file=sys.stderr)
sys.exit(1)
PY
)"
  if [[ -z "$_db_url" ]]; then
    echo "error: could not read DATABASE_URL from $REMOTE_DIR/.env" >&2
    exit 1
  fi
  export DATABASE_URL="$_db_url"
  echo "[v2-backend] migrations → $REMOTE_DIR/scripts/migrations/"
  # -u: unbuffered stdout. timeout: avoid rare hang in asyncio event-loop shutdown (asyncpg/SSL) or slow DB.
  _mig_t=240
  if command -v timeout &>/dev/null; then
    timeout "$_mig_t" "$REMOTE_DIR/.venv/bin/python" -u "$REMOTE_DIR/scripts/run_migrations.py" "$REMOTE_DIR/scripts/migrations" \
      || { echo "error: migrations failed or exceeded ${_mig_t}s (timeout), see above" >&2; exit 1; }
  else
    "$REMOTE_DIR/.venv/bin/python" -u "$REMOTE_DIR/scripts/run_migrations.py" "$REMOTE_DIR/scripts/migrations" \
      || { echo "error: migrations failed" >&2; exit 1; }
  fi
  echo "[v2-backend] migrations done; updating systemd ($SERVICE_NAME)"
fi

if [[ "${ZENHEART_V2_STANDARDIZE_CHECKIN_SYSTEM:-0}" == "1" ]]; then
  echo "[v2-backend] standardize check-in room (--system-creator)"
  cd "$REMOTE_DIR"
  "$REMOTE_DIR/.venv/bin/python" "$REMOTE_DIR/scripts/standardize_checkin_room.py" --system-creator
fi

sudo cp "$REMOTE_DIR/deploy/zenheart-v2-backend.service" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
# restart can block if the unit never reaches active; cap wait so deploy does not hang forever.
if command -v timeout &>/dev/null; then
  echo "[v2-backend] systemctl restart (max 120s)..."
  timeout 120 sudo systemctl restart "$SERVICE_NAME" || { echo "error: systemctl restart timed out or failed" >&2; exit 1; }
else
  echo "[v2-backend] systemctl restart: timeout command not in PATH; if this hangs, install coreutils" >&2
  sudo systemctl restart "$SERVICE_NAME"
fi
sleep 2
if ! sudo systemctl is-active --quiet "$SERVICE_NAME"; then
  echo "error: $SERVICE_NAME failed to start" >&2
  sudo journalctl -u "$SERVICE_NAME" -n 40 --no-pager >&2 || true
  exit 1
fi

if curl -sf --connect-timeout 5 --max-time 20 "http://127.0.0.1:8090/health" | grep -q ok; then
  echo "ok: GET http://127.0.0.1:8090/health"
else
  echo "warn: health check failed on 8090" >&2
fi

if [[ "$SKIP_NGINX" != "1" ]] && command -v nginx &>/dev/null; then
  sudo cp "$REMOTE_DIR/deploy/nginx-v2-backend-upstream.conf" /etc/nginx/conf.d/zenheart-v2-backend-upstream.conf
  sudo cp "$REMOTE_DIR/deploy/nginx-v2-backend-location.conf" /etc/nginx/snippets/zenheart-v2-backend-location.conf
  echo "Installed nginx fragments. Inside your HTTPS server block for zenheart.net add (once):"
  echo "  include /etc/nginx/snippets/zenheart-v2-backend-location.conf;"
  if command -v timeout &>/dev/null; then
    _ngx_t=60
    if timeout "$_ngx_t" sudo nginx -t; then
      sudo systemctl reload nginx
      echo "ok: nginx reloaded"
    else
      echo "warn: nginx -t failed or timed out after ${_ngx_t}s — fix config then reload nginx" >&2
    fi
  elif sudo nginx -t; then
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
_SSH_EC=$?
set -e
if [[ $_SSH_EC -eq 124 ]]; then
  die "remote install exceeded ${ZENHEART_V2_REMOTE_SSH_MAX_S}s (timeout). Fix the hang, or raise ZENHEART_V2_REMOTE_SSH_MAX_S."
fi
[[ $_SSH_EC -eq 0 ]] || exit "$_SSH_EC"

if [[ "${ZENHEART_V2_SAVE_LAST_ADMIN_KEY:-0}" == "1" ]]; then
  _lah="$V2_ROOT/.last-admin-api-key"
  if "${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
    "grep '^ADMIN_API_KEY=' ${REMOTE_DIR}/.env | sed -n 's/^ADMIN_API_KEY=//p'" >"$_lah" 2>/dev/null; then
    chmod 600 "$_lah" 2>/dev/null || true
    echo "[v2-backend] copied remote ADMIN_API_KEY value → $_lah (chmod 600; gitignored)"
  else
    echo "[v2-backend] warn: could not fetch ADMIN_API_KEY to $_lah" >&2
  fi
fi

echo "[v2-backend] deploy-backend.sh done"
echo "[v2-backend] admin CLI: $REMOTE_DIR/scripts/admin_agent_cli.py"
echo "[v2-backend] agent WS protocol: v2/docs/protocol/A01_agent-connectivity-spec.md"
