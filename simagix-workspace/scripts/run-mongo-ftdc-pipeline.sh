#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"

INPUT_PATH="${1:-simagix-workspace/data/diagnostic.data}"
export MONGO_FTDC_LATEST="${MONGO_FTDC_LATEST:-0}"
export MONGO_FTDC_RAW_EXPORT="${MONGO_FTDC_RAW_EXPORT:-false}"
export MONGO_FTDC_EXPORT_TIER="${MONGO_FTDC_EXPORT_TIER:-normalized}"
export MONGO_FTDC_RUN_ID="${MONGO_FTDC_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

REPORT_DIR="${SIMAGIX_DIR}/reports/mongo-ftdc/${MONGO_FTDC_RUN_ID}"
EXPORT_DIR="${SIMAGIX_DIR}/exports/mongo-ftdc/${MONGO_FTDC_RUN_ID}"
RUN_MANIFEST="${SIMAGIX_DIR}/runs/${MONGO_FTDC_RUN_ID}/run_manifest.json"

mkdir -p "$(dirname "${RUN_MANIFEST}")"

echo "=== Mongo FTDC unified pipeline ==="
echo "Run ID: ${MONGO_FTDC_RUN_ID}"
echo "Input: ${INPUT_PATH}"
echo "Latest: ${MONGO_FTDC_LATEST}"
echo "Export tier: ${MONGO_FTDC_EXPORT_TIER}"
echo "Raw export: ${MONGO_FTDC_RAW_EXPORT}"

"${SCRIPT_DIR}/run-mongo-ftdc.sh" "${INPUT_PATH}"
"${SCRIPT_DIR}/run-llm-export.sh" "${INPUT_PATH}"

GENERATED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
cat > "${RUN_MANIFEST}" <<EOF
{
  "run_id": "${MONGO_FTDC_RUN_ID}",
  "generated_at": "${GENERATED_AT}",
  "input": "${INPUT_PATH}",
  "latest": ${MONGO_FTDC_LATEST},
  "export_tier": "${MONGO_FTDC_EXPORT_TIER}",
  "raw_export": ${MONGO_FTDC_RAW_EXPORT},
  "report_dir": "simagix-workspace/reports/mongo-ftdc/${MONGO_FTDC_RUN_ID}",
  "export_dir": "simagix-workspace/exports/mongo-ftdc/${MONGO_FTDC_RUN_ID}",
  "executive_context": "simagix-workspace/exports/mongo-ftdc/${MONGO_FTDC_RUN_ID}/llm/executive_context.json",
  "manifest": "simagix-workspace/exports/mongo-ftdc/${MONGO_FTDC_RUN_ID}/manifest.json"
}
EOF

printf '%s\n' "${MONGO_FTDC_RUN_ID}" > "${SIMAGIX_DIR}/runs/latest_run_id.txt"
ln -sfn "${SIMAGIX_DIR}/runs/${MONGO_FTDC_RUN_ID}" "${SIMAGIX_DIR}/runs/latest" 2>/dev/null || true

echo "Pipeline complete."
echo "Run manifest: ${RUN_MANIFEST}"
echo "Reports: ${REPORT_DIR}"
echo "Export: ${EXPORT_DIR}"
