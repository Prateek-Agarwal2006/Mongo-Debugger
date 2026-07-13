# RCA Backend API

The RCA backend loads mongo-ftdc's pre-analyzed evidence, exposes fallback retrieval tools, serves the **web UI**, and orchestrates the Phase 2 agentic RCA layer.

Base URL: `http://localhost:8000`  
Web UI: `http://localhost:8000/`  
API docs: `http://localhost:8000/docs` (Bootstrap-themed Swagger UI) · ReDoc: `/redoc`

**Last updated:** 2026-07-01

**Path resolution:** All run-scoped disk paths go through `get_run_workspace()` in `backend/app/core/run_workspace.py`. Set env `DATA_ROOT` to the mount root (default: repo root). Layout under `{DATA_ROOT}/simagix-workspace/...` is unchanged.

---

## Web UI

| Route | Description |
|-------|-------------|
| `GET /` | Home dashboard |
| `GET /upload` | Upload FTDC archive |
| `GET /mcp-workarea` | Configure operator MCP connectors (registry on disk) |
| `GET /skill-workarea` | Upload operator skill packages (ZIP by slot name) |
| `GET /runs` | List runs |
| `GET /runs/{run_id}` | Run detail, Grafana charts, RCA panel (MCP checkboxes before Run RCA) |

---

## Upload & pipeline jobs

### Upload diagnostic.data archive

```http
POST /simagix/uploads
Content-Type: multipart/form-data
```

Form field: `file` — `.zip` or `.tar.gz` archive containing `metrics.*` files, or a single `metrics.*` FTDC file. Nested archive folders (e.g. `diagnostic.data/metrics.*`) are flattened when all metrics share one parent directory.

Uploads are stored at `simagix-workspace/uploads/<run_id>/inputs/diagnostic.data/` (legacy reads: `data/uploads/...`). The API **enqueues** a per-upload file-queue job with `job_type: "mongo_ftdc"`; the **standalone worker** (`python -m backend.app.jobs.worker`) runs the Docker pipeline. Processing requires Docker (same pipeline as CLI).

Response:

```json
{
  "job_id": "uuid",
  "run_id": "upload20260610T120000Z",
  "input_path": "simagix-workspace/uploads/<run_id>/inputs/diagnostic.data",
  "status": "pending"
}
```

### Job status

```http
GET /simagix/uploads/jobs/{job_id}
```

### Retry failed pipeline (Phase 1 decode)

```http
POST /simagix/uploads/runs/{run_id}/retry
```

Re-enqueues Phase 1 for an **existing upload** (same `run_id`, new `job_id`). Does **not** re-upload the file.

| Response | Meaning |
|----------|---------|
| **200** | New job created and enqueued |
| **404** | Upload folder missing |
| **409** | Export bundle already exists (`manifest.json`), **or** pipeline already queued/running for this run |

Response shape matches upload: `{ job_id, run_id, input_path, status, job_type }`.

### Upload MongoDB logs (Hatchet, optional second step)

```http
POST /simagix/uploads/runs/{run_id}/logs
Content-Type: multipart/form-data
```

Form field: `files` — one or more MongoDB JSON log files (`.log`, rotated `.log.*`, `.log.gz`, `.txt`) **or** a `.zip`/`.tar.gz` archive containing those files. Requires an existing FTDC upload (`run_id`). Saves under `inputs/mongodb-logs/` and enqueues `job_type: "hatchet"`. Large files are streamed to disk in 1 MiB chunks.

Response:

```json
{
  "job_id": "uuid",
  "run_id": "upload20260610T120000Z",
  "saved_files": ["mongod.log"],
  "status": "pending",
  "job_type": "hatchet"
}
```

### Retry Hatchet log analysis

```http
POST /simagix/uploads/runs/{run_id}/logs/retry
```

Re-enqueues Hatchet for an upload that already has log files (same `run_id`, new `job_id`). Clears stale `summary.json` before enqueue.

| Response | Meaning |
|----------|---------|
| **200** | New hatchet job created and enqueued |
| **404** | Run or log directory missing |
| **409** | Hatchet already queued/running for this run |

UI: log upload + retry on `/runs/{run_id}` when FTDC export is ready.

