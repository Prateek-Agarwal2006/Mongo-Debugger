# Simagix Workspace

Local workspace for running the Simagix diagnostic toolchain and producing tiered evidence bundles for the Mongo Debugger RCA backend.

**Commands and troubleshooting:** [Operations](OPERATIONS.md)  
**Tool roles and Docker scripts:** [Simagix Toolchain](SIMAGIX_TOOLCHAIN.md)  
**Bundle schema:** [Export Contract](export_contract.md)

**Last updated:** 2026-06-17

## Current status

| Component | Status |
|-----------|--------|
| mongo-ftdc Docker pipeline | Ready |
| Unified pipeline (`run_id` linking) | Ready |
| Tiered LLM export (`cmd/llm-export`) | Ready |
| RCA backend integration | Ready |
| Hatchet | Blocked — needs MongoDB logs |
| Keyhole / Maobi | Blocked — needs `MONGO_URI` and Keyhole output |

Latest validated export: `phase1test20260609T133314Z`. Full scorecard: [Project Status](PROJECT_STATUS.md).

The setup is hybrid: local repo clones for source review, Docker scripts for repeatable runs, generated data kept separate from source repos.

**Note:** upstream `mongo-ftdc` defaults to `-latest 10`. Our scripts default `MONGO_FTDC_LATEST=0` (all files).

## Cloned reference versions

| Repo | Remote | Commit |
|------|--------|--------|
| `mongo-ftdc` | `https://github.com/simagix/mongo-ftdc.git` | `66212fd` |
| `keyhole` | `https://github.com/simagix/keyhole.git` | `7d3a156` |
| `hatchet` | `https://github.com/simagix/hatchet.git` | `c109eed` |

## Three “workspace” concepts

These stack — do not confuse them:

```text
DATA_ROOT                          ← configurable mount (repo root locally, /data on K8s)
  └── simagix-workspace/           ← folder on disk (this doc)
        └── uploads/{run_id}/      ← one incident’s full lifecycle
```

| Concept | What it is |
|---------|------------|
| **`simagix-workspace/`** | Real directory: scripts, repos, `uploads/`, `reports/`. Not `backend/` or `frontend/`. |
| **`RunWorkspace`** | Python class in `backend/app/core/run_workspace.py` — maps domain terms (`run_id`, evidence, Phase 2) to concrete paths. |
| **`DATA_ROOT`** | Env/config root passed into `RunWorkspace`. Local: repo root. K8s: `/data`. API and worker **must** share the same value. |

Factory: `get_run_workspace()` → `RunWorkspace(settings.data_root or repo_root())`.

## RunWorkspace — adapter between Run and disk

**Interview line:** “`get_data_root()` answers *where*; `RunWorkspace` answers *what paths exist*.”

The rest of the app speaks in **domain terms** (upload, evidence bundle, Phase 2 session). The filesystem speaks in **paths**. `RunWorkspace` is the **adapter** — callers ask for `exports_dir(run_id)`; the module returns a `Path`.

```text
  api/upload.py          RunWorkspace              disk / PVC
  "save this upload" --> upload_diagnostic_dir(run_id) --> .../uploads/{id}/raw/diagnostic.data/
  jobs/worker.py       iter_phase1_queue_pending_paths() --> .../uploads/*/phase1/queue/pending/
  api/phase2.py        exports_dir(run_id)            --> .../uploads/{id}/phase1/evidence/
```

Constructor (stores an absolute, normalized root):

```python
def __init__(self, root: Path) -> None:
    self.root = root.resolve()
```

- **`root`** — top of the data tree (`DATA_ROOT`), *not* `simagix-workspace/` itself. All paths are built as `self.root / "simagix-workspace" / ...`.
- **`resolve()`** — makes the path **absolute**, follows **symlinks**, and normalizes `.` / `..`. Stable for `relative_to()` and for API vs worker running from different working directories.

`resolve_*` methods prefer **Option A** paths and fall back to legacy layouts (`data/uploads`, `exports/mongo-ftdc`, `runs/`) if old data still exists on disk.

