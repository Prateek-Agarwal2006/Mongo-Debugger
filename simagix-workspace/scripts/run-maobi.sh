#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"
REPORT_DIR="${SIMAGIX_DIR}/reports/maobi"

mkdir -p "${REPORT_DIR}"

if [ "${1:-}" != "" ]; then
  INPUT_PATH="$1"
else
  INPUT_PATH="$(ls -t "${PROJECT_ROOT}/tmp/keyhole-output"/* 2>/dev/null | head -n 1 || true)"
  if [ -n "${INPUT_PATH}" ]; then
    INPUT_PATH="${INPUT_PATH#${PROJECT_ROOT}/}"
  fi
fi

if [ -z "${INPUT_PATH:-}" ]; then
  echo "No Keyhole output found."
  echo "Run ./simagix-workspace/scripts/run-keyhole.sh first, or pass a Keyhole output file path."
  exit 1
fi

echo "Running Maobi against: ${INPUT_PATH}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace \
  simagix/maobi \
  /maobi "${INPUT_PATH}" | tee "${REPORT_DIR}/maobi-console.txt"

if [ -d "${PROJECT_ROOT}/html" ]; then
  cp -R "${PROJECT_ROOT}/html/." "${REPORT_DIR}/"
  echo "Copied generated Maobi reports into ${REPORT_DIR}"
fi
