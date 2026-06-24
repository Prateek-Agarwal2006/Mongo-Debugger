#!/usr/bin/env bash
# Worker-facing Hatchet job: parse uploaded mongod logs into phase1/hatchet/hatchet.db (no HTML).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"

RUN_ID="${HATCHET_RUN_ID:-${1:-}}"
LOG_REL="${2:-}"
HATCHET_IMAGE="${HATCHET_IMAGE:-mongo-debugger/hatchet:local}"

if [[ -z "${RUN_ID}" ]]; then
  echo "Usage: run-hatchet-job.sh <run_id> [relative-log-dir]" >&2
  exit 1
fi

if [[ -z "${LOG_REL}" ]]; then
  LOG_REL="simagix-workspace/uploads/${RUN_ID}/inputs/mongodb-logs"
fi

LOG_DIR="${PROJECT_ROOT}/${LOG_REL}"
OUT_DIR="${SIMAGIX_DIR}/uploads/${RUN_ID}/phase1/hatchet"
DB_PATH="${OUT_DIR}/hatchet.db"

mkdir -p "${OUT_DIR}"

if [[ ! -d "${LOG_DIR}" ]]; then
  echo "Log directory not found: ${LOG_DIR}" >&2
  exit 1
fi

LOG_FILES=()
while IFS= read -r file; do
  LOG_FILES+=("${file}")
done < <(find "${LOG_DIR}" -maxdepth 1 -type f ! -name '.*' -print | LC_ALL=C sort)
if [[ "${#LOG_FILES[@]}" -eq 0 ]]; then
  echo "No log files in ${LOG_DIR}" >&2
  exit 1
fi

DOCKER_ARGS=()
for file in "${LOG_FILES[@]}"; do
  rel="${file#${PROJECT_ROOT}/}"
  DOCKER_ARGS+=("${rel}")
done

DB_REL="${DB_PATH#${PROJECT_ROOT}/}"

echo "=== Hatchet job ==="
echo "Run ID: ${RUN_ID}"
echo "Logs: ${#DOCKER_ARGS[@]} file(s) under ${LOG_REL}"
echo "Output DB: ${DB_REL}"
echo "Image: ${HATCHET_IMAGE}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  "${HATCHET_IMAGE}" \
  /hatchet -merge -url "/workspace/${DB_REL}" "${DOCKER_ARGS[@]}"

if [[ ! -f "${DB_PATH}" ]]; then
  echo "Hatchet did not produce ${DB_PATH}" >&2
  exit 1
fi

echo "Hatchet DB ready: ${DB_PATH}"
