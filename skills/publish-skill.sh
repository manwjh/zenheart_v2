#!/usr/bin/env bash
# One-shot publish bundle directories to ClawHub and sync to ZenHeart site.
#
# Usage:
#   ./publish-skill.sh zen-agent
#   ./publish-skill.sh zen-agent zen-admin
#   ./publish-skill.sh --all          # every sibling dir containing SKILL.md + skill.json
#
# Env:
#   CHANGELOG                  — passed to clawhub publish (default: see script)
#   ZENHEART_EC2_HOST         — required for ZenHeart sync
#   ZENHEART_EC2_USER         — SSH user (required)
#   ZENHEART_EC2_KEY          — SSH private key path (required)
#   ZENHEART_SSH_KNOWN_HOSTS  — known_hosts file (required)
#   ZENHEART_V2_REMOTE_DIR    — remote backend dir under /opt/zenheart/ (required)
#   ZENHEART_SKILLS_URL_BASE  — public API base for post-sync checks (required)
#
# Requires: jq, clawhub (npm i -g clawhub), clawhub login, ssh, scp, tar, curl
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CHANGELOG="${CHANGELOG:-Publish from ZenHeart v2 skills bundle.}"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
TMP_DIR=""
PUBLISHED_SLUGS=()

die() { echo "error: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

require_env() {
  local key="$1"
  [[ -n "${!key:-}" ]] || die "missing required env: ${key}"
}

require_opt_zenheart_path() {
  local p="$1" name="$2"
  [[ "$p" == /* ]] || die "$name must be absolute (got: $p)"
  [[ "$p" == /opt/zenheart/* ]] || die "$name must be under /opt/zenheart/ (got: $p)"
  [[ "$p" != *..* ]] || die "$name must not contain .. (got: $p)"
}

cleanup() {
  if [[ -n "$TMP_DIR" ]]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

clawhub_publish() {
  local slug="$1"
  local dir="${ROOT}/${slug}"
  local meta="${dir}/skill.json"
  [[ -f "$meta" ]] || die "missing $meta (needed for ClawHub metadata)"
  local name version
  name="$(jq -r '.name // empty' "$meta")"
  version="$(jq -r '.version // empty' "$meta")"
  [[ -n "$name" ]] || die "skill.json missing .name"
  [[ -n "$version" ]] || die "skill.json missing .version"
  need_cmd clawhub
  local out_file
  out_file="$(mktemp)"
  if clawhub publish "$dir" \
    --slug "$slug" \
    --name "$name" \
    --version "$version" \
    --changelog "$CHANGELOG" \
    --tags latest \
    --no-input >"$out_file" 2>&1; then
    cat "$out_file"
    rm -f "$out_file"
    echo "[clawhub] published ${slug}@${version}"
    return
  fi
  if grep -q "Version already exists" "$out_file"; then
    cat "$out_file"
    rm -f "$out_file"
    echo "[clawhub] exists ${slug}@${version}; continue"
    return
  fi
  cat "$out_file" >&2
  rm -f "$out_file"
  die "clawhub publish failed for ${slug}@${version}"
}

publish_one() {
  local slug="$1"
  [[ "$slug" != *"/"* ]] || die "invalid slug: $slug"
  clawhub_publish "$slug"
  PUBLISHED_SLUGS+=("$slug")
}

load_deploy_env() {
  local deploy_env="$REPO_ROOT/.deploy-env"
  if [[ -f "$deploy_env" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$deploy_env"
    set +a
  fi
  ZENHEART_EC2_KEY="${ZENHEART_EC2_KEY:-$REPO_ROOT/../aws/zenheart-ec2.pem}"
  ZENHEART_EC2_USER="${ZENHEART_EC2_USER:-ec2-user}"
  ZENHEART_V2_REMOTE_DIR="${ZENHEART_V2_REMOTE_DIR:-/opt/zenheart/services/v2_backend}"
  ZENHEART_SKILLS_URL_BASE="${ZENHEART_SKILLS_URL_BASE:-https://zenheart.net/v2/faq/skills}"
}

zenheart_sync_skills() {
  need_cmd ssh
  need_cmd scp
  need_cmd tar
  need_cmd curl

  require_env ZENHEART_EC2_HOST
  require_env ZENHEART_EC2_USER
  require_env ZENHEART_EC2_KEY
  require_env ZENHEART_SSH_KNOWN_HOSTS
  require_env ZENHEART_V2_REMOTE_DIR
  require_env ZENHEART_SKILLS_URL_BASE

  [[ -f "$ZENHEART_EC2_KEY" ]] || die "missing SSH key: $ZENHEART_EC2_KEY"
  [[ -f "$ZENHEART_SSH_KNOWN_HOSTS" ]] || die "missing known_hosts file: $ZENHEART_SSH_KNOWN_HOSTS"
  require_opt_zenheart_path "$ZENHEART_V2_REMOTE_DIR" "ZENHEART_V2_REMOTE_DIR"

  local skills_remote
  local archive_local
  local archive_name

  skills_remote="$(dirname "$ZENHEART_V2_REMOTE_DIR")/skills"
  require_opt_zenheart_path "$skills_remote" "skills_remote"

  TMP_DIR="$(mktemp -d)"
  archive_local="$TMP_DIR/skills.tar.gz"
  archive_name="zenheart-v2-skills.tar.gz"

  echo "[zenheart] pack skills → $archive_local"
  COPYFILE_DISABLE=1 COPY_EXTENDED_ATTRIBUTES_DISABLE=1 tar -C "$ROOT" -czf "$archive_local" .

  echo "[zenheart] upload skills archive → $ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$archive_name"
  chmod 400 "$ZENHEART_EC2_KEY" 2>/dev/null || true
  scp \
    -i "$ZENHEART_EC2_KEY" \
    -o StrictHostKeyChecking=yes \
    -o "UserKnownHostsFile=$ZENHEART_SSH_KNOWN_HOSTS" \
    -o GlobalKnownHostsFile=/dev/null \
    "$archive_local" \
    "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST:~/$archive_name"

  echo "[zenheart] install skills → $skills_remote"
  ssh \
    -i "$ZENHEART_EC2_KEY" \
    -o StrictHostKeyChecking=yes \
    -o "UserKnownHostsFile=$ZENHEART_SSH_KNOWN_HOSTS" \
    -o GlobalKnownHostsFile=/dev/null \
    "$ZENHEART_EC2_USER@$ZENHEART_EC2_HOST" \
    env SKILLS_ARCHIVE_NAME="$archive_name" SKILLS_REMOTE="$skills_remote" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
if [[ -z "${SKILLS_ARCHIVE_NAME:-}" || ! -f "$HOME/$SKILLS_ARCHIVE_NAME" ]]; then
  echo "error: missing skills archive $HOME/$SKILLS_ARCHIVE_NAME" >&2
  exit 1
fi
if [[ -z "${SKILLS_REMOTE:-}" ]]; then
  echo "error: SKILLS_REMOTE is empty" >&2
  exit 1
fi
sudo rm -rf "$SKILLS_REMOTE"
sudo mkdir -p "$SKILLS_REMOTE"
sudo tar -xzf "$HOME/$SKILLS_ARCHIVE_NAME" -C "$SKILLS_REMOTE"
sudo chown -R "$(id -un):$(id -gn)" "$SKILLS_REMOTE"
rm -f "$HOME/$SKILLS_ARCHIVE_NAME"
REMOTE_SCRIPT
}

zenheart_verify_slugs() {
  local slug url
  for slug in "${PUBLISHED_SLUGS[@]}"; do
    url="${ZENHEART_SKILLS_URL_BASE%/}/${slug}"
    echo "[zenheart] verify $url"
    curl -fsS "$url" >/dev/null || die "zenheart verify failed: $url"
  done
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,50p' "$0"
  exit 0
fi

[[ $# -ge 1 ]] || die "usage: $0 <slug> [<slug>...] | $0 --all"

if [[ "${1:-}" == "--all" ]]; then
  shopt -s nullglob
  for dir in "${ROOT}"/*/; do
    base="$(basename "${dir}")"
    [[ -f "${dir}SKILL.md" && -f "${dir}skill.json" ]] || continue
    publish_one "$base"
  done
  load_deploy_env
  zenheart_sync_skills
  zenheart_verify_slugs
  echo "[zenheart] sync complete"
  exit 0
fi

for slug in "$@"; do
  publish_one "$slug"
done

load_deploy_env
zenheart_sync_skills
zenheart_verify_slugs
echo "[zenheart] sync complete"