Business logic: `backend/app/jobs/hatchet_retry.py`, worker entry `backend/app/jobs/hatchet.py`. FTDC retry: `backend/app/jobs/retry.py` (see [Jobs module layout](#jobs-module-layout) below).

UI (FTDC retry): buttons on Home, `/runs`, and `/runs/{run_id}/pipeline` when status is **failed** or **stale** (Not enqueued).

---

## Pipeline worker and queue cleanup (`finally`)

The API **does not** run the pipeline in-process. A separate process polls the file queue:

```bash
uv run python -m backend.app.jobs.worker
```

### Two files per in-flight job

| File | Meaning |
|------|---------|
| `phase1/queue/pending\|processing/{job_id}.json` | **Work ticket** — worker owns this while scheduled or running |
| `phase1/jobs/{job_id}.json` | **Outcome record** — `pending` / `running` / `succeeded` / `failed` |

### Worker `try` / `finally`

```python
# backend/app/jobs/worker.py — process_one()
try:
    if claimed.job_type == "hatchet":
        run_hatchet_job(...)
    else:
        run_pipeline_job(...)
finally:
    self._queue.complete(claimed.run_id, claimed.job_id)  # deletes processing/{job_id}.json
```

Queue ticket JSON includes `job_type` (`mongo_ftdc` default for legacy tickets). One FIFO worker handles both tool jobs.

**`finally` always runs** after `run_pipeline_job` returns — whether the pipeline succeeded, failed, timed out, or raised an exception. It deletes the queue file so the run is no longer “in flight.”

| What happened | Queue file after `finally` | Where failure/success is recorded |
|---------------|----------------------------|----------------------------------|
| Pipeline succeeded | Deleted | `jobs/{job_id}.json` → `succeeded` |
| Pipeline failed | Deleted | `jobs/{job_id}.json` → `failed` |
| Worker process killed (`kill -9`) mid-run | May remain in `processing/` | Requeued to `pending/` on next worker startup |

### If `finally` / `complete()` were omitted on failure

| Problem | Effect |
|---------|--------|
| `processing/{job_id}.json` left behind | Catalog shows **processing** forever |
| `has_active_job_for_run()` stays **True** | **Retry returns 409** even though worker finished |
| Stale recovery on restart | Job silently **re-run** — confusing for failed uploads |

**Design rule:** Queue files are **scheduling only**. Terminal state lives in **`jobs/{job_id}.json`**. Never leave failed jobs in `pending/` or `processing/`.

See also [SIMAGIX_WORKSPACE.md](SIMAGIX_WORKSPACE.md) § On-disk JSON catalog (Layer 1) and [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.4.

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

Tracks fallback tool call usage (max 12 calls per evidence-service session).

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
| `GET /simagix/runs/{run_id}/grafana/urls` | Dashboard URLs + stack health (uses cached probes during decode) |
| `GET /simagix/runs/grafana/status` | Stack health for status banner |

**Run page flow (`grafana.js`):**

1. `GET /grafana/status` — banner text (running / decode in progress / Docker down).
2. `GET /grafana/urls` — if stack healthy, show **Anomaly View** / **All Metrics** buttons with pre-built URLs.
3. **First visit this session** — silent `POST /grafana/load` unless already loaded or decode in progress (`sessionStorage`).
4. User clicks a dashboard button — one debounced `window.open` to `localhost:3030`.

**Backend (`GrafanaStackManager`):** `_HEALTH_CACHE` is module-level (not per request) so a probe timeout during FTDC decode does not make `/urls` report the stack down. See [OPERATIONS.md](OPERATIONS.md) § Grafana troubleshooting.

---

## Operator MCP connectors

Registry path: `simagix-workspace/operator/mcp_connectors/registry.json` (under `DATA_ROOT`).

```http
GET /simagix/mcp-connectors
POST /simagix/mcp-connectors
DELETE /simagix/mcp-connectors/{connector_id}
```

**POST body (HTTP):** `{"id": "remote-docs", "name": "Docs MCP", "transport": "http", "url": "https://…", "headers": {}}`

**POST body (stdio template):** `{"id": "github", "name": "GitHub", "transport": "stdio_template", "template_id": "github-mcp", "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "…"}}`

List response includes `stdio_templates[]` and locked builtin `simagix-evidence`.

**Run page:** checkboxes (no saved selection) → `enabled_mcp_ids` on Phase 2 start and clarify. Both Cursor and ADK merge selected ids via `build_mcp_server_specs`; mock ignores the field.

---

## Operator skill catalog

Storage path: `simagix-workspace/operator/skills/{slot_name}/` (under `DATA_ROOT`). Pass-through ZIP extract — no `registry.json`.

```http
GET /simagix/skills
POST /simagix/skills          # multipart: slot_name + archive (.zip)
DELETE /simagix/skills/{slot_name}
```

**No run-page checkboxes.** When the catalog is non-empty, **all** skills attach on Phase A, Phase C, and chatbot (Cursor: `scratch/.cursor/skills/`; ADK: `SkillToolset`).

---

## Phase 2 RCA endpoints

### LLM providers

```http
GET /simagix/runs/phase2/llm-providers
```

Returns `default` from `.env` and `options[]` with `id`, `label`, `available` (whether API keys are configured).

### Start RCA (Phase A+B)

```http
POST /simagix/runs/{run_id}/phase2/run
```

Body: `{"llm": "mock", "enabled_mcp_ids": ["github-prod"]}` or `{"llm_provider": "gemini"}` (required unless legacy `force_mock`). `enabled_mcp_ids` is optional — user connector ids only (built-in `simagix-evidence` is always on for Cursor). Runs tier-2 investigation into `phase2/llm/{llm}/`. Response includes resolved `llm` folder name.

### Session status

```http
GET /simagix/runs/{run_id}/phase2/status?llm=mock
```

Query `llm` is **required** (`mock` | `cursor` | `gemini`). Response includes `tool_trace_summary` (total calls and counts by category: `mcp`, `web`, `local`, `shell`).

### Agent tool trace

```http
GET /simagix/runs/{run_id}/phase2/llm
GET /simagix/runs/{run_id}/phase2/tool-trace?llm=mock
```

`llm` query param is **required** on tool-trace, status, and reports. Returns SDK `tool_call` events persisted to `simagix-workspace/runs/{run_id}/phase2/llm/{llm}/tool_trace.json`. Used by the run page **Agent Tool Activity** panel (`#tool-trace-panel`).

### Latest report

```http
GET /simagix/runs/{run_id}/phase2/reports/latest?llm=mock&format=pretty
GET /simagix/runs/{run_id}/phase2/reports/latest/view?llm=mock
```

### Hybrid anomaly correlation

```http
GET /simagix/runs/{run_id}/phase2/anomaly-correlation
```

### Final RCA (Phase C)

```http
POST /simagix/runs/{run_id}/phase2/clarify?llm=mock
```

Body: `{"answers": {"question_id": "operator answer"}, "enabled_mcp_ids": ["github-prod"]}`. Query `llm` is **required** (or legacy `llm_provider` / `force_mock`). Phase C uses **current** checkbox state from the run page, not Phase A selection.

### Post-report chatbot (Phase 3)

```http
GET /simagix/runs/{run_id}/phase2/chatbot?llm=mock
POST /simagix/runs/{run_id}/phase2/chatbot/attachments?llm=mock
POST /simagix/runs/{run_id}/phase2/chatbot/messages?llm=mock
```

Body (POST messages): `{"content": "user message", "attachments": [{"name": "notes.txt", "path": "attachments/abc_notes.txt", "size": 42}], "enabled_mcp_ids": ["github-prod"]}`. `enabled_mcp_ids` is optional — current **Chatbot-tab** MCP checkbox state (`#chatbot-mcp-run-checkboxes`); **stateless per message** (not stored in chat history). Upload files first via **multipart** `POST .../chatbot/attachments` with field `file` (`.json`, `.txt`, `.log`, `.md`, `.csv`, `.yaml`, `.yml`; max `PHASE2_CHATBOT_MAX_ATTACHMENT_BYTES`, default 512 KiB). Files land in `chatbot_scratch/attachments/`; the agent prompt lists paths for `read`/`grep`.

Returns assistant `message` + `tool_calls_used`. **404** if no `latest_report.json` for that LLM slot. History persisted to `chatbot_chat.json` (full transcript); long threads summarized into `summary_of_older` for prompt replay.

---

## Python integration example

```python
from pathlib import Path
from backend.app.simagix.evidence_service import SimagixEvidenceService

workspace = Path(".")
evidence = SimagixEvidenceService(workspace, "phase1test20260609T133314Z")

# Primary: analyzed context
context = evidence.get_prompt_context()

# Fallback: metric proof
window = evidence.get_metric_window("repl_lag_host-1", limit=50)

# Phase 2 package
package = evidence.build_phase2_llm_package()
```

---

## Backend layout

FastAPI app under `backend/app/`.

### Modules

| Module | Path | Purpose |
|--------|------|---------|
| Simagix RCA | `app/simagix/` | Bundle loader, fallback tools, evidence service |
| Phase 2 LLM | `app/simagix/llm/` | Cursor or Gemini ADK agent, MCP/evidence tools, 3-phase RCA flow |

#### Phase 2 LLM file layout (`app/simagix/llm/`)

| File / area | Cursor | Gemini ADK | Shared |
|-------------|--------|------------|--------|
| Orchestration | — | — | `service.py`, `session.py`, `prompts.py`, `parse_output.py` |
| Providers | `providers/cursor/provider.py` | `providers/adk/{provider,runner}.py` | `providers/mock.py`, `provider.py` (ABC) |
| Agent runtime | **Cursor SDK** | ADK `InMemoryRunner` | — |
| MCP layer | SDK spawns subprocesses | Native `McpToolset` via `to_adk_mcp_toolsets()` | `mcp/registry.py`, `mcp/connectors.py`, `mcp/servers/*` |
| Skill catalog | `copytree` → scratch `.cursor/skills/` + `setting_sources=["project"]` | `SkillToolset` via `load_skill_from_dir` | `skills/registry.py`, `/skill-workarea` |
| WorkArea / operator MCPs | `enabled_mcp_ids` → `build_mcp_server_specs` → SDK | Same specs → `McpToolset` | Registry + API + UI |
| Web fetch policy | `web_fetch.py` → `build_cursor_sdk_web_tools` | `web_fetch.py` callable on ADK agent | `web_fetch.py` |
| Tool audit | `tool_trace.py` | `tool_trace.py` | `tool_trace.py` |

Full layout: [PHASE2_LLM.md](PHASE2_LLM.md) § Unified MCP layout. Tradeoffs: [DESIGN_NOTES.md](DESIGN_NOTES.md) §13.18, §14.

| Hatchet tier-2 | `app/simagix/hatchet_tools.py`, `llm/mcp/servers/hatchet.py` | MCP tools over `hatchet.db` when logs were analyzed |
| Web UI | `app/web/` | Jinja2 templates, pages |
| Upload jobs | `app/jobs/` | File queue, worker, job store, catalog, retry (see below) |
| API | `app/api/` | REST routes (runs, phase2, upload, grafana) |
| Static | `frontend/static/` | Bootstrap theme CSS, RCA + Grafana client JS |

### Jobs module layout (`app/jobs/`)

| File | Role |
|------|------|
| `queue.py` | `FileJobQueue` — enqueue, claim, `complete()`, `has_active_job_for_run()` |
| `store.py` | `JobStore` — create/update/persist `phase1/jobs/{job_id}.json` + `job_status.json` |
| `worker.py` | `PipelineWorker` — poll queue, `try`/`finally` + `complete()` |
| `pipeline.py` | `run_pipeline_job()` — subprocess to Docker pipeline script |
| `hatchet.py` | `run_hatchet_job()` — Docker Hatchet + Python `summary.json` export |
| `hatchet_retry.py` | `retry_hatchet_for_run()` — re-enqueue Hatchet when logs exist |
| `catalog.py` | Run list display status (queued / processing / finished / failed / stale) |
| `retry.py` | `retry_pipeline_for_run()` — re-enqueue rules for failed/stale runs |

#### Why `retry.py` is separate from `upload.py`

| Concern | `upload.py` (API route) | `retry.py` (service) |
|---------|-------------------------|----------------------|
| Input | Multipart file stream | Existing `run_id` on disk |
| Creates | New upload folder + `run_id` | New `job_id` only; reuses `inputs/diagnostic.data/` |
| Validation | Archive format, `metrics.*` present | No export yet; no active queue; upload path exists |
| Errors | `HTTPException` from FastAPI | `PipelineRetryError` → mapped to HTTP in route |

**Reasons for a dedicated module:**

1. **Different domain action** — upload is ingest; retry is re-schedule. Mixing both in one file bloats the upload handler with 409/404 rules that do not apply to new uploads.
2. **Test without HTTP** — `test_pipeline_retry.py` calls `retry_pipeline_for_run()` directly with a temp `RunWorkspace`; no TestClient or multipart needed.
3. **Thin HTTP layer** — `POST .../retry` is ~10 lines: call service, map `PipelineRetryError` to status code.
4. **Reuse** — same function could be invoked from a CLI, admin script, or future automation without importing FastAPI.

`has_active_job_for_run()` is used **only** in `retry.py` to block double-enqueue when the user clicks Retry twice or a job is still running.

### Web UI routes

| Route | Description |
|-------|-------------|
| `GET /` | Home — recent runs and jobs |
| `GET /upload` | Upload FTDC archive |
| `GET /runs` | List analysis runs |
| `GET /runs/{run_id}` | Run detail, Grafana charts, RCA panel |

### Phase 2 persistence

```text
simagix-workspace/uploads/<run_id>/phase2/llm/{mock|cursor|gemini}/
  investigation.json, iterative_state.json, tool_trace.json,
  latest_report.json, budget_state.json, session_metadata.json,
  chatbot_chat.json, chatbot_scratch/
```

Evidence bundle: `uploads/<run_id>/phase1/mongo-ftdc/` (legacy `exports/mongo-ftdc/` still readable).

### Environment

```bash
# Provider selection (default: cursor)
export LLM_PROVIDER=cursor   # cursor | gemini | mock

# Cursor SDK (LLM_PROVIDER=cursor)
export CURSOR_API_KEY="cursor_..."

# Google ADK + AI Studio (LLM_PROVIDER=gemini)
export GOOGLE_API_KEY="..."           # https://aistudio.google.com/apikey
export GOOGLE_MODEL=gemini-2.5-flash

# Optional Graylog MCP
export GRAYLOG_API_URL="..."
export GRAYLOG_API_TOKEN="..."
```

Install LLM extras: `uv sync --extra dev --extra llm` (includes `cursor-sdk`, `google-adk`, `mcp`).

### Tests

```bash
uv run pytest backend/tests -q
```
