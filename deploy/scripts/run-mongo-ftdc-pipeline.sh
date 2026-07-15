#!/usr/bin/env bash
# K8s-native replacement for simagix-workspace/scripts/run-mongo-ftdc-pipeline.sh
# Calls Go binaries directly (mftdc, llm-export) — no Docker daemon required.
# Placed at DATA_ROOT/simagix-workspace/scripts/ by the worker init container.
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
EXPORT_DIR="${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}/phase1/mongo-ftdc"
RUN_MANIFEST="${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}/phase1/run_manifest.json"

mkdir -p "${REPORT_DIR}" "${EXPORT_DIR}" "$(dirname "${RUN_MANIFEST}")"

echo "=== Mongo FTDC pipeline (K8s-native) ==="
echo "Run ID : ${MONGO_FTDC_RUN_ID}"
echo "Input  : ${INPUT_PATH}"
echo "Tier   : ${MONGO_FTDC_EXPORT_TIER}"

# llm-export builds the tiered evidence bundle (tier 1/2/3) that gets ingested
# into Postgres. mftdc (HTML report generator) is not needed in K8s — its output
# was disk-only and is not used by the agent or the API.
llm-export \
  -input  "${PROJECT_ROOT}/${INPUT_PATH}" \
  -output "${EXPORT_DIR}" \
  -latest "${MONGO_FTDC_LATEST}" \
  -tier   "${MONGO_FTDC_EXPORT_TIER}" \
  -raw    "${MONGO_FTDC_RAW_EXPORT}"

# ── Manifest ─────────────────────────────────────────────────────────────────
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
  "export_dir": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/mongo-ftdc",
  "executive_context": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/mongo-ftdc/llm/executive_context.json",
  "manifest": "simagix-workspace/uploads/${MONGO_FTDC_RUN_ID}/phase1/mongo-ftdc/manifest.json"
}
EOF

printf '%s\n' "${MONGO_FTDC_RUN_ID}" > "${SIMAGIX_DIR}/uploads/latest_run_id.txt"
ln -sfn "${SIMAGIX_DIR}/uploads/${MONGO_FTDC_RUN_ID}" "${SIMAGIX_DIR}/uploads/latest" 2>/dev/null || true

echo "Pipeline complete. Run ID: ${MONGO_FTDC_RUN_ID}"
