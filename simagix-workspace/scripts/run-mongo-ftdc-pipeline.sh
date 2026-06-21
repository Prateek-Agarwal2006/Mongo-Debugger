#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"

INPUT_PATH="${1:-tmp/diagnostic.data}"
export MONGO_FTDC_LATEST="${MONGO_FTDC_LATEST:-0}"
export MONGO_FTDC_RAW_EXPORT="${MONGO_FTDC_RAW_EXPORT:-false}"
export MONGO_FTDC_EXPORT_TIER="${MONGO_FTDC_EXPORT_TIER:-normalized}"
export MONGO_FTDC_RUN_ID="${MONGO_FTDC_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

REPORT_DIR="${SIMAGIX_DIR}/reports/mongo-ftdc/${MONGO_FTDC_RUN_ID}"
EXPORT_DIR="${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}/phase1/evidence"
RUN_MANIFEST="${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}/phase1/run_manifest.json"

mkdir -p "$(dirname "${RUN_MANIFEST}")" "${EXPORT_DIR}"

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
  "export_dir": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/evidence",
  "executive_context": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/evidence/llm/executive_context.json",
  "manifest": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/evidence/manifest.json"
}
EOF

printf '%s\n' "${MONGO_FTDC_RUN_ID}" > "${SIMAGIX_DIR}/uploads/latest_run_id.txt"
ln -sfn "${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}" "${SIMAGIX_DIR}/uploads/latest" 2>/dev/null || true

echo "Pipeline complete."
echo "Run manifest: ${RUN_MANIFEST}"
echo "Reports: ${REPORT_DIR}"
echo "Export: ${EXPORT_DIR}"