More design rationale: [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.3.

## Symlinks

A **symlink** (symbolic link) is a filesystem pointer: a small file whose content is “go to that other path.” It is not a copy of the data.

| Path | Created by | Purpose |
|------|------------|---------|
| `uploads/latest` | `run-mongo-ftdc-pipeline.sh` (`ln -sfn …`) | Convenience pointer to the most recent upload dir |
| `uploads/latest_run_id.txt` | Pipeline scripts | Text file with latest `run_id` (not a symlink) |
| `uploads/latest_export_path.txt` | `run-llm-export.sh` | Text file with latest evidence dir path |

**Why the backend skips `uploads/latest`:** `iter_upload_run_dirs()` treats `latest` as a symlink and **does not** enumerate it as a separate run. Without that, the same `phase1/jobs/*.json` would be scanned twice (real folder + symlink) and the catalog could show false “(2 tries)”.

**`Path.resolve()` vs symlinks:** When `RunWorkspace` calls `root.resolve()`, symlinks in the root path are followed to the real directory. That is separate from skipping `uploads/latest` during run listing.

**Do not** commit runtime symlinks under `uploads/` except the git-tracked test fixture dir (`phase1test20260609T133314Z`).

## On-disk JSON catalog (per upload)

Each `uploads/{run_id}/` tree holds JSON in **four layers** with different writers and lifecycles.

### Layer 1 — Job orchestration (Python API + worker)

| File | Writer | Reader | Purpose |
|------|--------|--------|---------|
| `phase1/jobs/{job_id}.json` | `JobStore.persist()` | Worker, catalog, API, retry | **Source of truth** for one pipeline attempt: `state`, timestamps, message, error, `input_path` |
| `phase1/job_status.json` | Same `persist()` call | UI quick lookup | **Latest snapshot** for this upload — copy of the most recently updated job for that `run_id` |
| `phase1/queue/pending/{job_id}.json` | `FileJobQueue.enqueue()` | Worker `claim_next()` | **Work ticket:** `{ job_id, run_id, input_path }` |
| `phase1/queue/processing/{job_id}.json` | Worker (rename from `pending/`) | Crash recovery | Same payload while running; requeued to `pending/` on worker startup if stale |

Sync rules: upload creates job record + queue file together. Worker deletes queue file in `finally` after run; failed state lives only in `jobs/{job_id}.json`. **Stale** = job says `pending` but no queue file.

#### Worker `finally` and `complete()` (queue vs job JSON)

When the worker runs a job (`backend/app/jobs/worker.py`):

```python
try:
    run_pipeline_job(...)   # Docker pipeline; may succeed or fail
finally:
    queue.complete(run_id, job_id)   # always deletes processing/{job_id}.json
```

| Artifact | Role |
|----------|------|
| `queue/processing/{job_id}.json` | **Lease** — “worker holds this job right now” |
| `jobs/{job_id}.json` | **Truth** — final `succeeded` / `failed` + message + error |

**Why `finally`:** Pipeline failure must still release the lease. Without it, the UI stays on **processing**, retry gets **409** (`has_active_job_for_run`), and restart may re-run a job the user thought had failed.

**What `finally` does not fix:** `kill -9` on the worker mid-pipeline — queue file may stick until the next worker startup runs stale recovery (`processing/` → `pending/`).

Retry after failure: `POST /simagix/uploads/runs/{run_id}/retry` → `jobs/retry.py` creates a **new** `job_id` + `pending/` entry (blocked if queue already active). See [RCA_BACKEND.md](RCA_BACKEND.md) § Pipeline worker and § Why retry.py is separate.

Queue dirs are **per upload** on disk; the worker scans **all** uploads and claims the oldest pending file by mtime (one global FIFO, one worker in v1).

### Layer 2 — Pipeline bookkeeping (shell script)

| File | Writer | Purpose |
|------|--------|---------|
| `phase1/run_manifest.json` | `run-mongo-ftdc-pipeline.sh` | Ops index after export: `export_dir`, `report_dir`, pointers to bundle `manifest` and `executive_context` |

Not the same as worker job status.

### Layer 3 — Evidence bundle (`phase1/evidence/`, mongo-ftdc Go export)

Written once at end of Phase 1. **`evidence/manifest.json`** is the gate: `has_export = manifest exists`.

**Bundle metadata**

| File | Role |
|------|------|
| `manifest.json` | Authoritative bundle metadata (written atomically last) |
| `bundle_index.json` | All files with tier, size, sha256 |
| `validation.json` | Completeness checks (`valid`, `errors`, `warnings`) |
| `manifest.pre.json` | Non-authoritative checkpoint during export (optional) |

**Tier 1 — analyzed (primary RCA input)**

| File | Role |
|------|------|
| `llm/executive_context.json` | Compact LLM entrypoint |
| `diagnosis/findings.json` | Named issues, severity, suggestions |
| `diagnosis/anomaly_timeline.json` | Full anomaly event list |
| `diagnosis/activity_summary.json` | Workload profile |
| `assessment/assessment.json` | Per-metric p5/median/p95/score |
| `assessment/formulas.json` | Score formulas and thresholds |
| `diagnosis/diagnosis.json` | Optional full diagnosis engine output |

**Tier 2 — normalized (fallback tools only)**

| File | Role |
|------|------|
| `normalized/replication_lags.json`, `disk_stats.json`, `server_info.json` | Structured metric slices |
| `normalized/*.jsonl.gz` | Large time-series (gzip JSONL) |
| `metric_catalog.json` | Metric name → point counts |

**Tool retrieval**

| File | Role |
|------|------|
| `llm/fallback_retrieval_index.json` | Array of pointers (metric → source file → time window); no metric values |

Full schema: [export_contract.md](export_contract.md), [FALLBACK_INDEX.md](FALLBACK_INDEX.md).

### Layer 4 — Phase 2 LLM session (`phase2/llm/{mock|cursor|gemini}/`)

Updated incrementally by the Python RCA backend.

| File | Writer | Role |
|------|--------|------|
| `budget_state.json` | `RetrievalBudget` | Tool-call budget across restarts |
| `iterative_state.json` | `save_iterative_state()` | Workflow state (`awaiting_clarifications`, `completed`, …) |
| `investigation.json` | `persist_investigation()` | Structured investigation summary |
| `latest_report.json` | `persist_report()` | Final RCA report (`RCAReportDraft`) |
| `session_metadata.json` | `persist_report()` | Run metadata + budget + tool usage summary |
| `tool_trace.json` | `ToolTraceCollector` | Audit log of tool calls |
| `chatbot_chat.json` | Chatbot API | Follow-up Q&A transcript |

**Run-level aggregator**

| File | Writer | Role |
|------|--------|------|
| `phase2/llm_index.json` | `update_llm_index()` | Summary per LLM slot: `status`, `has_report`, `last_run_at` |

### Optional input JSON

| File | Role |
|------|------|
| `raw/profiler/system.profile.json` | Optional profiler upload for Phase 2 |

### Source-of-truth cheat sheet

| Question | Answer |
|----------|--------|
| Is Phase 1 done? | Latest job `state == succeeded` **and** `evidence/manifest.json` exists |
| Is worker actually queued? | Queue file in `pending/` or `processing/` for that job |
| Can Phase 2 start? | `evidence/manifest.json` exists |
| Is RCA done? | `phase2/llm/{provider}/latest_report.json` or `iterative_state.json` status |
| What does the LLM read first? | `executive_context.json`; tools use `fallback_retrieval_index.json` |

## Folder layout

**Option A:** one tree per upload under `uploads/{run_id}/`. Legacy `data/uploads`, `exports/mongo-ftdc`, and `runs/` are removed from disk; code still reads them if present on older machines.

```text
simagix-workspace/
  repos/                    mongo-ftdc, keyhole, hatchet (source clones)
  uploads/<run_id>/         One tree per web upload / pipeline run
    raw/
      diagnostic.data/      FTDC metrics (web upload target)
      profiler/             Optional profiler JSON (Phase 2)
    phase1/
      jobs/{job_id}.json    Phase 1 job records
      queue/pending|processing/   Per-upload worker queue
      evidence/             Tiered mongo-ftdc export bundle
      job_status.json       Latest Phase 1 job snapshot
      run_manifest.json     Pipeline manifest
    phase2/
      llm/{mock|cursor|gemini}/   RCA session artifacts
      llm_index.json
  reports/mongo-ftdc/       Human HTML + console reports
  scripts/                  Docker wrappers (pipeline, Grafana, etc.)
```

Local dev inputs (gitignored, repo root `tmp/`): `tmp/diagnostic.data`, `tmp/mongodb-logs/`, `tmp/keyhole-output/`.

Committed test fixture: `uploads/phase1test20260609T133314Z/`. All other `uploads/*` dirs are local runtime only.

## Why Docker is preferred

- Matches the Simagix documented workflow
- Avoids local Go build and Grafana dependency issues
- Repeatable report generation; same commands the backend upload job uses

Local clones remain useful for inspecting decode/assessment/diagnosis code and pinning exact versions.

## Input artifacts

### FTDC for mongo-ftdc

Default sample path for manual CLI runs (not used by web upload):

```text
tmp/diagnostic.data/
```

Web uploads land under `simagix-workspace/uploads/<run_id>/raw/diagnostic.data/`.

### Logs for Hatchet (blocked until provided)

```text
tmp/mongodb-logs/
```

Accepted: `mongod.log`, `mongod.log.gz`, `mongos.log`, `mongos.log.gz`. For self-managed MongoDB, discover path via `db.adminCommand({ getCmdLineOpts: 1 })` → `parsed.systemLog.path`. For Atlas, download logs from the Atlas UI.

### Cluster metadata for Keyhole (blocked until configured)

```bash
export MONGO_URI="mongodb+srv://user:password@cluster.example.mongodb.net/"
```

Output: `tmp/keyhole-output/` (input for Maobi).

## Pipeline scripts

| Script | Purpose |
|--------|---------|
| `run-mongo-ftdc.sh` | Human HTML + console report |
| `run-llm-export.sh` | Tiered evidence bundle |
| `run-mongo-ftdc-pipeline.sh` | Both with shared `run_id` |
| `run-grafana-stack.sh` | Grafana `:3030` + FTDC API `:5408` |

All require Docker. On Mac: `colima start --cpu 4 --memory 8` before running. See [Operations](OPERATIONS.md) for full command examples.

## Related source

| Path | Description |
|------|-------------|
| `repos/mongo-ftdc/cmd/llm-export/` | Go tiered exporter |
| `repos/mongo-ftdc/diagnosis.go` | Diagnosis engine (`DetectedAt` fix) |
| `backend/app/simagix/` | Python bundle loader and fallback tools |
