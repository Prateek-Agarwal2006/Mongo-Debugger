# Mongo Debugger — Design Thinking (Interview / Demo Notes)

Personal reference for **why** the system is built this way — not a duplicate of `docs/ARCHITECTURE.md`. Focus: decisions that are non-obvious and worth explaining out loud.

**Last aligned with codebase:** 2026-06-29 (Stitch Modern report tab; `report-viewer--stitch` dual renderer).

---

## 1. One-sentence story

**Raw FTDC** → **mongo-ftdc** produces a **tiered evidence bundle** → **RCA backend** is the librarian (load tier 1, serve slices on demand) → **LLM Phase 2** is the detective (interpret, tool-call for proof, ask the human once, write RCA).

---

## 2. The core design bet: one reasoning brain

| Layer | Role | Reasons? |
|-------|------|----------|
| **mongo-ftdc** | Decode, score, diagnose, export | No — deterministic lab |
| **RCA backend** | Bundle loader, prompt assembly, gated tools, budget | No — clerk |
| **LLM Phase 2** | Correlate, hypothesize, cite, report | **Yes — only brain** |

**Why this impresses:** Most “AI on metrics” demos let the model re-derive health from raw time series. We **forbid** that. Findings from mongo-ftdc are authoritative; the LLM explains and proves, it doesn’t rediscover the lab work.

**Hospital analogy:** Lab (mongo-ftdc) → chart on file (tiered bundle) → clerk fetches pages (backend) → doctor diagnoses (LLM). The clerk doesn’t practice medicine; the doctor doesn’t re-run the spectrometer.

---

## 3. Evidence tiers — the “out of the box” optimization

FTDC exports can be **hundreds of MB**. Loading everything into an LLM context is impossible and wasteful.

| Tier | What | How Phase 2 uses it |
|------|------|---------------------|
| **Tier 1** | Pre-analyzed summary (~10–50 KB): findings, top anomaly windows, assessment | **Always** in every prompt — the starting truth |
| **Tier 2** | Normalized time series on disk | **Never wholesale** — MCP tools return 50–500 point **slices** (`get_metric_window`, etc.) |
| **Tier 3** | Raw forensic decoder output | Opt-in only; same slice pattern |

**Insight worth saying:** Tier 2 isn’t only “proof after the fact.” It’s for whenever tier 1 is **insufficient** — empty findings but spikes in assessment, missing correlation between two metrics, finer timing around a window.

**On the run page, “Tier: normalized”** = export manifest (`export_tier`), meaning the bundle **includes** tier-2 files for tools. That’s not the same label as “Phase A tier-2 investigation” (the agent **using** those files via MCP).

---

## 4. Empty findings — non-obvious behavior

`findings.json: []` does **not** mean “nothing wrong.”

- Tier 1 can still have **top anomaly windows**, **assessment highlights**, and **activity summary**.
- The backend **does not** auto-fetch tier 2 when findings are empty — no `if findings == []: load_metrics()`.
- **Escalation is policy in prompts + agent tool calls**, not hidden backend magic.

**Why we did it this way:** Keeps the backend honest (orchestration only). The agent must *decide* to call tools — that’s what makes Phase 2 agentic instead of a fancy template filler.

---

## 5. How we chose the LLM integration pattern

Three options we compared:

| | One-shot (tier 1 only) | **Agentic (chosen)** | Backend-orchestrated loop |
|--|------------------------|----------------------|---------------------------|
| Tool loop | None | LLM drives via MCP | Python code drives |
| Empty findings | Weak | Strong | Strong if coded |
| Cursor SDK fit | Poor | **Native** | Duplicates SDK |
| Demo depth | Shallow | **Interactive investigation** | Less visible to user |

**Chosen:** Cursor SDK + **in-process MCP evidence server** — same `SimagixFallbackTools` as REST, but budget persists across agent turns via `budget_state.json` on disk (MCP subprocess shares path through env).

**Managed agent — we did not build an MCP client.** Cursor SDK is the hosted agent runtime: it runs the tool loop (plan → call tool → read result → repeat), speaks MCP to our servers, and streams the run. We only implemented **MCP servers** (`mcp_evidence_server`, optional `graylog_mcp_server`) that expose tools. We did **not** write a custom MCP client, agent loop, or JSON-RPC plumbing — that would be Option C work or rolling our own “mini Managed Agents.”

**`LLMProvider` abstraction** — swap Cursor vs Gemini ADK vs mock without touching evidence plumbing. Both Cursor and Gemini ADK attach MCP tools via shared **`mcp/registry.py`** + MCP servers under **`mcp/servers/`** (ADK uses native **`McpToolset`**). Operator skills attach provider-natively via **`skills/registry.py`**. Same `SimagixEvidenceService` underneath. Layout: **§13.18** and [PHASE2_LLM.md](PHASE2_LLM.md) § Unified MCP layout.

---

## 6. 3-phase RCA — the impressive extension (PDF 3.4)

Single-pass “here’s your RCA” is easy to demo and easy to distrust. We split intent:

```text
Phase A — Investigation (MCP ON)
  Read tier 1 → call tier-2 tools (+ optional Graylog) → InvestigationSummary

Phase B — Clarify (MCP OFF)
  LLM generates up to 10 questions from gaps tools/metrics can’t answer
  (deployments, maintenance, RAM/cache config, etc.)

Phase C — Final RCA (MCP ON)
  tier 1 + investigation + operator answers → RCAReportDraft
```

**Why this is “out of the box”:**

1. **Investigate before bothering the human** — don’t ask ops questions the metrics could answer.
2. **Ask once** — one block of questions, not a chatty back-and-forth.
3. **Separate tool budgets** — `PHASE2_INVESTIGATION_MAX_TOOL_CALLS` (default 6) vs `PHASE2_RCA_MAX_TOOL_CALLS` (default 6), so investigation can’t burn the whole budget before final RCA.

**Post-report chatbot (light memory):** After Phase C, operators chat via `/phase2/chatbot`. Full transcript on disk (`chatbot_chat.json`); the agent prompt replays the last N messages plus a rolling `summary_of_older` (text-only summarize call). **Not** cross-run memory (no Hindsight) — mentor-style “remember this thread, not every RCA ever.” Full **why this, not that** table: **§14**.

**API surface (canonical, post-simplification):**

- `POST /phase2/run` — Phase A+B  
- `POST /phase2/clarify` — Phase C  
- `GET /phase2/status` — session state  
- `GET|POST /phase2/chatbot` — post-report agentic thread (Phase 3)  

All Phase 2 reads/writes are scoped by `?llm=` (`mock`, `cursor`, `gemini`) — separate artifacts under `phase2/llm/<slot>/`.

## 7. Multi-signal correlation — beyond FTDC

FTDC is **server metrics**, not application logs or query text.

| Signal | Source | When |
|--------|--------|------|
| Metrics & findings | mongo-ftdc bundle | Always |
| Metric slices | MCP `simagix-evidence` | Phase A & C |
| App/DB logs | Graylog MCP (optional) | Phase A if `GRAYLOG_*` configured |
| Charts | **Grafana** (`simagix/grafana-ftdc`) | Human exploration on run page |

**Talking point:** RCA cites **findings + metric windows + logs** where available — not a single monolithic dump.

---

## 8. Grafana: open in new tab + pipeline warmup

- **No iframe embed** — charts open at `localhost:3030` via **Anomaly View** / **All Metrics** (one debounced `window.open` per button click).
- **First visit per browser session** — run page silently `POST`s `/grafana/load` once so the FTDC API holds this run's `diagnostic.data`; reload skips re-decode unless the operator clicks **Load FTDC** again.
- **Reload during decode** — dashboard links stay visible: backend health cache (180s, module-level) treats recent probe success as still-up while the single-threaded FTDC API is busy; frontend shows links from `/grafana/urls` even when status text mentions decode in progress.
- **After upload pipeline** — job warms Grafana (`POST /grafana/dir`) so you may skip the wait on the run page.
- **FTDC server bootstrap** — patched `mftdc -server` starts without a directory; compose no longer requires `tmp/diagnostic.data` at boot (load is always per-run via `/grafana/dir`).
- **Stack recovery** — `ensure_stack_ready_for_load()` waits for a busy decoder before restarting FTDC; `docker compose up -d` without `--build` avoids killing Grafana on recovery.
- **Future work** — deduplicate upload pipeline: today `run-mongo-ftdc.sh` + `run-llm-export.sh` each decode/diagnose the same FTDC; target one pass for `exports/` (RCA) and shared decode for Grafana (see `docs/PROJECT_STATUS.md` § Other future work).

