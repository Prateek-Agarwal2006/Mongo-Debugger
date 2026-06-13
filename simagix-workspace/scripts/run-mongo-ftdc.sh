#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"
INPUT_PATH="${1:-simagix-workspace/data/diagnostic.data}"
LATEST="${MONGO_FTDC_LATEST:-0}"
RUN_ID="${MONGO_FTDC_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
REPORT_DIR="${SIMAGIX_DIR}/reports/mongo-ftdc/${RUN_ID}"

mkdir -p "${REPORT_DIR}"

echo "Running mongo-ftdc against: ${INPUT_PATH}"
echo "Reports will be copied to: ${REPORT_DIR}"
echo "Run ID: ${RUN_ID}"
echo "Latest files setting: ${LATEST} (0 means all files)"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  simagix/ftdc \
  /mftdc -latest "${LATEST}" "${INPUT_PATH}" | tee "${REPORT_DIR}/mftdc-console.txt"

if [ -d "${PROJECT_ROOT}/html" ]; then
  cp -R "${PROJECT_ROOT}/html/." "${REPORT_DIR}/"
  echo "Copied generated HTML reports into ${REPORT_DIR}"
fi

printf '%s\n' "${RUN_ID}" > "${SIMAGIX_DIR}/reports/mongo-ftdc/latest_run_id.txt"
