#!/usr/bin/env bash
# Sync FAQ-facing trees (markdown docs, skills) to production without restarting the backend.
# Matches deploy-backend.sh remote layout: "$(dirname ZENHEART_V2_REMOTE_DIR)/{docs,skills}".
# Optional: mirror v2/packages to sibling packages/ (--with-packages); not read by GET /v2/faq/* today.
#
# Env / prereqs: same as deploy-backend.sh (v2/.deploy-env, ZENHEART_EC2_HOST, SSH host key pinning).
#
# Usage:
#   ./v2/deploy-faq-files.sh              # rsync docs + skills (skip missing dirs)
#   ./v2/deploy-faq-files.sh --dry-run    # show what would change
#   ./v2/deploy-faq-files.sh --check-only  # exit 1 if remote differs from local (no writes)
#   ./v2/deploy-faq-files.sh --with-packages
#
set -euo pipefail

V2_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$V2_ROOT/.." && pwd)"

die() { echo "error: $*" >&2; exit 1; }

require_opt_zenheart_path() {
  local p="$1" name="$2"
  [[ "$p" == /* ]] || die "$name must be absolute (got: $p)"
  [[ "$p" == /opt/zenheart/* ]] || die "$name must be under /opt/zenheart/ (got: $p)"
  [[ "$p" != *..* ]] || die "$name must not contain .. (got: $p)"
}

if [[ -f "$V2_ROOT/.deploy-env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$V2_ROOT/.deploy-env"
  set +a
fi

if [[ -n "${ZENHEART_SSH_KNOWN_HOSTS:-}" ]] && [[ ! -f "$ZENHEART_SSH_KNOWN_HOSTS" ]]; then
  if [[ -f "$V2_ROOT/.ssh/known_hosts" ]]; then
    echo "[v2-faq-files] ZENHEART_SSH_KNOWN_HOSTS file missing (${ZENHEART_SSH_KNOWN_HOSTS-}) — using $V2_ROOT/.ssh/known_hosts" >&2
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
  die "SSH host key: set ZENHEART_SSH_KNOWN_HOSTS or ZENHEART_SSH_ACCEPT_NEW=1 (see deploy-backend.sh)"
fi

ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/aws/zenheart-ec2.pem}"
ZENHEART_EC2_HOST="${ZENHEART_EC2_HOST:-}"
[[ -n "$ZENHEART_EC2_HOST" ]] || die "ZENHEART_EC2_HOST is not set (see v2/.deploy-env.example)"
ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
REMOTE_DIR="${ZENHEART_V2_REMOTE_DIR:-/opt/zenheart/services/v2_backend}"

require_opt_zenheart_path "$REMOTE_DIR" "ZENHEART_V2_REMOTE_DIR"

[[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY"
chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true

SSH_CMD=(
  ssh -i "$ZENHEART_EC2_KEY"
  "${SSH_HOSTKEY_ARGS[@]}"
  -o BatchMode=yes
  -o ConnectTimeout=15
  -o ServerAliveInterval=5
  -o ServerAliveCountMax=3
)

REMOTE_PARENT="$(dirname "$REMOTE_DIR")"
require_opt_zenheart_path "$REMOTE_PARENT" "REMOTE_PARENT (dirname of ZENHEART_V2_REMOTE_DIR)"

RSYNC_RSH=$(printf '%q ' "${SSH_CMD[@]}")
export RSYNC_RSH

DRY_RUN=0
CHECK_ONLY=0
WITH_PACKAGES=0
USE_CHECKSUM=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--dry-run)
      DRY_RUN=1
      ;;
    --check-only)
      CHECK_ONLY=1
      ;;
    --with-packages)
      WITH_PACKAGES=1
      ;;
    --checksum)
      USE_CHECKSUM=1
      ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *)
      die "unknown argument: $1 (try --help)"
      ;;
  esac
  shift
done

if [[ "$CHECK_ONLY" == "1" && "$DRY_RUN" == "1" ]]; then
  die "use either --check-only or --dry-run, not both"
fi

remote_ensure_tree() {
  local sub="$1"
  "${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
    "sudo mkdir -p \"$REMOTE_PARENT/$sub\" && sudo chown \"\$(id -un):\$(id -gn)\" \"$REMOTE_PARENT/$sub\""
}

tree_has_drift() {
  local name="$1"
  local src="$V2_ROOT/$name"
  local dst="$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_PARENT/$name/"
  local tmp
  tmp="$(mktemp)"
  if ! "${SSH_CMD[@]}" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" "test -d \"$REMOTE_PARENT/$name\""; then
    echo "[deploy-faq-files] remote missing: $REMOTE_PARENT/$name (run sync once without --check-only)" >&2
    rm -f "$tmp"
    return 1
  fi
  local rsync_flags=( -azcn --delete )
  if [[ "$USE_CHECKSUM" == "1" ]]; then
    rsync_flags+=( --checksum )
  fi
  set +e
  rsync "${rsync_flags[@]}" -e "$RSYNC_RSH" "$src/" "$dst" >"$tmp" 2>"${tmp}.err"
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    cat "${tmp}.err" >&2 || true
    rm -f "$tmp" "${tmp}.err"
    die "rsync check failed for $name (rc=$rc)"
  fi
  rm -f "${tmp}.err"
  if [[ -s "$tmp" ]]; then
    echo ""
    echo "=============================================================================="
    echo "[deploy-faq-files] drift: local $name vs $REMOTE_PARENT/$name/"
    echo "=============================================================================="
    cat "$tmp"
    rm -f "$tmp"
    return 1
  fi
  rm -f "$tmp"
  return 0
}

sync_tree() {
  local name="$1"
  local src="$V2_ROOT/$name"
  [[ -d "$src" ]] || { echo "[deploy-faq-files] skip (missing dir): $src"; return 0; }

  if [[ "$CHECK_ONLY" == "1" ]]; then
    tree_has_drift "$name" || return 1
    echo "[deploy-faq-files] ok (in sync): $name"
    return 0
  fi

  remote_ensure_tree "$name"

  local rsync_flags=( -az --delete --omit-dir-times )
  if [[ "$DRY_RUN" == "1" ]]; then
    rsync_flags+=( -n )
  fi
  if [[ "$USE_CHECKSUM" == "1" ]]; then
    rsync_flags+=( --checksum )
  fi

  echo "[deploy-faq-files] rsync → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_PARENT/$name/"
  rsync "${rsync_flags[@]}" -e "$RSYNC_RSH" "$src/" "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:$REMOTE_PARENT/$name/"
}

echo "=============================================================================="
echo "[deploy-faq-files] ZenHeart v2 — sync trees: docs, skills (no backend restart)"
echo "[deploy-faq-files] remote parent: $REMOTE_PARENT"
echo "=============================================================================="

ANY_DRIFT=0
for tree in docs skills; do
  [[ -d "$V2_ROOT/$tree" ]] || continue
  if [[ "$CHECK_ONLY" == "1" ]]; then
    sync_tree "$tree" || ANY_DRIFT=1
  else
    sync_tree "$tree"
  fi
done

if [[ "$WITH_PACKAGES" == "1" ]]; then
  if [[ ! -d "$V2_ROOT/packages" ]]; then
    echo "[deploy-faq-files] warn: --with-packages but $V2_ROOT/packages missing" >&2
  elif [[ "$CHECK_ONLY" == "1" ]]; then
    sync_tree packages || ANY_DRIFT=1
  else
    sync_tree packages
  fi
fi

if [[ "$CHECK_ONLY" == "1" && "$ANY_DRIFT" == "1" ]]; then
  echo "" >&2
  echo "[deploy-faq-files] check-only: remote differs from local (exit 1)" >&2
  exit 1
fi

if [[ "$CHECK_ONLY" == "1" ]]; then
  echo "[deploy-faq-files] check-only: all present trees match local"
fi

echo "[deploy-faq-files] done"
