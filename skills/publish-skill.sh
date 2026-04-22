#!/usr/bin/env bash
# One-shot publish bundle directories to ClawHub.
#
# Usage:
#   ./publish-skill.sh zenheart-user-agent
#   ./publish-skill.sh zenheart-user-agent zenheart-admin-agent
#   ./publish-skill.sh --all          # every sibling dir containing SKILL.md + skill.json
#
# Env:
#   CHANGELOG  — passed to clawhub publish (default: see script)
#
# Requires: jq, clawhub (npm i -g clawhub), clawhub login
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CHANGELOG="${CHANGELOG:-Publish from ZenHeart v2 skills bundle.}"

die() { echo "error: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

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
  clawhub publish "$dir" \
    --slug "$slug" \
    --name "$name" \
    --version "$version" \
    --changelog "$CHANGELOG" \
    --tags latest \
    --no-input
  echo "[clawhub] published ${slug}@${version}"
}

publish_one() {
  local slug="$1"
  [[ "$slug" != *"/"* ]] || die "invalid slug: $slug"
  clawhub_publish "$slug"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '1,35p' "$0"
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
  exit 0
fi

for slug in "$@"; do
  publish_one "$slug"
done