## 9. What we deliberately removed (shows maturity)

We **deleted parallel paths** instead of maintaining alternatives:

| Removed | Why |
|---------|-----|
| Single-pass sync RCA + SSE stream | One canonical 3-phase flow |
| Chart.js + graphs API | Grafana is the sole chart path for real FTDC dashboards |
| Three prompt files + `iterative.py` | Merged into `prompts.py` + `service.py` |

**Impress line:** “We optimized for one correct RCA path and one chart path, not feature sprawl.”

---

## 10. Five rules (updated)

1. **Analyze once upstream** — mongo-ftdc owns diagnosis rules; downstream consumes, doesn’t re-derive.
2. **Tier 1 by default** — every session starts from analyzed evidence.
3. **Tier 2 on demand** — slices only, never whole gzip files in context.
4. **Split budgets** — investigation and final RCA each get their own tool cap.
5. **Human for ops context only** — after tools have done their pass.

---

## 11. Demo talking points (30 seconds each)

1. **“Deterministic findings, probabilistic explanation.”** Rules fire in Go; the LLM narrates and correlates with citations.
2. **“Show me the investigation JSON.”** `findings_reviewed` + `metric_insights` prove tier 1 was read and tier 2 was tool-called.
3. **“Why did you ask me that?”** Clarifying questions come from `open_questions_for_operator` and investigation gaps — not a static form.
4. **“Grafana is exploration; MCP is agent evidence.”** Open Grafana in a new tab for human charts; RCA panel = structured agent flow.
5. **“Mock vs live.”** Mock is run-specific (reads real bundle); live Cursor agent is fully dynamic.

---

## 12. Where to look in code (minimal)

| Idea | Location |
|------|----------|
| Evidence librarian (not agent loop) | `backend/app/simagix/evidence_service.py` |
| Cursor SDK agent + MCP wiring | `backend/app/simagix/llm/cursor_provider.py` |
| 3-phase workflow orchestration | `backend/app/simagix/llm/service.py` |
| Investigation / clarify / RCA prompts | `backend/app/simagix/llm/prompts.py` |
| Tier-1 evidence block in prompts | `backend/app/simagix/prompt.py` |
| Mechanistic RCA format rules | `backend/app/simagix/llm/detail_requirements.py` |
| MCP evidence tools | `backend/app/simagix/llm/mcp_evidence_server.py` |
| Grounding rules | `backend/app/simagix/grounding.py` |
| Upload + pipeline thread | `backend/app/api/upload.py`, `backend/app/jobs/pipeline.py` |
| Job status store | `backend/app/jobs/store.py` |
| HTML pages (server-rendered) | `backend/app/web/routes.py` + `frontend/templates/` |
| Run page JS → JSON APIs | `frontend/static/js/rca.js`, `grafana.js`, `phase-rail.js`, `agent-chat.js` |
| Post-report chatbot | `backend/app/simagix/llm/service.py` (`post_chatbot_message`, `maybe_summarize_chatbot`) |
| Shared HTTPS fetch policy | `backend/app/simagix/llm/web_fetch.py` |
| Per-LLM paths | `backend/app/simagix/llm/llm_paths.py`, `session.py` |
| Scroll / 3D deck | `frontend/static/js/scroll-3d.js`, `scroll-3d.css`, `report-viewer.js` |
| Settings singleton | `backend/app/core/config.py` |

Full API and ops: `docs/RCA_BACKEND.md`, `docs/PHASE2_LLM.md`, `docs/PROJECT_STATUS.md`.

---

## 13. My theory — code walkthrough Q&A

Personal notes on *how the pieces connect*. Complements `ARCHITECTURE.md` (system map) with “why this file exists.”

### 13.1 `@lru_cache` on `get_settings()` (`core/config.py`)

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

**What it does:** Python’s `functools.lru_cache` memoizes the function — the **first** call reads `.env` and builds `Settings`; every later call returns the **same object** with no re-parse.

**Why:** `get_settings()` is called from Grafana, Phase 2, Cursor provider, etc. Without cache you’d reload env on every request. Settings are process-lifetime constants (API keys, tool-call caps, Grafana URLs) — safe to cache.

**Not** a data cache for runs or bundles — only configuration.

---

### 13.2 How HTML pages use our APIs

Two layers:

| Layer | Role | Talks to |
|-------|------|----------|
| **Server-rendered HTML** | `web/routes.py` builds pages with Jinja | Disk (manifest, persisted report) + in-memory `job_store` / `phase2_session_store` |
| **Browser JS on run/upload pages** | `fetch()` to JSON REST APIs | FastAPI routers under `/simagix/...` |

**Upload flow (`upload.html`):**

```text
GET  /upload              → web/routes.py → upload.html (static form)
POST /simagix/uploads     → api/upload.py → saves file, creates job, starts pipeline thread
GET  /simagix/uploads/jobs/{job_id}  → poll job state
redirect GET /runs/{run_id}  → web/routes.py → run_detail.html
```

**Run page (`run_detail.html` + JS):**

```text
GET  /runs/{run_id}       → web/routes.py loads manifest + formatted report text for initial paint
POST /simagix/runs/{run_id}/phase2/run     → rca.js — Phase A+B
POST /simagix/runs/{run_id}/phase2/clarify → rca.js — Phase C
GET  /simagix/runs/{run_id}/phase2/tool-trace → rca.js — tool activity table
GET  /simagix/runs/grafana/status          → grafana.js
GET  /simagix/runs/{run_id}/grafana/urls    → grafana.js (shows links; stack health uses cached probes)
POST /simagix/runs/{run_id}/grafana/load   → grafana.js (first visit auto-load; manual reload button)
GET  /simagix/runs/{run_id}/reports/latest/view → link in template (HTML report)
```

The browser **never** talks to Docker, Grafana, or Cursor directly — only to FastAPI `:8000`.

---

### 13.3 What `web/routes.py` does

`APIRouter` with **no prefix** — serves **HTML**, not JSON:

- `GET /` — home: recent runs + recent upload jobs
- `GET /runs` — run list
- `GET /runs/{run_id}` — run detail: reads `exports/.../manifest.json`, optionally loads persisted Phase 2 report and formats it for the page
- `GET /upload` — upload form

It does **not** run the pipeline or RCA. It’s the **view layer**: templates + a little server-side data assembly so the first paint has context before JS calls APIs.

---

### 13.4 What is a `@dataclass`?

A Python decorator that auto-generates `__init__`, `__repr__`, etc. for a class that mainly **holds data**.

Examples in this repo:

- `JobStatus` in `jobs/store.py` — `job_id`, `run_id`, `state`, `message`
- `Phase2Session` in `llm/session.py` — `run_id`, `evidence`, paths
- `RetrievalBudget` in `budget.py` — counters + history

Alternative would be a dict or Pydantic model. Dataclasses are lightweight for **in-process** job/session state; Pydantic is used where we need JSON schema validation (RCA reports, investigation).

---

### 13.5 Why `jobs/store.py` exists

Upload returns immediately (`job_id`) while the pipeline runs for minutes. Something must track:

- `pending` → `running` → `succeeded` / `failed`
- `message`, `error`, `run_id`, `input_path`

`JobStore` is an **in-memory dict** keyed by `job_id`, with a `threading.Lock` for safe updates from the pipeline thread and the main FastAPI thread.

`upload.html` polls `GET /simagix/uploads/jobs/{job_id}` until done.

`persist()` writes `simagix-workspace/runs/{run_id}/job_status.json` for debugging — the live source of truth during upload is memory.

**Why not skip it?** Without a job store you’d block the HTTP request for the whole Docker pipeline (bad UX) or have no way to poll progress.

---

### 13.6 `pipeline.py` — background work (threading, not multiprocessing)

```text
upload API thread          pipeline daemon thread
     |                              |
     | start(job)                   |
     |----------------------------->| subprocess.run(run-mongo-ftdc-pipeline.sh)
     |                              | job_store.update(...)
     |                              | warm_grafana_for_run(...)
     |<----- poll job status -------|
```

