#!/usr/bin/env bash
# Build patched Hatchet Docker image from simagix-workspace/repos/hatchet.
# Required for -merge multi-file log ingest (upstream simagix/hatchet regressed in fd28370).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="${SIMAGIX_DIR}/repos/hatchet"
PATCH="${SIMAGIX_DIR}/patches/hatchet-merge-drop-gate.patch"
IMAGE="${HATCHET_IMAGE:-mongo-debugger/hatchet:local}"

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
docker run --rm "${IMAGE}" /hatchet -version
echo "Built ${IMAGE}"
