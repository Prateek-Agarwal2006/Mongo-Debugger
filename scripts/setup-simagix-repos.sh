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

# mongo-ftdc (incl. cmd/ftdc-slice) is vendored under simagix-workspace/repos/mongo-ftdc
# — Kind/Docker builds COPY that tree; no upstream clone required for Phase 1/tier-3.
FTDC_REPO="${REPOS_DIR}/mongo-ftdc"
if [[ -f "${FTDC_REPO}/go.mod" ]] && [[ -f "${FTDC_REPO}/cmd/ftdc-slice/main.go" ]]; then
  echo "OK  mongo-ftdc (vendored at ${FTDC_REPO}, includes ftdc-slice)"
elif [[ -f "${FTDC_REPO}/go.mod" ]]; then
  echo "WARN mongo-ftdc present but cmd/ftdc-slice missing — Kind api/worker builds will fail."
else
  echo "Cloning mongo-ftdc (vendored tree missing)..."
  git clone --depth 1 "https://github.com/simagix/mongo-ftdc.git" "${FTDC_REPO}"
  echo "WARN upstream has no ftdc-slice — restore vendored tree from git history."
fi

clone_repo "keyhole" "https://github.com/simagix/keyhole.git"
clone_repo "hatchet" "https://github.com/simagix/hatchet.git"

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