**Design choice:** `threading.Thread(daemon=True)` + `subprocess.run` for the shell script.

- **Not multiprocessing** — we don’t spawn a second Python interpreter. One thread waits on the external bash/Docker pipeline.
- **Why a thread:** FastAPI must return the upload response immediately; pipeline is I/O-bound (Docker, disk).
- **Daemon thread:** won’t block process exit if the server stops (job may be cut mid-run).

**Impressive part:** same process serves the UI while pipeline + optional Grafana warmup run concurrently; status flows through `job_store`.

---

### 13.7 Does threading need a different orchestrator? Thread per run_id?

**No extra evidence service for the thread.** The pipeline thread only runs `subprocess` + Grafana warmup — it does **not** construct `SimagixEvidenceService`.

**One daemon thread per upload job** (named `pipeline-{run_id}`), not a global pool. Multiple uploads → multiple threads, each with its own `job_id` / `run_id`.

**Where `run_id` is created** — `api/upload.py`:

```python
def _new_run_id() -> str:
    return f"upload{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
```

Passed to `job_store.create(run_id, ...)` and `MONGO_FTDC_RUN_ID` env for the shell script so exports land in `exports/mongo-ftdc/{run_id}/`.

**Orchestrator** appears later when someone hits REST tools or Phase 2 — scoped to that `run_id`, cached per run in `Phase2SessionStore` for RCA.

---

### 13.8 Why `simagix/llm/` lives under `simagix/`

Folder layout mirrors responsibility:

```text
simagix/           — evidence + RCA domain (bundle, tools, evidence service, grounding)
simagix/llm/       — Phase 2 only: agent providers, prompts, MCP servers, session, parse
api/               — HTTP routers (thin)
web/               — HTML
jobs/              — upload pipeline async
```

`llm/` is not separate top-level because it **depends on** `SimagixEvidenceService`, `GroundingRules`, bundle paths, and budgets. Keeping it under `simagix/` says: “LLM is a consumer of Simagix evidence, not a generic chat layer.”

---

### 13.9 `grounding.py` — why this structure

`GroundingRules` is a small class with one method `as_dict()` returning:

- `allowed_evidence_sources` — what citations may reference
- `citation_format` — `finding:…`, `metric:…`, `log:…`, etc.
- `score_semantics` — mongo-ftdc 0–100 scoring rules
- `rules` — anti-hallucination prose injected into Phase C prompt

**Design:** Rules live in **one Python module**, serialized to JSON in the prompt — not scattered in prompt strings. `evidence.build_phase2_llm_package()` attaches `grounding_rules` to the package; `prompts.py` embeds them in the final RCA message.

Easy to demo: “Here’s the contract the model must obey.”

---

### 13.10 `fallback_tools.py` — why only `replication_lags` and `disk_stats` branches?

mongo-ftdc exports tier-2 data in **three shapes**:

| `source` in index | File | Shape |
|-------------------|------|--------|
| `time_series` | `normalized/time_series.jsonl.gz` | One JSON line per metric (default) |
| `replication_lags` | `normalized/replication_lags.json` | Host-keyed object, not line-oriented |
| `disk_stats` | `normalized/disk_stats.json` | Nested disk → field → datapoints |

`get_metric_window` reads `fallback_retrieval_index.json`, then:

- `replication_lags` → `_slice_replication_lag`
- `disk_stats` → `_slice_disk_metric`
- **everything else** → `_slice_time_series`

Most metrics are in the gzip line file — special cases are **file layout**, not special metrics. See `docs/FALLBACK_INDEX.md` for how the exporter sets `source`.

---

### 13.11 `get_raw_path` in evidence service — why?

**Tier 3** forensic path: search `raw/raw_metric_values.jsonl.gz` for MongoDB metric **paths** (internal FTDC path strings), not normalized names.

Use when tier-2 normalized names aren’t enough — e.g. prove a specific internal counter path spiked. Returns small match slices (capped `limit`), never the whole gzip file.

Budget: `consume_tool_call("get_raw_path")` — same gated retrieval as tier-2 tools.

---

### 13.12 Budget — what decrements it?

`RetrievalBudget.consume_tool_call()` runs only inside **evidence service** methods:

| Orchestrator method | Budget? |
|---------------------|---------|
| `get_metric_window` | Yes |
| `get_normalized_series` | Yes (once per call, even though it loops metrics internally) |
| `get_raw_path` | Yes |
| `list_fallback_metrics` | **No** |
| `get_budget_status` | **No** |
| `load_tier1` / `get_prompt_context` | **No** (not tool retrieval) |

**MCP surface vs budget:**

| MCP tool (`mcp_evidence_server.py`) | Hits budget? |
|-------------------------------------|--------------|
| `get_metric_window` | Yes (via evidence service) |
| `get_normalized_series` | Yes |
| `get_raw_path` | Yes |
| `list_fallback_metrics` | **No** |
| `get_budget_status` | **No** |

Listing metrics is intentionally “free” (still traced in `tool_trace.json` for SDK/local/MCP activity; budget file tracks evidence retrieval caps).

**Cursor SDK built-ins** (`read`, `grep`, `shell`, `web`) are **not** in `budget_state.json` — they appear in **Agent Tool Activity** (`tool_trace.json`). Prompts discourage local/shell in favor of MCP.

---

### 13.13 What is `@property`?

Python decorator for **computed attributes** on a class — call like a field, no `()`.

In `Phase2Session`:

```python
@property
def report_path(self) -> Path:
    return self.session_dir / "latest_report.json"
```

Keeps path logic in one place; callers use `session.report_path` instead of repeating string joins. Same for `budget_state_path`, `investigation_path`, `tool_trace_path`.

---

### 13.14 Orchestrator per `run_id` — not one global singleton

See §2 in this doc. Short version:

- REST `simagix_runs.py`: new `SimagixEvidenceService(workspace, run_id)` per request — stateless, cheap.
- Phase 2: one evidence service **per run** inside `Phase2Session`, cached in `phase2_session_store`.
- MCP subprocess: one evidence service built from env (`SIMAGIX_RUN_ID`, `SIMAGIX_BUDGET_STATE_PATH`) for that agent run.

A single global evidence service would mix bundles and budgets across runs.

---

### 13.15 Where all prompts live

| File | What it builds |
|------|----------------|
| `simagix/prompt.py` | `build_tier1_evidence_block`, `build_phase2_prompt` — tier-1 findings/windows/activity text |
| `simagix/scoring.py` | `score_semantics_prompt_lines` — 0–100 score rules inlined in tier-1 block |
| `simagix/llm/prompts.py` | **Phase A** `build_investigate_user_message` (+ full `retrievable_metrics` list); **Phase B** `build_clarify_user_message`; **Phase C** `build_phase2_user_message` |
| `simagix/llm/detail_requirements.py` | `DETAIL_REQUIREMENTS` — mechanistic RCA format + anti-echo rules (included in A & C) |
| `simagix/grounding.py` | `GroundingRules.as_dict()` — embedded as JSON in Phase C prompt |
| `simagix/evidence_service.py` | `build_phase2_llm_package()` — assembles prompt + grounding + schema + tool list (not prose itself) |
| `simagix/llm/mock_provider.py` | Deterministic stub text when `force_mock` (no cloud agent) |
| `simagix/llm/parse_output.py` | Post-parse lint (`warn_prompt_example_echo`) — not a prompt, guards output |

**Flow:** `service.py` calls `build_phase2_llm_package()` → provider sends user messages from `prompts.py` to Cursor agent (or mock).

---

### 13.16 `SimagixEvidenceService` — not the agentic “orchestrator”

**File:** `backend/app/simagix/evidence_service.py`  
**Former name:** `SimagixRCAOrchestrator` (`orchestrator.py`, removed 2026-06-11)

This name is easy to confuse with **LangGraph / AutoGen / ReAct “orchestrator”** (the component that runs `think → act → observe` in a loop). Ours is **not** that.

| | Agentic AI “orchestrator” (theory) | `SimagixEvidenceService` (this repo) |
|--|-----------------------------------|--------------------------------------|
| Calls the LLM repeatedly | Yes | **No** |
| Chooses next tool / next step | Yes | **No** |
| Manages agent termination | Yes | **No** |
| Loads tier-1 evidence | Sometimes via tools | **Yes** (`load_tier1`, `get_prompt_context`) |
| Serves metric/log slices | Via tool handlers | **Yes** (`get_metric_window`, …) |
| Enforces retrieval budget | Sometimes | **Yes** (`RetrievalBudget.consume_tool_call`) |
| Builds prompt package for Phase 2 | Rarely | **Yes** (`build_phase2_llm_package`) |

