#!/usr/bin/env bash
set -euo pipefail

# Package each skill folder (must contain SKILL.md) into dist/<slug>.zip
# Archive root is the skill directory contents (SKILL.md at zip root).

ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="${ROOT}/dist"
mkdir -p "${OUT}"

shopt -s nullglob
for dir in "${ROOT}"/*/; do
  base="$(basename "${dir}")"
  [[ "${base}" == "dist" ]] && continue
  [[ -f "${dir}SKILL.md" ]] || continue
  zip_path="${OUT}/${base}.zip"
  rm -f "${zip_path}"
  (cd "${dir}" && zip -qr "${zip_path}" . -x "*.DS_Store" -x ".DS_Store")
  echo "wrote ${zip_path}"
done
