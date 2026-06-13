# RCA Backend API

The RCA backend loads mongo-ftdc's pre-analyzed evidence, exposes fallback retrieval tools, serves the **web UI**, and orchestrates the Phase 2 agentic RCA layer.

Base URL: `http://localhost:8000`  
Web UI: `http://localhost:8000/`  
API docs: `http://localhost:8000/docs`

---

## Web UI

| Route | Description |
|-------|-------------|
| `GET /` | Home dashboard |
| `GET /upload` | Upload FTDC archive |
| `GET /runs` | List runs |
| `GET /runs/{run_id}` | Run detail, Grafana charts, RCA panel |

---

## Upload & pipeline jobs

### Upload diagnostic.data archive

```http
POST /simagix/uploads
Content-Type: multipart/form-data
```

Form field: `file` — `.zip` or `.tar.gz` archive containing `metrics.*` files, or a single `metrics.*` FTDC file. Nested archive folders (e.g. `diagnostic.data/metrics.*`) are flattened when all metrics share one parent directory.

Uploads are stored at `simagix-workspace/data/uploads/<run_id>/diagnostic.data/`. Processing requires Docker (same pipeline as CLI).

Response:

```json
{
  "job_id": "uuid",
  "run_id": "upload20260610T120000Z",
  "input_path": "simagix-workspace/data/uploads/.../diagnostic.data",
  "status": "pending"
}
```

### Job status

```http
GET /simagix/uploads/jobs/{job_id}
```

---

## Health

```http
GET /health
```

Response:

```json
{ "status": "ok" }
```

---

## Simagix runs

All Simagix endpoints are under `/simagix/runs/`.

### List runs

```http
GET /simagix/runs
```

Returns all export bundles that have an authoritative `manifest.json`.

Response:

```json
{
  "runs": ["phase1test20260609T133314Z", "20260609T111629Z"]
}
```

### Get tier_1 prompt context

```http
GET /simagix/runs/{run_id}/context
```

Returns the assembled analyzed context for LLM consumption:

- time range, host, MongoDB version
- findings (full list)
- top anomaly windows
- assessment highlights
- read order and fallback file pointers

This is the **primary input** for Phase 2 LLM RCA.

### Get full tier_1 bundle

```http
GET /simagix/runs/{run_id}/tier1
```

Returns the complete `Tier1Context` model including manifest, validation, bundle index, and fallback retrieval index.

---

## Fallback tools (tier_2 / tier_3)

These endpoints are for when analyzed evidence is insufficient. The LLM (Phase 2) calls these via the backend — not by reading raw files directly.

### Get metric window

```http
GET /simagix/runs/{run_id}/tools/metric-window?metric=cpu_idle&limit=500
```

Query parameters:

| Param | Type | Description |
|-------|------|-------------|
| `metric` | string | Metric name (e.g. `cpu_idle`, `repl_lag_host-1`) |
| `start` | datetime | Optional window start (ISO 8601) |
| `end` | datetime | Optional window end (ISO 8601) |
| `limit` | int | Max data points (default 500) |

Response:

```json
{
  "metric": "cpu_idle",
  "source_file": "normalized/time_series.jsonl.gz",
  "tier": "tier_2_normalized",
  "points": [[97.0, 1780421343004], ...],
  "point_count": 500
}
```

### Get normalized series (batch)

```http
GET /simagix/runs/{run_id}/tools/normalized-series?metric=cpu_idle&metric=write_conflicts/s&limit=100
```

Returns a map of metric name to window result.

### Get raw path (forensic)

```http
GET /simagix/runs/{run_id}/tools/raw-path?path_contains=serverStatus&limit=100
```

Only available when the bundle was exported with `-tier=forensic` or `-raw=true`.

### List fallback metrics

```http
GET /simagix/runs/{run_id}/tools/fallback-metrics?pattern=repl
```

Returns metric names from `llm/fallback_retrieval_index.json`.

---

## Budget and Phase 2

### Retrieval budget

```http
GET /simagix/runs/{run_id}/budget
```

Tracks fallback tool call usage (max 12 calls per orchestrator session).

Response:

```json
{
  "max_tool_calls": 12,
  "tool_calls_used": 2,
  "remaining_tool_calls": 10,
  "tool_call_history": ["get_metric_window", "get_normalized_series"],
  "budget_exhausted": false
}
```

Returns `429` when budget is exhausted.