**What it actually is:** a [**Facade**](https://refactoring.guru/design-patterns/facade) over `SimagixBundleLoader` + `SimagixFallbackTools` + `RetrievalBudget` — the **evidence clerk** from §2.

**Who calls it:**

```text
service.py              → build_phase2_llm_package() before each LLM phase
mcp_evidence_server.py  → same tool methods when Cursor agent requests evidence
simagix_runs.py         → REST debug API for humans/scripts
mock_provider.py        → direct evidence-service calls in tests (no SDK)
```

**Who does *not* use it for the agent loop:** `cursor_provider.py` never implements ReAct — it delegates the loop to Cursor SDK. The SDK calls MCP; MCP calls evidence service.

**Layer split (memorize this):**

```text
service.py              → workflow orchestrator (Phase A → B → C)     [Template Method]
Cursor SDK Agent        → agent runtime (tool loop, planning)         [ReAct driver — external]
SimagixEvidenceService  → evidence librarian (bundle + slices + budget) [Facade]
```

Renamed from `SimagixRCAOrchestrator` because “orchestrator” implied cognition loop; **evidence service** matches agentic terminology.

**Future work — multi-agent orchestration:** Full specialist-agent graphs are scoped as **likely overkill** for single-incident RCA; recommended incremental path (deterministic verifier → optional LLM auditor) and mentor discussion questions are in [PROJECT_STATUS.md](PROJECT_STATUS.md) § Future enhancements.

**Design patterns (Refactoring.Guru):** Facade (this class), Adapter (MCP servers), Strategy (`LLMProvider`), Factory Method (`get_llm_provider`), Template Method (`service.py` phases). See §13.17 for where Cursor SDK sits.

---

### 13.17 How Cursor SDK runs Phase 2 (what we did *not* build in Python)

**We do not implement** the MCP client, JSON-RPC tool loop, or multi-turn agent state machine. **Cursor SDK** (`cursor-sdk` / `cursor_provider.py`) does.

**Our code’s job:** configure the agent once, send one user message per phase, stream messages for tracing, parse final JSON.

#### Setup (`cursor_provider.py`)

1. **`AgentOptions`** — `api_key`, `model` (`cursor_model`, default `composer-2.5`).
2. **`LocalAgentOptions(cwd=…)`** — agent built-in `cwd` is **`chatbot_scratch/`** when MCP is on (Phases A/C/chatbot), **export bundle** when MCP is off (Phase B clarify). See [PHASE2_LLM.md](PHASE2_LLM.md) § Mentor Q&A — Cursor SDK agent runtime.
3. **`SandboxOptions(enabled=not include_mcp)`** + **`auto_review=True` when MCP on** — sandbox off for MCP phases so headless runs can read bundle paths and execute MCP; sandbox on for clarify-only.
4. **`mcp_servers`** — dict of **`StdioMcpServerConfig`**: spawn subprocesses that speak MCP over stdin/stdout:
   - `simagix-evidence` → `python -m backend.app.simagix.llm.mcp_evidence_server` with env `SIMAGIX_RUN_ID`, `SIMAGIX_WORKSPACE_ROOT`, `SIMAGIX_BUDGET_STATE_PATH`
   - `graylog` (optional) → `graylog_mcp_server` when `GRAYLOG_*` set
5. **Phase B:** `include_mcp=False` → empty `mcp_servers` — clarify pass is text-only JSON.

#### One agent run (`_run_agent_text` / `run`)

```text
with Agent.create(options) as agent:
    session.agent_id = agent.agent_id
    run = agent.send(user_message, SendOptions(mode="agent"))
    for message in run.messages():
        tool_trace.record_sdk_message(message, phase)   # our audit log
        collect assistant text chunks
    result = run.wait()
```

**Inside Cursor (conceptual — not our source code):**

```text
1. SDK sends prompt + tool schemas to Cursor agent runtime (cloud/local bridge)
2. Model may reply with text OR tool_call(s)
3. SDK executes tool_call:
     - MCP tool → stdio to our mcp_evidence_server → evidence service → JSON result
     - built-in read/grep/web → SDK local executor (sandboxed)
4. Tool results fed back to model
5. Repeat until model stops calling tools and returns final text
6. run.wait() completes; result.result holds summary text
```

That repeat loop is **ReAct / agent executor** — same *role* as LangGraph’s tool node, but implemented inside Cursor.

#### After the SDK returns

| Step | Our code |
|------|----------|
| Parse JSON from fences | `parse_investigation_summary` / `parse_clarifying_questions` / `parse_rca_report` |
| Refresh budget from disk | `session.refresh_budget()` — MCP subprocess wrote `budget_state.json` |
| Persist | `session.persist_investigation` / `persist_report` |
| Tool audit | `tool_trace.json` via `ToolTraceCollector` |

#### Three SDK invocations per full RCA (not one long chat)

| Phase | SDK calls | MCP | Output schema |
|-------|-----------|-----|---------------|
| A Investigation | `run_investigation` → `_run_agent_text` | ON | `InvestigationSummary` |
| B Clarify | `generate_clarifying_questions` → `_run_agent_text` | OFF | `ClarifyingQuestionsBlock` |
| C Final RCA | `run` → `_run_agent_text` | ON | `RCAReportDraft` |

`service.py` stitches phases and human answers — the SDK does **not** remember Phase A when Phase C runs unless we **embed** investigation + answers in the Phase C prompt (`build_phase2_user_message`).

#### What the SDK does vs what we do (checklist)

| Concern | Owner |
|---------|--------|
| Tool loop until done | **Cursor SDK** |
| MCP protocol / subprocess lifecycle | **Cursor SDK** |
| Evidence slice logic + budget file | **Us** (evidence service + MCP servers) |
| 3-phase workflow + human Q&A gate | **Us** (`service.py`) |
| Structured output validation | **Us** (`output_schema` + `parse_output.py`) |
| Swap Cursor for OpenAI | **Us** (`LLMProvider` — must reimplement tool loop for OpenAI) |

**Interview line:** “We built MCP **servers** and an evidence **Facade**; Cursor SDK is the managed **agent runtime** that runs the ReAct loop we deliberately didn’t duplicate in Python.”

---

### 13.18 How Gemini ADK runs Phase 2 (parallel to §13.17)

**Gemini ADK** (`providers/adk/`) runs the tool loop in-process via **Google ADK** `InMemoryRunner`, but evidence tools come from the **same MCP subprocess servers** as Cursor — attached via native **`McpToolset`** (`to_adk_mcp_toolsets`).

**Our code's job:** build MCP specs from `build_mcp_server_specs()`, open sessions in the ADK runner, configure `Agent(tools=...)`, record tool trace via `after_tool_callback`, parse final JSON — same *outputs* as Cursor, shared *tool attachment*.

#### File roles

| File | Role | Cursor Equivalent |
|------|------|-------------------|
| `providers/adk/provider.py` | `LLMProvider` — phases A/C/chatbot; parse JSON | `providers/cursor/provider.py` |
| `providers/adk/runner.py` | Native `McpToolset` + optional `SkillToolset` + ADK runner + trace callback | Cursor SDK `Agent.create` / `send` / `wait` |
| `mcp/servers/*.py` | `@mcp.tool()` definitions (stdio subprocess) | Same modules (SDK spawns them) |
| `mcp/registry.py` | `build_mcp_server_specs()`, `to_adk_mcp_toolsets()`, `to_cursor_sdk_servers()` | Same registry |
| `skills/registry.py` | Operator skill catalog; Cursor copytree + ADK `SkillToolset` | `setting_sources=["project"]` + `.cursor/skills/` |

Legacy import shims removed; use `providers/` and `mcp/servers/` directly.

#### Setup (`providers/adk/runner.py`)

1. **`build_mcp_server_specs(session, settings, enabled_mcp_ids=...)`** — built-ins + WorkArea connectors (same as Cursor).
2. **`to_adk_mcp_toolsets(specs)`** + optional **`build_adk_skill_toolset_all(workspace)`** + **`web_fetch`**.
3. **`Agent(..., tools=..., after_tool_callback=...)`** — ADK agent.
4. **`InMemoryRunner.run_debug(...)`** — model + tool loop (AI Studio API key).
5. **`await toolset.close()`** in `finally` — MCP + skill toolsets.
6. **`session.refresh_budget()`** — budget updated via MCP evidence subprocess writing `budget_state.json`.

#### One agent run (conceptual)

```text
run_adk_agent_text(..., enabled_mcp_ids=[...])
  → specs = build_mcp_server_specs(...)
  → tools = [*to_adk_mcp_toolsets(specs), skill_toolset?, web_fetch]
  → Agent(..., tools=tools, after_tool_callback=trace)
  → InMemoryRunner.run_debug(...)
  → close toolsets in finally
  → parse_investigation_summary / parse_rca_report / …
```

#### MCP WorkArea

| Concern | Cursor | Gemini ADK |
|---------|--------|------------|
| Operator registry + checkboxes | `enabled_mcp_ids` → `build_mcp_server_specs` → SDK | Same specs → `McpToolset` |
| Operator skill catalog | `copytree` → scratch `.cursor/skills/` | `SkillToolset(all)` — no checkboxes |
| Evidence tools | MCP `simagix-evidence` subprocess | Same subprocess via MCP client |
| Graylog | Optional MCP server | Same |
| External GitHub/HTTP MCP | WorkArea registry | Same |

#### What ADK does vs what we do (checklist)

| Concern | Owner |
|---------|--------|
| Tool loop until done | **Google ADK** (`InMemoryRunner`) |
| MCP protocol / subprocess lifecycle | **ADK `McpToolset`** for Gemini; **Cursor SDK** for Cursor |
| Evidence slice logic + budget | **Us** (`SimagixEvidenceService` + MCP servers) |
| 3-phase workflow + human Q&A gate | **Us** (`service.py`) |
| Structured output validation | **Us** (`parse_output.py`) |
| WorkArea operator MCPs | **Both providers** via `enabled_mcp_ids` |

**Interview line:** "One MCP server tree; Cursor SDK and ADK `McpToolset` are two adapters. WorkArea MCP checkboxes feed the same registry builder; Skill WorkArea attaches all skills automatically."

---

## 14. Architecture tradeoffs — mentor Q&A (“why this, not that?”)

**Purpose:** Single place for scope and design debates — **no separate `MY_UNDERSTANDING.md` or `DESIGN_DILEMMAS.md`**. When a manager asks “why didn’t you use X?”, answer from here (and link to code). For future-work items, see [PROJECT_STATUS.md](PROJECT_STATUS.md) § Future enhancements.

**Maintenance habit:** Same session as any architecture decision — add or update a row in the table below (template and checklist in [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) § “§14 tradeoff habit”). Agents enforce via `.cursor/rules/doc-maintenance.mdc` step 5.

| Topic | What we chose | Why | Why not the alternative | Code / config |
|-------|---------------|-----|-------------------------|---------------|
| **MongoDB profiler (`db.system.profile`)** | **Removed** — no upload API, MCP tool, schema field, or prompt mentions | Profiler caused Gemini hard-fails when MCP failed; out of scope vs FTDC + Hatchet logs | **Profiler upload + `get_profiler_samples`** — extra operator step; brittle when tool not registered | Profiler code deleted 2026-06-29; `parse_output.py` strips legacy `profiler_insights` |
| **Agent tool loop** | **Cursor SDK** (and Gemini **ADK** for the `gemini` slot) runs ReAct; we implement MCP **servers** + evidence Facade only | Avoid duplicating JSON-RPC tool loop, subprocess lifecycle, and sandbox in Python; swap providers via `LLMProvider` | **LangGraph / custom ReAct in Python** — more control but high build cost; we’d re-own what Cursor/ADK already ship | `cursor_provider.py`, `gemini_adk_provider.py`, §13.16–§13.17 |
| **Workflow shape** | Fixed **3-phase** template in `service.py` (A investigate → B clarify once → C final RCA) | Predictable ops flow, separate tool budgets, human gate only after tools run | **Open-ended chat RCA** or **dynamic supervisor** — harder to demo, budget blow-ups, unclear “done” | `service.py`, `PHASE2_*_MAX_TOOL_CALLS` |
| **Multi-agent orchestration** | **Not built** — one reasoning brain per incident per phase | Single upload, deep RCA; tier-1 + one investigation pass usually enough | **Parallel specialist agents + verifier graph** — cost/latency; defer unless eval shows single-agent misses signals | [PROJECT_STATUS.md](PROJECT_STATUS.md) § Multi-agent; prefer **deterministic verifier** first |
| **Phase-to-phase memory (A→C)** | **Prompt assembly** — investigation JSON + operator answers embedded in Phase C user message; no shared agent session across phases | Each phase is a fresh SDK/ADK run with a bounded prompt; auditable artifacts on disk | **One long agent thread** across A/B/C — context creep, harder to parse structured outputs per phase | `prompts.py`, `build_phase2_user_message`, §13.17 table |
| **Post-report chatbot memory** | **Light in-thread memory:** full transcript in `chatbot_chat.json`; prompt gets report + investigation + `summary_of_older` + last **N** messages (`PHASE2_CHATBOT_MAX_REPLAY_MESSAGES`); fold older turns via **text-only summarize** when count exceeds `PHASE2_CHATBOT_SUMMARIZE_AFTER_MESSAGES` | Operators can dig deeper after Phase C without shipping a memory product; cheap, inspectable JSON on disk | **Hindsight / Mem0 / vector DB / LangGraph checkpointer** — cross-run or semantic memory is out of scope for one FTDC incident; adds infra and retrieval quality risk | `service.py` (`load_chatbot`, `maybe_summarize_chatbot`), `chatbot_chat.json` |
| **Cross-run / fleet memory** | **None** — each `(run_id, llm)` is isolated | RCA is per upload; conflating incidents would confuse citations | **Global memory store** — wrong trust model for forensic RCA | `phase2/llm/<slot>/`, `llm_index.json` |
| **Web research tool** | Shared **`web_fetch`** — SSRF-safe HTTPS, size/timeout caps (`PHASE2_WEB_FETCH_*`) for Cursor + Gemini | One policy, one audit category (`web` in tool trace), operator-trustable allowlist behavior | **Gemini `GoogleSearchTool` only** — provider-specific, harder to align with Cursor; removed from ADK tool list | `web_fetch.py` |
| **Operator skill catalog** | **Skill WorkArea** — ZIP upload by slot name; attach **entire catalog** on every tool phase; Cursor `copytree` + `setting_sources=["project"]`; ADK `SkillToolset` | Skills are playbooks, not MCP tools; provider-native attachment avoids prompt injection | **Prompt injection**; **run-page skill checkboxes** for attach-all policy | `skills/registry.py`, `/skill-workarea` |
| **ADK MCP attachment** | Native **`McpToolset`** via `to_adk_mcp_toolsets()`; **`mcp/client.py` deleted** | ADK owns MCP lifecycle; same specs as Cursor | **Custom `ClientSessionGroup` bridge** — duplicate lifecycle glue | `mcp/registry.py`, `providers/adk/runner.py` |
| **Operator MCP connectors** | Disk registry + **MCP WorkArea** UI; **stateless** run-page checkboxes → `enabled_mcp_ids` on Phase A/C for **both** Cursor and ADK via `build_mcp_server_specs` | Operators attach GitHub/HTTP MCPs without code changes; explicit opt-in per run; `simagix-evidence` always locked on | **Saved defaults / env-only MCP list** — hides what ran; **free-form stdio commands** — unsafe; **Cursor-only WorkArea** — ADK could not use operator MCPs | `mcp/connectors.py`, `mcp/registry.py`, `api/mcp_connectors.py`, `/mcp-workarea` |
| **ADK in-process evidence tools (v1, superseded)** | Was **`adk_evidence_tools.py`**; **file deleted** — ADK uses shared MCP servers | Faster local dev before unify | **Permanent duplicate** vs `@mcp.tool` servers | `mcp/servers/` |
| **Provider file split (Cursor vs ADK)** | **`providers/cursor`**, **`providers/adk`**, **`providers/mock`**; shared **`mcp/`** tree | Names layers; ADK runner testable without JSON parse; one registry for all providers | **Flat llm/*.py forever** — harder navigation as providers grow | `providers/`, `mcp/`, §13.18 |
| **Unified MCP tool surface** | **`mcp/servers/*.py`** as single `@mcp.tool` source; **`mcp/registry.py`** + native **`McpToolset`** for ADK; Cursor SDK as client; **`adk_evidence_tools` deleted** | WorkArea + graylog + hatchet parity across providers; one place to add tools; OpenAI slot can reuse registry | **Keep ADK in-process forever** — duplicate tool surfaces; **per-provider tool modules** — drift | `mcp/`, `providers/`, [PHASE2_LLM.md](PHASE2_LLM.md) § Unified MCP layout |
| **Agent filesystem writes** | **Writes only under** `chatbot_scratch/` per LLM slot; reads/grep/shell allowed more broadly with prompts steering toward evidence | Scratch notes and small artifacts without polluting bundle or repo | **Unrestricted write** — risk to export bundle integrity and git workspace | `session.ensure_chatbot_scratch_dir()`, `prompts.py` `SCRATCH_RULES` |
| **LLM slots** | **`mock` / `cursor` / `gemini`** with separate `phase2/llm/<slot>/` trees | Compare providers on same run without overwriting investigation/report/trace | **Single shared phase2 folder** — switching LLM corrupted state (fixed 2026-06) | `llm_paths.py`, `test_llm_isolation.py` |
| **UI layer** | Top-level **`frontend/`** (templates + static); backend wires routes only | Reskin or replace UI without touching Phase 2 logic | **Templates under `backend/app/`** — coupled deploy story | `frontend/`, `web/routes.py` |
| **Phase A→B→C rail (UI)** | Client state machine in `phase-rail.js`, hydrated from `GET /phase2/status`; sticky shell **hides on scroll** while reading report/chat | Progress feedback during RCA; rail gets out of the way when reading long content | **Always-visible sticky bar** — blocks report/chat (user feedback); **server-driven SSE rail** — unnecessary for three discrete phases | `phase-rail.js`, `rca.js` `setFromApiStatus` |
| **RCA reading surface (UI)** | Scoped **`.reading-surface`** on report + chatbot only; warm light/dark toggle (`reading-surface.js`); Source Serif report prose; amber accents inside surface | Claude-like reading without reskinning uploads/Grafana/rail; operator picks light cream or warm dark | **Global Claude reskin** — breaks Mongo brand on ops pages; **light-only** — jarring on dark chrome; **no toggle** — mentor/demo preference varies | `reading-surface.css`, `reading-surface.js`, `run_detail.html` `#reading-surface` |
| **Modern report tab (Stitch)** | **`report-viewer--stitch`** in `run_workspace.html` iframe; `buildReportDomStitch()` + `report-viewer-stitch.css`; Classic theme keeps `rv-*` renderer | Stitch design (side nav, Lora body, confidence ring, dark log blocks) without replacing classic Bootstrap run page | **One global report CSS** — breaks classic glass/dark deck; **duplicate HTML in stitch page** — drifts from JSON renderer | `report-viewer.js`, `report-viewer-stitch.css`, `stitch/run_workspace.html` |
| **Modern results page integration** | Bootstrap **`ResultsPage`** React component in the modern shell via `run_detail.html` body class and JSON page data blocks; custom SVG lines/sparklines for FTDC metrics | Seamless modern/classic UI transition based on theme selection; high-performance responsive charting without heavy library dependencies | **Full client-side router takeover** — breaks FastAPI routes; **Heavy charting libraries (Recharts/Chart.js)** — bundle bloat | `ResultsPage.tsx`, `run_detail.html`, `App.tsx` |
| **Charting** | **Grafana** (external tab) for human exploration; MCP slices for agent evidence | Real FTDC dashboards from `simagix/grafana-ftdc`; patched `mongo-debugger/ftdc:local` defers FTDC load to `/grafana/dir` (no `tmp/` bootstrap) | **Embedded Chart.js / graphs API** — removed as duplicate path | §8, `grafana/service.py`, `patches/mftdc-server-deferred-load.patch` |
| **Grafana health during FTDC decode** | **Module-level probe cache** (180s TTL) on `:5408` / `:3030`; run-page **sessionStorage** guards auto-load | FTDC API is single-threaded — probes time out mid-decode; per-request manager had empty cache so reload hid links and stacked loads | **Per-instance cache** (never shared across requests); **hide links when probe fails**; **auto-load on every page open** | `stack.py` `_HEALTH_CACHE`, `grafana.js` `_wasLoadedThisSession` / `_loadInProgress` |
| **Citation trust (future)** | Documented preference: **deterministic verifier** on `tool_trace.json` before any **LLM auditor agent** | Highest ROI for “prove the agent looked” without second agent cost | **Verifier-only LLM** as first step — slower, still probabilistic | [PROJECT_STATUS.md](PROJECT_STATUS.md) § Trust & cost |
| **Run-scoped paths (K8s prep)** | **`RunWorkspace`** — one module: configurable root + named path methods (`uploads_dir`, `exports_dir`, `phase2_dir`, …) | Fixes K8s `DATA_ROOT` *and* removes duplicated layout strings; routes express intent; tests inject a temp-dir workspace | **Minimal `get_data_root()` only** — fixes mount root but leaves `"simagix-workspace/exports/mongo-ftdc"` copy-pasted in 5+ files | `backend/app/core/run_workspace.py`, `get_run_workspace()`; `DATA_ROOT` in `config.py`; all backend callers migrated (2026-06-18) |
| **Upload folder layout (Option A)** | **One tree per upload:** `uploads/{run_id}/inputs`, `phase1/mongo-ftdc`, `phase2/` (LLM) | Single PVC subtree; tool-named Phase 1 outputs; `inputs/` avoids clash with bundle tier-3 `raw/` | **Scattered layout** (`data/uploads`, global queue, `exports/mongo-ftdc`) or **generic `evidence/` + run `raw/`** — ambiguous before Hatchet | `run_workspace.py`; pipeline scripts; `SIMAGIX_WORKSPACE.md` |
| **Pipeline jobs (K8s prep)** | **Standalone worker** + **file queue** on `DATA_ROOT`; atomic rename claim; crash recovery requeues `processing/` → `pending/` | Upload survives API restart; worker survives pod restart; same PVC as RunWorkspace; no Redis in v1 | **Daemon thread in API** — lost on pod death; in-memory `JobStore` only; **embedded worker in FastAPI** — duplicate entrypoints | `jobs/worker.py`, `jobs/queue.py`, `jobs/pipeline.py`; `PIPELINE_WORKER_POLL_SECONDS`; **1 worker replica** in v1 |
| **Queue placement (v1)** | **Per-upload queue dirs** under `uploads/{run_id}/phase1/queue/`; worker scans all uploads and claims oldest by mtime | Option A cohesion (queue lives with jobs/evidence); `has_active_job_for_run()` is O(1) per run; worker behavior is already one global FIFO | **Single central dir** (`data/job_queue/` or `uploads/_queue/`) — simpler scan, but splits scheduling from incident tree; revisit when scaling **>1 worker** or adding Redis/SQS | `queue.py` `iter_phase1_queue_pending_paths()`; `claim_next()` mtime sort; legacy global queue read-only |
| **Hatchet MCP tier-2 tools (v2)** | Separate `hatchet-evidence` MCP server + ADK tools when summary+db exist; shared retrieval budget | Agent pulls deeper log slices on demand without bloating tier-1 prompt | **Embed in simagix-evidence server** — mixed concerns; **no budget** — unbounded SQLite reads | `hatchet_tools.py`, `hatchet_mcp_server.py`, `cursor_provider._mcp_config` |
| **Hatchet log evidence (v1)** | Optional second upload to `inputs/mongodb-logs/`; enqueue `job_type: "hatchet"` on the existing queue; mongo-ftdc uses `job_type: "mongo_ftdc"`; one Hatchet job parses + exports summary-only tier 1; Phase 2 waits for Hatchet when logs exist | Uses Hatchet's SQLite source of truth directly like mongo-ftdc; keeps logs optional; one FIFO worker model; compact tier 1 includes slow-op rankings, COLLSCAN, audit rollups, drivers, log snippets, connection timeline | **Hatchet web service / HTML** — unused wrappers; **Hatchet MCP in v1** — defer to v2; **separate queue** — duplicate semantics; **`pipeline` job type** — misleading | `backend/app/jobs/hatchet.py`, `hatchet_export.py`, `POST …/logs`, `run-hatchet-job.sh`; patch: `hatchet-merge-drop-gate.patch` |

**Talking points (Cursor vs ADK layout):** Cursor looks like one file because the SDK owns ReAct + MCP client; ADK splits into provider / runner / in-process tools because nothing is outsourced. Same ~700 vs ~430 lines of responsibility — ADK just names it. WorkArea is Cursor-only in v1 because connectors are MCP-server configs, not ADK callables.

**Talking points (MCP client):** MCP client only when the tool is an external MCP server (WorkArea GitHub/HTTP). In-process `AdkEvidenceTools` skips MCP because `SimagixEvidenceService` is already in the same Python process. Future unify: one `@mcp.tool` server list + shared client for ADK/OpenAI; Cursor SDK stays the client for the cursor slot.

**Talking points (Hatchet retry):** Upload/retry calls `clear_hatchet_artifacts()` — deletes `hatchet.db*` before enqueue so each parse starts fresh. Reusing a half-written DB from killed Docker runs caused multi-GB WAL and `SQLITE_BUSY`. Only one worker + one Hatchet container per run until single-flight guard lands.

**Talking points (Hatchet export schema):** Hatchet 7.x `merge_clients` has `ip`/`accepted`/`ended` but no `date`; export uses `PRAGMA table_info` and falls back to per-IP rollups instead of minute buckets.

**Talking points (Grafana reload / health cache):** Each API request constructs a fresh `GrafanaStackManager`. A per-instance health cache never survives to the next request, so decode-time probe timeouts looked like “stack down” and the run page hid dashboard links. Fix: module-level `_HEALTH_CACHE` shared across managers (180s). Frontend: first visit auto-loads FTDC once per session; reload uses `sessionStorage` to skip duplicate `/grafana/load`. Open buttons use debounced `window.open`, not `<a target=_blank>`.
| **Hatchet `-merge` drop gate (local patch)** | **`shouldDropHatchetBeforeBegin()`** — skip `Drop()` when `-merge` && `mergeMarker > 1`; build **`mongo-debugger/hatchet:local`** | Restores documented `-merge` behavior with per-file markers; file 1 still replaces stale merged hatchet | **Always drop in Begin** (upstream fd28370) — last file wins; **concat single file** — no markers; **fork on GitHub** — repos gitignored, patch tracked in-tree | `simagix-workspace/patches/hatchet-merge-drop-gate.patch`; `build-hatchet-local.sh`; `SIMAGIX_TOOLCHAIN.md` |

### 14.4 Pipeline worker — file queue, not upload thread

**Status:** **Implemented** — upload enqueues; `python -m backend.app.jobs.worker` consumes queue.

**Problem before:** `PipelineJobRunner.start()` spawned a **daemon thread** in the API process. `JobStore` was mostly **in-memory**. Pod restart → thread gone, status gone, upload stuck with no retry.

**What we chose:**

```text
API                          Worker (separate process)
 |                                |
 save upload                     poll pending/
 enqueue pending/{id}.json  -->  claim (rename → processing/)
 persist uploads/{run_id}/phase1/jobs/{id}.json   run_pipeline_job(subprocess)
 return job_id                    complete (unlink processing/)
```

**PVC / local:** No special queue code for K8s. Both processes set the same `DATA_ROOT` (repo root locally, `/data` PVC in cluster). Queue files live under `{DATA_ROOT}/simagix-workspace/uploads/{run_id}/phase1/queue/` (legacy global queue under `data/job_queue/` is read-only fallback).

**Crash recovery (demo sound bite):** On worker startup, move every `processing/*.json` back to `pending/`. Assumes the previous worker crashed mid-pipeline; re-run is safe because work is keyed by `run_id`.

**Claim = lock (v1):** `Path.replace()` from `pending/` to `processing/` is atomic on one filesystem. That is the job lock when **exactly one worker** polls the queue.

**Multi-worker (future — document, not v1):** Two workers can race on the same `pending/` file before rename. Options if scaling workers:

| Option | Notes |
|--------|--------|
| `fcntl.flock` / `portalocker` on pending file during claim | Works on POSIX shared volume; test NFS storage class |
| Stale lease in `processing/` (`worker_id`, `claimed_at`) | Extends crash recovery |
| Redis / SQS / Hatchet | Broker queue with visibility timeout |
| One K8s Job per upload | Different architecture (no shared consumer) |

**Interview line:** “RunWorkspace is where artifacts live; the pipeline worker is who runs long work — upload enqueues, worker claims from disk, PVC keeps both alive across restarts.”

#### Talking points (low-level — mentor / demo)

Capture these when explaining the worker in reviews; full habit: [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) § Low-level concept notes and § In-flight tradeoffs.

**`job_id` vs `run_id` (both required in the model, not always in every function arg):**

| ID | Role |
|----|------|
| **`run_id`** | Domain incident — upload folder, exports, Phase 2, `MONGO_FTDC_RUN_ID` |
| **`job_id`** | Unique async task (UUID) — poll `GET /jobs/{job_id}`, queue filename |

**Multiple jobs per run:** Same `run_id`, different `job_id` (retry / reprocess). **`run_id` lives in `JobStore`** (`uploads/{run_id}/phase1/jobs/{job_id}.json`); callers can pass **`job_id` only** and load `run_id` + `input_path` from disk. Queue JSON currently **denormalizes** `run_id` + `input_path` to avoid a second read on claim (see below).

**Worker loop (not event-driven):** Upload writes a file; worker **polls** `pending/` every `PIPELINE_WORKER_POLL_SECONDS` (default 2s). No HTTP callback from API → worker.

**Claim “lock”:** No `threading.Lock` on claim — **`Path.replace(pending → processing)`** is atomic on one filesystem (the lock). v1: **one worker replica**.

**Crash recovery:** Worker startup moves `processing/` → `pending/` (previous pod died mid-run; safe to retry — work keyed by `run_id`).

**Failed job vs queue:** On pipeline failure the worker still runs `complete()` in a `finally` block — the queue file is deleted. `state: failed` lives only in `uploads/{run_id}/phase1/jobs/{job_id}.json`. **`pending` without a queue file** → catalog status **stale** (“Not enqueued”). Manual retry via `POST .../runs/{run_id}/retry` creates a **new** job and `pending/` entry; 409 only if that run already has something in `pending/` or `processing/`.

**Python `finally` (implications if omitted):**

| Exit path | Without `finally` + `complete()` |
|-----------|----------------------------------|
| Pipeline returns failure | `processing/` stuck → UI “processing”; retry **409** |
| Exception / timeout in worker | Same ghost lease |
| Pipeline success | Usually OK if `complete()` only after success — but any missed branch leaves stuck jobs |

`finally` guarantees **one cleanup site** for all exit paths. Queue = scheduling lease; job JSON = outcome.

**Why `retry.py` is not in `upload.py`:** Upload = multipart ingest + new `run_id`. Retry = re-schedule existing upload (new `job_id`, same FTDC on disk) with different guards (no export, no active queue). Separate module keeps routes thin, tests direct (`test_pipeline_retry.py`), and allows non-HTTP callers. HTTP mapping stays in `api/upload.py` only.

**“Extra load” (queue denormalization vs single source of truth):**

| Approach | Reads on claim | Tradeoff |
|----------|----------------|----------|
| Queue file includes `run_id` + `input_path` | **1** (queue JSON only) | Duplicate fields vs `JobStore` |
| Queue file = `job_id` only | **2** (queue + `data/jobs/{id}.json`) | One source of truth; extra read is ~ms vs **minutes** of pipeline |

**Target refactor (when touching queue):** queue holds **`job_id` only**; worker loads `JobStatus` before `run_pipeline_job(workspace_root, job_id)`.

**Decisions logged during implementation (examples):**

| Decision | Chose | Over | Why |
|----------|-------|------|-----|
| Worker deployment | Standalone process only | Embedded thread in FastAPI | One code path; matches K8s API + worker pods; no duplicate entrypoints |
| Job claim lock | Atomic `Path.replace` | `threading.Lock` / Redis | Same-filesystem rename is enough for **1 worker replica**; no broker in v1 |
| Queue payload | Denormalize `run_id` + `input_path` | `job_id` only (see target refactor) | One disk read on claim; negligible vs pipeline runtime |
| Status source of truth | `data/jobs/{job_id}.json` + RAM cache | RAM only | API and worker are separate processes; PVC survives restart |
| Failed job vs queue | `complete()` always unlinks `processing/`; failed state only in job JSON | Leave failed jobs in `pending/` | Queue is work-only; terminal failures must not block FIFO or retries |
| Pipeline retry | New `job_id` + new `pending/` entry; same `run_id` + upload path | Re-upload archive; reuse same `job_id` | Upload already on PVC; audit trail per attempt; poll new job after retry |
| Retry service location | `jobs/retry.py` + thin route in `upload.py` | All logic in `upload.py` | Different validation and test surface; upload stays file-ingest only | `retry.py`, `test_pipeline_retry.py`, `has_active_job_for_run()` |

See also [ARCHITECTURE.md](ARCHITECTURE.md) § Pipeline worker, [OPERATIONS.md](OPERATIONS.md) § Starting the RCA backend.

### 14.3 RunWorkspace — why full module, not just `get_data_root()`

**Status:** **Implemented** — `RunWorkspace` + `get_run_workspace()`; all backend modules use named path methods; `_workspace_root()` removed from `backend/app/`.

**Problem before RunWorkspace:** Every HTTP handler and several services discovered disk layout themselves:

1. **Root discovery** — `_workspace_root()` uses `Path(__file__).resolve().parents[3]` (copy-pasted in five modules). That finds the **git repo root**, not a configurable `DATA_ROOT=/data` on Kubernetes.
2. **Layout strings** — paths like `"simagix-workspace/exports/mongo-ftdc/{run_id}"` are built inline in `upload.py`, `simagix_runs.py`, `evidence_service.py`, `grafana/service.py`, `web/routes.py`, etc. Phase 2 is partly centralized in `llm_paths.py`, but callers still pass `workspace_root` everywhere.

**Two separate problems:**

| Problem | Question it answers |
|---------|-------------------|
| **Where is the root?** | Repo checkout locally vs PVC mount `/data` in K8s |
| **What paths exist under the root?** | Uploads vs exports vs Phase 2 vs job state |

A minimal fix — replace `_workspace_root()` with `get_data_root()` from config — solves **only the first row**. We are implementing **RunWorkspace** to solve **both**.

#### Minimal `get_data_root()` vs `RunWorkspace`

| Problem | Minimal `get_data_root()` | **RunWorkspace** (what we chose) |
|---------|---------------------------|--------------------------------|
| Root is `/data` in K8s | Fixed | Fixed |
| `"simagix-workspace/exports/mongo-ftdc"` in 5+ files | Still duplicated | One method: `exports_dir(run_id)` |
| Typo / layout change (e.g. drop `simagix-workspace/` prefix) | Edit many files | Edit one module |
| Route says *what* it needs | Must know folder names | `uploads_dir(run_id)` — intent only |
| Tests | Patch `get_data_root` in several places | Pass a fake `RunWorkspace` with `tmp_path` root |

**Interview line:** “`get_data_root()` answers *where*; `RunWorkspace` answers *what paths exist* — we need both, so we ship one module.”

#### Why this is an Adapter (and how Strategy fits later)

**Adapter (GoF):** The rest of the app speaks in **domain terms** (Run, Evidence bundle, Phase 2 session). The filesystem speaks in **paths** (`/data/simagix-workspace/exports/mongo-ftdc/abc123`). **RunWorkspace** is the adapter between them — callers ask for `exports_dir(run_id)`; the adapter translates to concrete `Path` objects.

```
  api/upload.py          RunWorkspace              disk / PVC
  "save this upload" --> upload_diagnostic_dir(run_id) --> .../uploads/{id}/inputs/diagnostic.data/
  api/phase2.py        mongo_ftdc_dir(run_id)      --> .../uploads/{id}/phase1/mongo-ftdc/
  jobs/worker.py       iter_phase1_queue_pending_paths() --> .../uploads/*/phase1/queue/pending/
```

Without the adapter, every caller duplicates the translation (today’s `_workspace_root()` + string concat).

Constructor stores an absolute root: `self.root = root.resolve()` — see [SIMAGIX_WORKSPACE.md](SIMAGIX_WORKSPACE.md) § RunWorkspace.

**Strategy (related, not the same layer):** When we add **object storage** (S3) later, the *interface* might be `ArtifactStore` or a protocol with `read_bytes` / `write_bytes`. **RunWorkspace** stays the **filesystem** adapter for path-shaped operations; a **Strategy** picks filesystem vs S3 at startup (`STORAGE_BACKEND=filesystem|s3`). RunWorkspace is the first filesystem implementation of the path seam — not the whole storage story.

| Pattern | Role here |
|---------|-----------|
| **Adapter** | RunWorkspace maps domain nouns → filesystem paths |
| **Strategy** (later) | Config chooses filesystem workspace vs object-storage backend for blobs |
| **Not “just a helper”** | One function `get_data_root()` is a helper; a module with named methods is a deliberate **seam** (see `/codebase-design`: one adapter = hypothetical seam, two = real) |

#### Planned interface (sketch)

```python
# backend/app/core/run_workspace.py (planned)
class RunWorkspace:
    def __init__(self, root: Path): ...

    def uploads_dir(self, run_id: str) -> Path: ...
    def exports_dir(self, run_id: str) -> Path: ...      # Evidence bundle
    def phase2_dir(self, run_id: str) -> Path: ...
    def llm_session_dir(self, run_id: str, llm: str) -> Path: ...
    def job_status_path(self, run_id: str) -> Path: ...
```

Factory: `get_run_workspace()` reads `DATA_ROOT` from `config.py` (default: repo root locally, `/data` in container). `llm_paths.py` either moves into this module or delegates to it.

#### Current code pointers (before refactor)

| Artifact | Today |
|----------|--------|
| Upload path | `api/upload.py` — `workspace / "simagix-workspace/data/uploads" / run_id / "diagnostic.data"` |
| Evidence bundle | `evidence_service.py` — `workspace_root / "simagix-workspace/exports/mongo-ftdc" / run_id` |
| List runs | `simagix_runs.py` + `web/routes.py` — duplicate scan of exports dir |
| Phase 2 | `llm_paths.py` — `phase2_root_dir`, `llm_session_dir` (partial fix) |

See also [ARCHITECTURE.md](ARCHITECTURE.md) § RunWorkspace.

### 14.1 Sound bites for a manager

1. **“We didn’t skip memory — we scoped it.”** Chatbot remembers **this thread on disk**, not every RCA the company ever ran.
2. **“LangGraph would be orchestration sugar on top of a workflow we already encoded in `service.py`.”** We’d still need the same prompts, schemas, and MCP servers.
3. **“The SDK is the agent runtime; we’re the evidence and workflow layer.”** That’s the intern-project sweet spot: integrate, don’t rebuild OpenAI’s tool loop.
4. **“Per-LLM folders are like git worktrees for experiments.”** Mock vs Cursor vs Gemini on the same FTDC upload without cross-contamination.
5. **“RunWorkspace is the adapter between Run and disk.”** Routes ask for `exports_dir(run_id)`; they don’t hardcode `simagix-workspace/exports/...`.
6. **“Upload enqueues; the worker claims from disk.”** PVC + `DATA_ROOT` keep the queue across pod restarts; startup requeue handles crash recovery.
7. **“job_id is the task ticket; run_id is the incident folder.”** Same run can have many jobs; store holds `run_id` — pass `job_id` through the worker.
8. **“The claim lock is a rename, not a mutex.”** `pending/` → `processing/` is atomic on the shared volume.

### 14.2 When to revisit a decision

| Signal | Consider |
|--------|----------|
| Eval shows Phase A repeatedly misses logs **and** metrics | Parallel specialist agents (see PROJECT_STATUS) |
| Chat threads routinely exceed summarize threshold with quality loss | Tune `PHASE2_CHATBOT_*` or add retrieval over `chatbot_chat.json` (still not cross-run) |
| Product scope becomes **fleet triage** across many runs | LangGraph-style supervisor + shared index — **new project phase**, not a quick add-on |
