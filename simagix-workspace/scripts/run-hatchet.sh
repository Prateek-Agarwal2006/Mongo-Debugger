#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"
LOG_DIR="${1:-tmp/mongodb-logs}"
REPORT_DIR="${SIMAGIX_DIR}/reports/hatchet"

mkdir -p "${REPORT_DIR}"

if [ -z "$(ls -A "${PROJECT_ROOT}/${LOG_DIR}" 2>/dev/null || true)" ]; then
  echo "No MongoDB logs found in ${PROJECT_ROOT}/${LOG_DIR}"
  echo "Copy mongod.log, mongod.log.gz, mongos.log, or mongos.log.gz there, then rerun."
  exit 1
fi

echo "Running Hatchet against: ${LOG_DIR}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  simagix/hatchet \
  /hatchet -report "${LOG_DIR}" | tee "${REPORT_DIR}/hatchet-console.txt"

if [ -d "${PROJECT_ROOT}/html" ]; then
  cp -R "${PROJECT_ROOT}/html/." "${REPORT_DIR}/"
  echo "Copied generated Hatchet reports into ${REPORT_DIR}"
fi
