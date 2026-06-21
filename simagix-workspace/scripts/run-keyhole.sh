#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"
OUTPUT_DIR="tmp/keyhole-output"
REPORT_DIR="${SIMAGIX_DIR}/reports/keyhole"

mkdir -p "${PROJECT_ROOT}/tmp/keyhole-output" "${REPORT_DIR}"

if [ -z "${MONGO_URI:-}" ]; then
  echo "MONGO_URI is required for Keyhole."
  echo "Example:"
  echo "  export MONGO_URI='mongodb+srv://user:password@cluster.example.mongodb.net/'"
  echo "  ./simagix-workspace/scripts/run-keyhole.sh"
  exit 1
fi

echo "Running Keyhole -allinfo with obfuscation enabled."
echo "Output directory: ${PROJECT_ROOT}/${OUTPUT_DIR}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w "/workspace/${OUTPUT_DIR}" \
  -e MONGO_URI="${MONGO_URI}" \
  simagix/keyhole \
  /keyhole -allinfo "${MONGO_URI}" -obfuscate | tee "${REPORT_DIR}/keyhole-console.txt"
