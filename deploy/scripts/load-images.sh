#!/usr/bin/env bash
# Build Docker images and load them into the Kind cluster.
# Run from the repo root: ./deploy/scripts/load-images.sh [cluster-name]
set -euo pipefail

CLUSTER="${1:-mongo-debugger}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"
command -v kind   >/dev/null || die "kind not found"

kind get clusters | grep -q "^${CLUSTER}$" || \
  die "Kind cluster '${CLUSTER}' not found. Run: kind create cluster --config deploy/kind/cluster.yaml"

echo "=== Building mongo-debugger-api ==="
docker build \
  -f deploy/docker/Dockerfile.api \
  -t mongo-debugger-api:latest \
  "${REPO_ROOT}"

echo "=== Building mongo-debugger-worker (multi-stage: Go + Python) ==="
docker build \
  -f deploy/docker/Dockerfile.worker \
  -t mongo-debugger-worker:latest \
  "${REPO_ROOT}"

echo "=== Building mongo-debugger-ui (Vite SPA + nginx) ==="
docker build \
  -f deploy/docker/Dockerfile.ui \
  -t mongo-debugger-ui:latest \
  "${REPO_ROOT}"

echo "=== Loading images into Kind cluster '${CLUSTER}' ==="
kind load docker-image mongo-debugger-api:latest    --name "${CLUSTER}"
kind load docker-image mongo-debugger-worker:latest --name "${CLUSTER}"
kind load docker-image mongo-debugger-ui:latest     --name "${CLUSTER}"

echo ""
echo "Images loaded. Verify with:"
echo "  kubectl get nodes -o wide"
echo "  docker exec -it ${CLUSTER}-control-plane crictl images | grep mongo-debugger"
