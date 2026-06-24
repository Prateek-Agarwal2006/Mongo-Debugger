#!/usr/bin/env bash
# Clone Simagix toolchain repos required for the Docker upload pipeline.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOS_DIR="${ROOT}/simagix-workspace/repos"

clone_repo() {
  local name="$1"
  local url="$2"
  local dest="${REPOS_DIR}/${name}"
  if [[ -d "${dest}/.git" ]] || [[ -f "${dest}/go.mod" ]] || [[ -f "${dest}/Dockerfile" ]]; then
    echo "OK  ${name} (already present at ${dest})"
    return 0
  fi
  echo "Cloning ${name}..."
  git clone --depth 1 "${url}" "${dest}"
}

mkdir -p "${REPOS_DIR}"

clone_repo "mongo-ftdc" "https://github.com/simagix/mongo-ftdc.git"
clone_repo "keyhole" "https://github.com/simagix/keyhole.git"
clone_repo "hatchet" "https://github.com/simagix/hatchet.git"

FTDC_PATCH="${ROOT}/simagix-workspace/patches/mftdc-server-deferred-load.patch"
FTDC_REPO="${REPOS_DIR}/mongo-ftdc"
if [[ -d "${FTDC_REPO}/.git" ]] && [[ -f "${FTDC_PATCH}" ]]; then
  echo "Applying mongo-ftdc server deferred-load patch..."
  (cd "${FTDC_REPO}" && git apply --check "${FTDC_PATCH}" 2>/dev/null && git apply "${FTDC_PATCH}") \
    || echo "mongo-ftdc patch already applied or repo differs; skip."
fi

PATCH="${ROOT}/simagix-workspace/patches/hatchet-merge-drop-gate.patch"
HATCHET_REPO="${REPOS_DIR}/hatchet"
if [[ -d "${HATCHET_REPO}/.git" ]] && [[ -f "${PATCH}" ]]; then
  echo "Applying Hatchet merge patch..."
  (cd "${HATCHET_REPO}" && git apply --check "${PATCH}" 2>/dev/null && git apply "${PATCH}") \
    || echo "Hatchet patch already applied or repo differs; skip."
fi

echo
echo "Next: build Docker images (once):"
echo "  simagix-workspace/scripts/build-ftdc-local.sh   # patched FTDC for Grafana -server (deferred load)"
echo "  cd simagix-workspace/repos/mongo-ftdc && ./build.sh docker   # optional upstream simagix/ftdc tags"
echo "  simagix-workspace/scripts/build-hatchet-local.sh   # patched Hatchet for -merge"
echo "See docs/OPERATIONS.md for Colima, upload, and Grafana."
