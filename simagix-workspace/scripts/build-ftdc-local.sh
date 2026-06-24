#!/usr/bin/env bash
# Build patched mongo-ftdc Docker image for Grafana server mode (deferred /grafana/dir load).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${SIMAGIX_DIR}/repos/mongo-ftdc"
PATCH="${SIMAGIX_DIR}/patches/mftdc-server-deferred-load.patch"
IMAGE="${FTDC_IMAGE:-mongo-debugger/ftdc:local}"

if [[ ! -d "${REPO_DIR}" ]]; then
  echo "Missing ${REPO_DIR}. Run: scripts/setup-simagix-repos.sh"
  exit 1
fi

if [[ -f "${PATCH}" ]]; then
  echo "Applying patch ${PATCH}..."
  (cd "${REPO_DIR}" && git apply --check "${PATCH}" 2>/dev/null && git apply "${PATCH}") \
    || echo "Patch already applied or repo differs; continuing build."
fi

echo "Building ${IMAGE} from ${REPO_DIR}..."
docker build -t "${IMAGE}" "${REPO_DIR}"
docker run --rm "${IMAGE}" /mftdc -version
echo "Built ${IMAGE}"
