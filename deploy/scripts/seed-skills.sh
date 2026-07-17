#!/usr/bin/env bash
# Upload the built-in skills from deploy/skills/ to the running API.
# Run after deploy: ./deploy/scripts/seed-skills.sh [api-base-url]
set -euo pipefail

API_BASE="${1:-http://localhost:8000}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKILLS_DIR="${REPO_ROOT}/deploy/skills"

command -v curl >/dev/null || { echo "ERROR: curl not found" >&2; exit 1; }
command -v zip  >/dev/null || { echo "ERROR: zip not found" >&2; exit 1; }

for skill_dir in "${SKILLS_DIR}"/*/; do
  slot="$(basename "${skill_dir}")"
  tmp_zip="$(mktemp -t "skill-${slot}-XXXX").zip"
  (cd "${skill_dir}" && zip -qr "${tmp_zip}" .)
  echo "Uploading skill '${slot}' → ${API_BASE}/simagix/skills"
  curl -sf -X POST "${API_BASE}/simagix/skills" \
    -F "slot_name=${slot}" \
    -F "archive=@${tmp_zip};type=application/zip" \
    | head -c 300
  echo ""
  rm -f "${tmp_zip}"
done

echo "Done. Verify: curl ${API_BASE}/simagix/skills"
