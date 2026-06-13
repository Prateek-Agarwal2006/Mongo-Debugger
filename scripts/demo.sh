#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

RUN_ID="${DEMO_RUN_ID:-phase1test20260605T071425Z}"
BASE="http://localhost:8000"

echo "=== FTDC Analyzer Demo ==="
echo "Base URL: ${BASE}"
echo "Run ID:   ${RUN_ID}"
echo

curl -sf "${BASE}/health" | python3 -m json.tool
echo

echo "--- Runs ---"
curl -sf "${BASE}/simagix/runs" | python3 -m json.tool
echo

echo "--- Tier-1 context (truncated) ---"
curl -sf "${BASE}/simagix/runs/${RUN_ID}/context" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('findings:', len(d.get('findings',[])))
print('anomalies:', len(d.get('top_anomaly_windows',[])))
"
echo

echo "--- Anomaly correlation ---"
curl -sf "${BASE}/simagix/runs/${RUN_ID}/phase2/anomaly-correlation" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('clusters:', len(d.get('correlated_clusters',[])))
"
echo

echo "--- Phase A+B: Investigation + clarifying questions (mock) ---"
START_JSON="$(curl -sf -X POST "${BASE}/simagix/runs/${RUN_ID}/phase2/run" \
  -H 'Content-Type: application/json' \
  -d '{"force_mock": true}')"
echo "${START_JSON}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('status:', d.get('status'))
print('investigation:', (d.get('investigation') or {}).get('summary','')[:120], '...')
print('questions:', len((d.get('clarifying_questions') or {}).get('questions', [])))
"

FIRST_QID="$(echo "${START_JSON}" | python3 -c "
import json,sys
qs=(json.load(sys.stdin).get('clarifying_questions') or {}).get('questions') or []
print(qs[0]['id'] if qs else '')
")"

ANSWERS_JSON='{"answers": {}}'
if [[ -n "${FIRST_QID}" ]]; then
  ANSWERS_JSON="$(python3 -c "import json; print(json.dumps({'answers': {'${FIRST_QID}': 'No maintenance during window'}}))")"
fi

echo
echo "--- Phase C: Final RCA (mock) ---"
curl -sf -X POST "${BASE}/simagix/runs/${RUN_ID}/phase2/clarify?force_mock=true" \
  -H 'Content-Type: application/json' \
  -d "${ANSWERS_JSON}" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('status:', d.get('status'))
print('summary:', (d.get('report') or {}).get('summary','')[:120], '...')
"
echo

echo "Web UI:  ${BASE}/"
echo "Run:     ${BASE}/runs/${RUN_ID}"
echo "Report:  ${BASE}/simagix/runs/${RUN_ID}/phase2/reports/latest/view"
echo "Done."
