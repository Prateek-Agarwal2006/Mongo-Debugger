#!/usr/bin/env bash
# Install (or upgrade) the Helm chart into the Kind cluster.
# Run from the repo root: ./deploy/scripts/deploy.sh [values-override.yaml]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHART_DIR="${REPO_ROOT}/deploy/helm"
RELEASE="mongo-debugger"
NAMESPACE="default"
VALUES_OVERRIDE="${1:-}"

die() { echo "ERROR: $*" >&2; exit 1; }
command -v helm >/dev/null || die "helm not found"

# Require a values override with secrets for non-trivial deploys.
# To run without API keys (local testing only): pass an empty file.
EXTRA_VALUES=""
if [ -n "${VALUES_OVERRIDE}" ]; then
  EXTRA_VALUES="--values ${VALUES_OVERRIDE}"
  echo "Using values override: ${VALUES_OVERRIDE}"
fi

echo "=== Deploying ${RELEASE} to namespace ${NAMESPACE} ==="
helm upgrade --install "${RELEASE}" "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --set postgres.password="password" \
  ${EXTRA_VALUES} \
  --wait --timeout 5m

echo ""
echo "=== Deployment status ==="
kubectl get pods -n "${NAMESPACE}" -l app.kubernetes.io/name=mongo-debugger

echo ""
echo "API + Modern UI available at: http://localhost:8000"
echo "  (Kind NodePort 30000 → ui nginx → proxies /simagix to api ClusterIP)"
echo "Grafana is available at: http://localhost:3030 (admin/admin)"
echo "(Kind maps NodePort 30000→8000 and 30300→3030 via cluster.yaml extraPortMappings)"
echo "If Grafana port mapping is missing on an older Kind cluster, run:"
echo "  kubectl port-forward svc/grafana 3030:3000"
echo ""
echo "To test ftdc-slice directly in the worker pod:"
echo "  kubectl exec -it deploy/worker -- ftdc-slice --help"
echo ""
echo "To test with a local FTDC file:"
echo "  kubectl cp /path/to/diagnostic.data default/\$(kubectl get pod -l app=worker -o name | head -1 | cut -d/ -f2):/tmp/diagnostic.data"
echo "  kubectl exec -it deploy/worker -- ftdc-slice --mode catalog /tmp/diagnostic.data/metrics.2026-06-24T08-45-38Z-00000"
