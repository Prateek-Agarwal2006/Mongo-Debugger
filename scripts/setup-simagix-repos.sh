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

echo
echo "Next: build Docker images (once):"
echo "  cd simagix-workspace/repos/mongo-ftdc && ./build.sh docker"
echo "See docs/OPERATIONS.md for Colima, upload, and Grafana."
