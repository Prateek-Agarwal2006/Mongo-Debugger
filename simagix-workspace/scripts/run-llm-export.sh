#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"

INPUT_PATH="${1:-tmp/diagnostic.data}"
LATEST="${MONGO_FTDC_LATEST:-0}"
RAW_EXPORT="${MONGO_FTDC_RAW_EXPORT:-false}"
EXPORT_TIER="${MONGO_FTDC_EXPORT_TIER:-normalized}"
RUN_ID="${MONGO_FTDC_RUN_ID:-${MONGO_FTDC_EXPORT_ID:-$(date -u +%Y%m%dT%H%M%SZ)}}"
EXPORT_DIR="${SIMAGIX_DIR}/uploads/${RUN_ID}/phase1/evidence"

mkdir -p "${EXPORT_DIR}"

echo "Running LLM-ready mongo-ftdc export against: ${INPUT_PATH}"
echo "Export directory: ${EXPORT_DIR}"
echo "Run ID: ${RUN_ID}"
echo "Latest files setting: ${LATEST} (0 means all files)"
echo "Export tier: ${EXPORT_TIER}"
echo "Raw decoder export: ${RAW_EXPORT}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace/simagix-workspace/repos/mongo-ftdc \
  golang:1.25 \
  go run ./cmd/llm-export \
    -input "/workspace/${INPUT_PATH}" \
    -output "/workspace/simagix-workspace/uploads/${RUN_ID}/phase1/evidence" \
    -latest "${LATEST}" \
    -tier "${EXPORT_TIER}" \
    -raw="${RAW_EXPORT}"

printf '%s\n' "${EXPORT_DIR}" > "${SIMAGIX_DIR}/uploads/latest_export_path.txt"
printf '%s\n' "${RUN_ID}" > "${SIMAGIX_DIR}/uploads/latest_run_id.txt"
echo "Latest export path saved to: ${SIMAGIX_DIR}/uploads/latest_export_path.txt"
