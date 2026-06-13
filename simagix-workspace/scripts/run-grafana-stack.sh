#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMAGIX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${SIMAGIX_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

# Ensure anomaly-focus dashboard exists
uv run python -m backend.app.grafana.anomaly_dashboard

echo "Starting Grafana + FTDC API stack..."
echo "(On Mac, run 'colima start --cpu 4 --memory 8' first if Docker is not running.)"
docker compose -f simagix-workspace/docker/grafana-compose.yaml up -d

echo "Grafana UI:  http://localhost:${GRAFANA_PORT:-3030}"
echo "FTDC API:    http://localhost:${FTDC_PORT:-5408}"
echo ""
echo "Load a run's data:"
echo '  curl -XPOST http://localhost:5408/grafana/dir -H "Content-Type: application/json" \'
echo '    -d '"'"'{"dir": "/workspace/tmp/diagnostic.data"}'"'"
