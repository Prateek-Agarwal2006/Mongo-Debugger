# Operations Guide

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
```

Pins and layout: [Simagix Workspace](SIMAGIX_WORKSPACE.md).

## FTDC sample data

The workspace references a local sample via symlink:

```text
simagix-workspace/data/diagnostic.data -> ../../tmp/diagnostic.data
```

Place your own `diagnostic.data` directory at `tmp/diagnostic.data` or point scripts at a custom path.

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
./simagix-workspace/scripts/run-grafana-stack.sh   # optional — backend can start stack on first load
```

On a run page (**http://localhost:8000/runs/{run_id}**):

1. **Load FTDC for this run** — if the Docker stack is up, this runs automatically when you open the page; you can also click the button to reload. Large datasets may take ~2 minutes.
2. Click **Open Anomaly View** or **Open All Metrics** (opens `localhost:3030`).

### What “Load FTDC for this run” does

The FTDC API (`:5408`) is a **singleton**: it holds one `diagnostic.data` directory in memory at a time. Grafana dashboards read metrics from that API, not from the export bundle JSON on disk.

When you load (UI button or `POST /simagix/runs/{run_id}/grafana/load`):

1. Ensures the Docker Grafana stack is running (`GrafanaStackManager.ensure_running`).
2. Resolves the **host path** to this run’s raw FTDC capture via `run_manifest.json` → `input` (e.g. `simagix-workspace/data/diagnostic.data` or an upload path). Falls back to export `manifest.json` or `tmp/diagnostic.data` if needed.
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

Requires Docker (`simagix/ftdc` image + locally built `mongo-debugger-grafana-ftdc`).

## Web upload (recommended)

Requires **Docker** for the background pipeline (Colima on Mac).

1. `colima start --cpu 4 --memory 8` (if not already running).
2. Start the backend (see below).
3. Open **http://localhost:8000/upload**.
4. Upload a `.zip` or `.tar.gz` containing `metrics.*` files, or a single `metrics.*` file.
   On Mac, if the file picker is awkward, zip first: `cd tmp && zip -r diagnostic.zip diagnostic.data`
5. The app saves uploads under `simagix-workspace/data/uploads/<run_id>/diagnostic.data/`, runs the Docker pipeline in the background, and redirects to the run page when complete.

API equivalent:

```bash
curl -F "file=@diagnostic.zip" http://localhost:8000/simagix/uploads
curl http://localhost:8000/simagix/uploads/jobs/<job_id>
```

## Starting the RCA backend

```bash
# Mac: Docker via Colima — needed for upload pipeline and Grafana charts
colima start --cpu 4 --memory 8

uv sync --extra dev --extra llm
uv run uvicorn backend.app.main:app --reload --port 8000
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

After a pipeline run with `run_id=20260609T133314Z`:

```text
simagix-workspace/reports/mongo-ftdc/20260609T133314Z/
  ftdc_diagnosis.html
  mftdc-console.txt

simagix-workspace/exports/mongo-ftdc/20260609T133314Z/
  manifest.json
  llm/executive_context.json
  diagnosis/findings.json
  normalized/time_series.jsonl.gz
  bundle_index.json
  validation.json

simagix-workspace/runs/20260609T133314Z/
  run_manifest.json
  phase2/llm/mock/latest_report.json    # persisted RCA per LLM slot
  phase2/llm/mock/budget_state.json
```

Latest run pointers:

```text
simagix-workspace/exports/mongo-ftdc/latest_run_id.txt
simagix-workspace/exports/mongo-ftdc/latest_export_path.txt
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

## Blocked workflows

These require additional input artifacts:

```bash
# Needs logs in simagix-workspace/data/mongodb-logs/
./simagix-workspace/scripts/run-hatchet.sh

# Needs MONGO_URI
./simagix-workspace/scripts/run-keyhole.sh

# Needs Keyhole output
./simagix-workspace/scripts/run-maobi.sh
```
