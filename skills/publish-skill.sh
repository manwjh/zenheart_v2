#!/usr/bin/env bash
# One-shot: build <slug>.zip next to v2/skills/ and publish the same folder to ClawHub.
# ZenHeart serves bundle skills from skills/<slug>/SKILL.md + optional skills/<slug>.zip.
#
# Usage:
#   ./publish-skill.sh zenheart-user-agent
#   ./publish-skill.sh zenheart-user-agent zenheart-admin-agent
#   ./publish-skill.sh --all          # every sibling dir containing SKILL.md + skill.json
#
# Env:
#   CHANGELOG  — passed to clawhub publish (default: see script)
#   SKIP_CLAWHUB=1 — only build zip
#   SKIP_ZIP=1     — only clawhub publish
#
# Requires: zip, jq, clawhub (npm i -g clawhub), clawhub login
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CHANGELOG="${CHANGELOG:-Publish from ZenHeart v2 skills bundle.}"

die() { echo "error: $*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing command: $1"; }

zip_bundle() {
  local slug="$1"
  local dir="${ROOT}/${slug}"
  [[ -d "$dir" ]] || die "not a directory: $dir"
  [[ -f "${dir}/SKILL.md" ]] || die "missing ${dir}/SKILL.md"
  local out="${ROOT}/${slug}.zip"
  rm -f "$out"
  (cd "$dir" && zip -qr "$out" . -x "*.DS_Store" -x ".DS_Store")
  echo "[zip] wrote $out"
}

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
  if [[ "${SKIP_ZIP:-}" != "1" ]]; then
    need_cmd zip
    zip_bundle "$slug"
  fi
  if [[ "${SKIP_CLAWHUB:-}" != "1" ]]; then
    clawhub_publish "$slug"
  fi
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
