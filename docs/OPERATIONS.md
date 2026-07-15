# Operations Guide

**Last updated:** 2026-07-16

## Prerequisites

### Required

- macOS or Linux
- [Docker](https://docs.docker.com/get-docker/) via Colima (recommended on macOS):

```bash
brew install docker docker-compose colima
colima start --cpu 4 --memory 8 --disk 60
docker run hello-world
```

- Python 3.11 and [uv](https://docs.astral.sh/uv/):

```bash
uv python install 3.11
uv sync --extra dev
```

### Optional

- Go 1.23+ (only if building mongo-ftdc from source outside Docker)
- `MONGO_URI` (for Keyhole cluster survey)
- MongoDB log files (for Hatchet)

### Simagix repo clones (first-time setup)

The upload pipeline runs `mongo-ftdc` from Docker and `llm-export` from a local clone. Repos are **not** committed (nested git); run once after clone:

```bash
./scripts/setup-simagix-repos.sh
cd simagix-workspace/repos/mongo-ftdc && ./build.sh docker
simagix-workspace/scripts/build-hatchet-local.sh   # patched Hatchet for multi-file -merge
```

Hatchet clone is gitignored; the merge fix lives in `simagix-workspace/patches/hatchet-merge-drop-gate.patch` (applied by setup). Use image **`mongo-debugger/hatchet:local`**, not `simagix/hatchet:latest`, for multi-file merge. Details: [Simagix Toolchain — Hatchet](SIMAGIX_TOOLCHAIN.md#hatchet).

Pins and layout: [Simagix Workspace](SIMAGIX_WORKSPACE.md).

## FTDC sample data

The workspace references a local sample via symlink:

Place your FTDC sample at `tmp/diagnostic.data/` or pass a custom path to pipeline scripts.

## Running the pipeline

All Simagix pipeline scripts use **Docker**. On Mac, start Colima first (once per session):

```bash
colima start --cpu 4 --memory 8
```

All commands run from the project root.

### Unified pipeline (recommended)

Produces report + export + run manifest with one shared `run_id`:

```bash
./simagix-workspace/scripts/run-mongo-ftdc-pipeline.sh
```

Custom run ID:

```bash
MONGO_FTDC_RUN_ID=myincident20260609 ./simagix-workspace/scripts/run-mongo-ftdc-pipeline.sh
```

### Individual steps

```bash
# Human report only
./simagix-workspace/scripts/run-mongo-ftdc.sh

# Evidence bundle only
./simagix-workspace/scripts/run-llm-export.sh
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGO_FTDC_RUN_ID` | UTC timestamp | Shared run identifier for report + export |
| `MONGO_FTDC_LATEST` | `0` | Number of latest FTDC files (`0` = all) |
| `MONGO_FTDC_EXPORT_TIER` | `normalized` | `analyzed`, `normalized`, or `forensic` |
| `MONGO_FTDC_RAW_EXPORT` | `false` | Include tier_3 raw decoder output |
| `MONGO_URI` | — | Required for Keyhole |
| `DATA_ROOT` | — (repo root) | Root for all Run artifacts (`simagix-workspace/...`). Set to `/data` in K8s when PVC is mounted. See `RunWorkspace` in `backend/app/core/run_workspace.py`. |
| `PIPELINE_WORKER_POLL_SECONDS` | `2.0` | How often the standalone worker polls an empty queue. |
| `GRAFANA_URL` | `http://localhost:3030` | Grafana UI base (deep links from Evidence tab) |

### Export tier reference

| Tier | Bundle size | Includes |
|------|-------------|----------|
| `analyzed` | Smallest (~100 KB tier_1) | Findings, assessment, executive context |
| `normalized` | Medium (~100 MB) | tier_1 + normalized time series |
| `forensic` | Large (~700 MB+) | tier_1 + tier_2 + raw decoder values |

## Grafana charts (Postgres SimpleJSON)

Grafana reads **ingested** metrics from Postgres via the API SimpleJSON datasource (`/grafana/simple`). There is **no** FTDC load step and **no** Docker ftdc-api.

**Kind / Helm:** Grafana is a chart Deployment. Datasource URL inside the cluster is `http://api:8000/grafana/simple`. UI opens `http://localhost:3030` (NodePort `30300`, or `kubectl port-forward svc/grafana 3030:3000` on older Kind clusters without that mapping).

On a run page (**Evidence** tab):

1. Click **Anomaly View** — triage dashboard (`simagix-grafana-anomaly`); time = anomaly windows when present, else full capture.
2. Click **All Metrics** — full analytics dashboard (`simagix-grafana`); time = full capture (`GET /grafana/simple/runs/{run_id}/range`).
3. Switch runs with the Grafana **Run** dropdown. After switching, reopen from Evidence (or widen the time picker) if panels go empty.
4. Red shaded regions are anomaly annotations from `executive_context`.

### Quick checks

```bash
curl -s http://localhost:8000/grafana/simple/
curl -s http://localhost:8000/grafana/simple/config | jq
curl -s http://localhost:8000/grafana/simple/runs/<run_id>/range | jq
curl -s -X POST http://localhost:8000/grafana/simple/search -H 'Content-Type: application/json' -d '{"target":"runs"}' | jq
```

Login (local Helm defaults): `admin` / `admin` (anonymous Viewer is also enabled).

### Grafana troubleshooting

| Symptom | Fix |
|---------|-----|
| **Anomaly View** / **All Metrics** fails to connect | Kind: ensure Grafana pod is Ready; `kubectl port-forward svc/grafana 3030:3000` if NodePort mapping is missing |
| Empty panels | Confirm the run was ingested; open via Evidence so `from`/`to` match the capture; `GET /grafana/simple/runs/<id>/range` shows the window |
| Only a few panels | Use **All Metrics** (full catalog). **Anomaly View** is the triage subset |
| Wrong run | Use the Grafana **Run** template variable (or reopen from the Evidence tab) |

## Kind rebuild (UI + API + worker)

Wipe old images from the Kind nodes, rebuild, reload, and roll pods:

```bash
# From repo root — full rebuild + load
./deploy/scripts/load-images.sh

# Or wipe Kind-local image tags first, then rebuild:
docker rmi mongo-debugger-ui:latest mongo-debugger-api:latest mongo-debugger-worker:latest 2>/dev/null || true
./deploy/scripts/load-images.sh
helm upgrade --install mongo-debugger deploy/helm \
  --set postgres.password=password \
  -f deploy/values-local.yaml \
  --wait --timeout 5m
kubectl rollout restart deploy/ui deploy/api deploy/worker
kubectl rollout status deploy/ui deploy/api deploy/worker --timeout=180s
kubectl get pods -l 'app in (ui,api,worker)'
```

Entry point: **http://localhost:8000** → **ui** nginx (SPA) → **api** ClusterIP.

### Catalog “Database unavailable” / Postgres CrashLoop

SPA home/runs/run pages call `/simagix/catalog*`. Those need Postgres. If Postgres is crash-looping, catalog returns 500 and the SPA shows **Database unavailable**.

**Common Kind cause:** after a heavy ingest / unclean shutdown, Postgres does WAL redo. A tight **liveness** probe (`timeoutSeconds: 1`, short `initialDelaySeconds`) kills the container mid-recovery → death spiral.

**Fix:** Helm postgres probes allow ~2+ minutes for recovery (`initialDelaySeconds: 120` on liveness, `timeoutSeconds: 5`). Then:

```bash
helm upgrade --install mongo-debugger deploy/helm \
  --set postgres.password=password \
  -f deploy/values-local.yaml
kubectl rollout status deploy/postgres --timeout=300s
kubectl rollout restart deploy/api deploy/worker
kubectl get pods -l 'app in (postgres,api,worker)'
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8000/simagix/catalog
```

---

## Web upload (recommended)

Requires **Docker** for the background pipeline (Colima on Mac) when running locally; Kind uses the worker image with baked binaries.
1. `colima start --cpu 4 --memory 8` (if not already running).
2. Start the backend (see below).
3. Open **http://localhost:8000/upload**.
4. Upload a **`.zip` (or `.tar.gz`) of your `diagnostic.data` folder** (nested `metrics.*` inside is fine), or a single `metrics.*` file.
   Do **not** drag an unzipped folder into the browser — zip it first: `zip -r diagnostic.zip diagnostic.data`
   The file picker is intentionally unfiltered (macOS greys out valid zips when `accept` lists `.tar.gz` / `metrics.*`); the API validates format.
5. After the upload POST accepts, the UI redirects to **`/runs/<run_id>`**. The SPA calls **`GET /simagix/catalog/{run_id}`** — unfinished Phase 1 shows **Decoding** / **Loading metrics**; success shows the RCA workspace. A **separate worker** must be running (Kind: `deploy/worker`).

6. **Optional — MongoDB logs (Hatchet):** on **http://localhost:8000/runs/{run_id}**, use **Upload logs** in the Hatchet card. Select individual `mongod.log` / rotated `mongod.log.*` files **or** zip them first (`zip case-7-logs.zip mongod*.log*`). Files land in `inputs/mongodb-logs/` and enqueue `job_type: hatchet`. **Retry** or a new log upload **deletes** prior `phase1/hatchet/hatchet.db*` so each run starts a fresh SQLite parse (avoids half-finished DBs from interrupted Docker). Large logs (~435 MB+) often take **30–45 minutes** — one worker only; do not run manual `run-hatchet-job.sh` in parallel. Phase 2 stays blocked until `phase1/hatchet/summary.json` exists when logs were uploaded.

**If the pipeline fails** (e.g. Docker not running): the upload files remain; the job record shows `failed` under `uploads/<run_id>/phase1/jobs/{job_id}.json`. The queue entry is removed — nothing blocks other jobs. If a job is `pending` but never enqueued, the catalog shows **Not enqueued** (stale). Open **http://localhost:8000/runs**, find the upload, click **Retry** (or use the Phase 1 page). Fix Docker first (`colima start`), ensure the worker is running, then retry — no need to upload again.

**Restart the worker after backend code changes** (unlike uvicorn `--reload`, the worker does not auto-reload):

```bash
pkill -f "backend.app.jobs.worker" || true
uv run python -m backend.app.jobs.worker
```

**Stop / restart the API** (required after `.env` changes — `get_settings()` is cached for the process lifetime):

```bash
pkill -f "uvicorn backend.app.main:app" || true
lsof -ti :8000 | xargs kill -9   # only if port still in use
uv run uvicorn backend.app.main:app --reload --port 8000
```

Ensure `simagix-workspace/scripts/run-hatchet-job.sh` is executable (`chmod +x`) or rely on the worker invoking it via `bash`.

**Local “fake PVC”:** both API and worker must share the same root:

```bash
export DATA_ROOT=/tmp/mongo-debugger-data
mkdir -p "$DATA_ROOT"
ln -sf "$(pwd)/simagix-workspace" "$DATA_ROOT/simagix-workspace"   # once, for scripts/docker paths
```

**K8s:** mount the same PVC at `/data` on API and worker Deployments; set `DATA_ROOT=/data` on both.

API equivalent:

```bash
curl -F "file=@diagnostic.zip" http://localhost:8000/simagix/uploads
curl http://localhost:8000/simagix/uploads/jobs/<job_id>
curl -X POST http://localhost:8000/simagix/uploads/runs/<run_id>/retry
```

## Starting the RCA backend

```bash
# Mac: Docker via Colima — needed for upload pipeline and Grafana charts
colima start --cpu 4 --memory 8

uv sync --extra dev --extra llm

# Terminal 1 — API
uv run uvicorn backend.app.main:app --reload --port 8000

# Terminal 2 — pipeline worker (required for uploads to process)
uv run python -m backend.app.jobs.worker
```

Web UI: **http://localhost:8000**

Verify:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/simagix/runs
./scripts/demo.sh
```

Load analyzed context for a run:

```bash
RUN_ID=phase1test20260609T133314Z
curl "http://localhost:8000/simagix/runs/${RUN_ID}/context" | jq .
```

Request a fallback metric slice:

```bash
curl "http://localhost:8000/simagix/runs/${RUN_ID}/tools/metric-window?metric=cpu_idle&limit=10" | jq .
```

## Phase 2 LLM (live RCA)

Copy `.env.example` to `.env` and choose a provider:

| Provider | Env | Install |
|----------|-----|---------|
| Mock (default in tests) | `{"llm":"mock"}` in API or no API keys | `uv sync --extra dev` |
| Cursor SDK | `LLM_PROVIDER=cursor`, `CURSOR_API_KEY=...` | `uv sync --extra dev --extra llm` |
| Gemini ADK | `LLM_PROVIDER=gemini`, `GOOGLE_API_KEY=...` from [AI Studio](https://aistudio.google.com/apikey) | `uv sync --extra dev --extra llm` |

Run investigation + clarifying questions:

```bash
curl -X POST "http://localhost:8000/simagix/runs/${RUN_ID}/phase2/run" \
  -H 'Content-Type: application/json' -d '{"llm_provider": "gemini"}'
```

On the run detail page (`/runs/{run_id}`), use the **LLM** dropdown next to **Run RCA** to pick mock/cursor/gemini for both running and viewing that slot's status, trace, and report.

Optional chatbot / web-fetch env (see `.env.example`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `PHASE2_CHATBOT_MAX_TOOL_CALLS` | 5 | MCP budget per chatbot message |
| `PHASE2_CHATBOT_MAX_ATTACHMENT_BYTES` | 524288 | Max chatbot file attachment size (512 KiB) |
| `PHASE2_CHATBOT_MAX_REPLAY_MESSAGES` | 12 | Recent messages replayed verbatim in prompt |
| `PHASE2_CHATBOT_SUMMARIZE_AFTER_MESSAGES` | 20 | Fold older turns into `summary_of_older` |
| `PHASE2_WEB_FETCH_MAX_BYTES` | 24000 | HTTPS fetch cap |
| `PHASE2_WEB_ALLOWLIST_SUFFIXES` | (unset) | Optional comma-separated host suffix allowlist |

Details: [PHASE2_LLM.md](PHASE2_LLM.md).

## Running tests

Tests need Postgres (`DATABASE_URL`). Example local DB:

```bash
docker run -d --name mongo-debugger-pg -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=mongodebugger -p 5544:5432 postgres:16-alpine
export DATABASE_URL=postgresql://postgres:dev@localhost:5544/mongodebugger
uv sync --extra prod --extra dev --extra llm   # psycopg pool + Cursor SDK + google-adk
uv run pytest backend/tests -q
```

GitHub Actions (`.github/workflows/test.yml`) starts Postgres 16 as a service, syncs `--extra prod`, and sets `DATABASE_URL` automatically.

Simagix-specific tests:

```bash
uv run pytest backend/tests/test_simagix_rca.py -q
```

## Output locations

After a pipeline run with `run_id=phase1test20260609T133314Z` (or your upload `run_id`):

```text
simagix-workspace/reports/mongo-ftdc/<run_id>/
  ftdc_diagnosis.html
  mftdc-console.txt

simagix-workspace/uploads/<run_id>/phase1/mongo-ftdc/
  manifest.json
  llm/executive_context.json
  diagnosis/findings.json
  normalized/time_series.jsonl.gz
  bundle_index.json
  validation.json

simagix-workspace/uploads/<run_id>/
  phase1/run_manifest.json
  phase2/llm/mock/latest_report.json    # persisted RCA per LLM slot
  phase2/llm/mock/budget_state.json
```

Latest run pointers (pipeline scripts):

```text
simagix-workspace/uploads/latest_run_id.txt
simagix-workspace/uploads/latest_export_path.txt
simagix-workspace/uploads/latest          # symlink to latest run dir
```

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Docker not running | Colima stopped | `colima start` |
| Export validation fails | Partial export interrupted | Re-run pipeline; check `validation.json` |
| Run not found in API | Missing `manifest.json` | Ensure export completed; check run_id |
| Report vs export mismatch | Different `run_id` or `-latest` | Use `run-mongo-ftdc-pipeline.sh` |
| Raw export too large | `-raw=true` default in old scripts | Set `MONGO_FTDC_RAW_EXPORT=false` |
| `429` on tool calls | Retrieval budget exhausted | New evidence-service instance per session |
| Grafana empty panels | Time range misses capture, run not ingested, or SimpleJSON plugin disabled | Open from Evidence (sets `from`/`to`); or `GET /grafana/simple/runs/<id>/range`; confirm search lists the run; `GF_PLUGINS_ANGULAR_SUPPORT_ENABLED=true` |

## Blocked workflows

These require additional input artifacts (manual CLI only — web upload uses the run page for Hatchet logs):

```bash
# Manual dev: logs in tmp/mongodb-logs/ (legacy HTML report script)
./simagix-workspace/scripts/run-hatchet.sh

# Worker path (v1, no HTML): run-hatchet-job.sh <run_id>
bash simagix-workspace/scripts/run-hatchet-job.sh upload20260618T120000Z

# Needs MONGO_URI
./simagix-workspace/scripts/run-keyhole.sh

# Needs Keyhole output
./simagix-workspace/scripts/run-maobi.sh
```
