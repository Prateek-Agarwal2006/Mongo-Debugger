# Operations Guide

**Last updated:** 2026-06-29

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
| `GRAFANA_URL` | `http://localhost:3030` | Grafana UI base |
| `FTDC_API_URL` | `http://localhost:5408` | FTDC API for `/grafana/dir` load |
| `FTDC_LOAD_TIMEOUT_SECONDS` | `300` | Max wait for large FTDC decode into Grafana |

### Export tier reference

| Tier | Bundle size | Includes |
|------|-------------|----------|
| `analyzed` | Smallest (~100 KB tier_1) | Findings, assessment, executive context |
| `normalized` | Medium (~100 MB) | tier_1 + normalized time series |
| `forensic` | Large (~700 MB+) | tier_1 + tier_2 + raw decoder values |

## Grafana charts (recommended for metrics)

One **shared** Docker stack per machine (not per run): Grafana on `:3030`, FTDC API on `:5408`. Chart.js and iframe embed were removed; dashboards open in a **new browser tab**.

```bash
colima start --cpu 4 --memory 8
./simagix-workspace/scripts/run-grafana-stack.sh   # builds mongo-debugger/ftdc:local + starts stack
```

The FTDC container starts **without** a bootstrap `diagnostic.data` directory. Data is loaded per run via `POST /grafana/dir` (UI **Load FTDC** or pipeline warm). No `tmp/diagnostic.data` required for upload-only workflows.

On a run page (**http://localhost:8000/runs/{run_id}**):

1. **First visit this browser session** — if the Docker stack is up, the page **silently loads** this run's FTDC into the FTDC API (~2 min for large sets). Dashboard links appear immediately; data fills in when decode finishes.
2. **Reload** — links stay visible; no second decode unless you click **Load FTDC for this run** (or open a new browser session).
3. Click **Anomaly View** or **Open All Metrics** — each opens **one** Grafana tab (`localhost:3030`).

**Important:** The FTDC API is single-threaded. While it decodes, HTTP health probes may time out. The backend treats a recent successful probe as still-up for 180s so reload does not hide the dashboard buttons.

### What “Load FTDC for this run” does

The FTDC API (`:5408`) is a **singleton**: it holds one `diagnostic.data` directory in memory at a time. Grafana dashboards read metrics from that API, not from the export bundle JSON on disk.

When you load (UI button or `POST /simagix/runs/{run_id}/grafana/load`):

1. Ensures the Docker Grafana stack is running (`GrafanaStackManager.ensure_running`).
2. Resolves the **host path** to this run’s raw FTDC capture via `run_manifest.json` → `input` (e.g. an upload path under `uploads/{run_id}/inputs/` or legacy `raw/`). Falls back to export `manifest.json` or `tmp/diagnostic.data` if needed.
3. Maps that path to the container path `/workspace/...` and `POST`s it to the FTDC API `POST /grafana/dir`.
4. Returns dashboard URLs with the correct time windows (anomaly-padded window vs full capture range).

**You must load the run you are viewing** before charts show data. Opening Grafana without loading (or after loading a different run) produces empty panels.

Upload jobs may warm Grafana automatically after pipeline export.

| Link | Dashboard | Scope |
|------|-----------|--------|
| **Open Anomaly View** | `simagix-grafana-anomaly` | Top anomaly metrics, padded incident window |
| **Open All Metrics** | `simagix-grafana` | Full mongo-ftdc dashboard, entire FTDC time range |

API:

```bash
curl -X POST "http://localhost:8000/simagix/runs/<run_id>/grafana/load"
curl "http://localhost:8000/simagix/runs/<run_id>/grafana/urls"
curl "http://localhost:8000/simagix/runs/grafana/status"
```

Requires Docker (`mongo-debugger/ftdc:local` from patched mongo-ftdc + locally built `mongo-debugger-grafana-ftdc`). Build FTDC once: `simagix-workspace/scripts/build-ftdc-local.sh` (also run automatically on first Grafana load if the image is missing).

### Grafana troubleshooting (run page)

| Symptom | What was going wrong | Fix (in code) |
|---------|----------------------|---------------|
| **Reload hides Anomaly / All Metrics links**; status says *"FTDC decode in progress — stack is busy"* even though Docker containers are still up | Health probes to `:5408` / `:3030` time out while FTDC is decoding. A per-request `GrafanaStackManager` had an **empty health cache every time**, so `/grafana/urls` reported the stack down and the UI hid links. | **Module-level health cache** (`_HEALTH_CACHE` in `stack.py`, 180s TTL): after a recent successful probe, a timeout still counts as up. Frontend always shows links when `/urls` succeeds. |
| **Grafana "restarts" or feels broken after reload** | Page reload re-triggered `POST /grafana/load`, stacking decodes on the busy FTDC API; compose recovery could restart containers when probes failed. | **Session guards** in `grafana.js`: auto-load only on first visit (`sessionStorage` `wasLoaded`); skip if `:started` within 5 min (`_loadInProgress`). `ensure_stack_ready_for_load()` waits before restarting FTDC; compose uses `restart: unless-stopped`, no `--build` on recovery. |
| **One click opens multiple Grafana tabs** | Native `<a target="_blank">` opens one tab **per click event**; double/triple-click fired multiple navigations. | Open buttons are `<button>` elements with a single debounced `window.open()` (500ms). |
| **Dashboard opens but panels are empty** | FTDC API never received this run's `diagnostic.data` (auto-load skipped or load still running). | Wait for first-visit silent load to finish, or click **Load FTDC for this run**. Confirm `POST /grafana/load` returns `load.ok: 1`. |

**Operator checks:**

```bash
curl -s http://localhost:8000/simagix/runs/grafana/status | jq
curl -s "http://localhost:8000/simagix/runs/<run_id>/grafana/urls" | jq '.stack'
docker compose -f simagix-workspace/docker/grafana-compose.yaml ps
```

If status shows both services up but charts are empty, the run was not loaded into the FTDC API yet — use **Load FTDC** or wait for the first-visit auto-load to complete.

## Web upload (recommended)

Requires **Docker** for the background pipeline (Colima on Mac).

1. `colima start --cpu 4 --memory 8` (if not already running).
2. Start the backend (see below).
3. Open **http://localhost:8000/upload**.
4. Upload a `.zip` or `.tar.gz` containing `metrics.*` files, or a single `metrics.*` file.
   On Mac, if the file picker is awkward, zip first: `cd tmp && zip -r diagnostic.zip diagnostic.data`
5. The app saves uploads under `simagix-workspace/uploads/<run_id>/inputs/diagnostic.data/` and **enqueues** a Phase 1 job under `uploads/<run_id>/phase1/queue/pending/`. A **separate worker process** must be running to execute the pipeline (see **Starting the pipeline worker** below). Poll job status until `succeeded`, then open the run page.

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

```bash
uv sync --extra dev --extra llm   # Cursor SDK + google-adk for Phase 2
uv run pytest backend/tests -q
```

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
| Grafana links disappear on reload | FTDC busy → health probe timeout; dead per-request cache | Wait for decode; hard-refresh after backend update; see **Grafana troubleshooting** above |
| Multiple Grafana tabs from one click | Double/triple-click on link | Use single click; fixed in `grafana.js` debounced buttons |
| Grafana empty panels | Run not loaded into FTDC API | **Load FTDC for this run**; wait ~2 min |

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