### Phase 2 LLM package

```http
GET /simagix/runs/{run_id}/phase2/package
```

Returns everything needed to wire an LLM provider:

- `prompt` — assembled from tier_1 context
- `context` — full tier_1 data
- `grounding_rules` — citation requirements
- `retrieval_budget` — current budget status
- `output_schema` — `RCAReportDraft` JSON schema
- `available_tools` — list of fallback tool names

### Golden incident evaluation

```http
GET /simagix/runs/{run_id}/eval
```

Runs checks against the golden incident fixture. Useful for CI and regression testing.

---

## Grafana charts (spec 3.3)

One shared local stack: Grafana `:3030`, FTDC API `:5408` (Docker / Colima required).

| Endpoint | Purpose |
|----------|---------|
| `POST /simagix/runs/{run_id}/grafana/load` | Decode run's FTDC into FTDC API (~2 min for large sets) |
| `GET /simagix/runs/{run_id}/grafana/urls` | Dashboard URLs for Anomaly Focus + All Metrics |
| `GET /simagix/runs/grafana/status` | Stack health |

Run page: **Load FTDC for this run** → **Open Anomaly View** / **Open All Metrics** (new tab, no iframe).

---

## Phase 2 RCA endpoints

### Start RCA (Phase A+B)

```http
POST /simagix/runs/{run_id}/phase2/run
```

Body: `{"force_mock": true}` (optional). Runs tier-2 investigation and returns clarifying questions.

### Session status

```http
GET /simagix/runs/{run_id}/phase2/status
```

Response includes `tool_trace_summary` (total calls and counts by category: `mcp`, `web`, `local`, `shell`).

### Agent tool trace

```http
GET /simagix/runs/{run_id}/phase2/tool-trace
```

Returns SDK `tool_call` events persisted to `simagix-workspace/runs/{run_id}/phase2/tool_trace.json`. Used by the run page **Agent Tool Activity** panel (`#tool-trace-panel`).

### Latest report

```http
GET /simagix/runs/{run_id}/phase2/reports/latest?format=pretty
GET /simagix/runs/{run_id}/phase2/reports/latest/view
```

### Hybrid anomaly correlation

```http
GET /simagix/runs/{run_id}/phase2/anomaly-correlation
```

### Final RCA (Phase C)

```http
POST /simagix/runs/{run_id}/phase2/clarify?force_mock=true
```

Body: `{"answers": {"question_id": "operator answer"}}`. Runs final RCA with investigation + operator answers.

### Profiler data

```http
POST /simagix/runs/{run_id}/phase2/profiler
GET /simagix/runs/{run_id}/phase2/profiler
```

---

## Python integration example

```python
from pathlib import Path
from backend.app.simagix.orchestrator import SimagixRCAOrchestrator

workspace = Path(".")
orch = SimagixRCAOrchestrator(workspace, "phase1test20260609T133314Z")

# Primary: analyzed context
context = orch.get_prompt_context()

# Fallback: metric proof
window = orch.get_metric_window("repl_lag_host-1", limit=50)

# Phase 2 package
package = orch.build_phase2_llm_package()
```

---

## Backend layout

FastAPI app under `backend/app/`.

### Modules

| Module | Path | Purpose |
|--------|------|---------|
| Simagix RCA | `app/simagix/` | Bundle loader, fallback tools, orchestrator |
| Phase 2 LLM | `app/simagix/llm/` | Cursor agent, MCP server, 3-phase RCA flow |
| Web UI | `app/web/` | Jinja2 templates, pages |
| Upload jobs | `app/jobs/` | Background pipeline runner |
| API | `app/api/` | REST routes (runs, phase2, upload, grafana) |
| Static | `app/static/` | CSS, Grafana client JS |

### Web UI routes

| Route | Description |
|-------|-------------|
| `GET /` | Home — recent runs and jobs |
| `GET /upload` | Upload FTDC archive |
| `GET /runs` | List analysis runs |
| `GET /runs/{run_id}` | Run detail, Grafana charts, RCA panel |

### Phase 2 persistence

```text
simagix-workspace/runs/<run_id>/phase2/latest_report.json
```

### Environment

```bash
export CURSOR_API_KEY="cursor_..."      # live agent
export GRAYLOG_API_URL="..."            # optional Graylog MCP
export GRAYLOG_API_TOKEN="..."
```

### Tests

```bash
uv run pytest backend/tests -q
```
