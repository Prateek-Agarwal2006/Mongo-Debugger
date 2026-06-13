# Mongo Debugger — Design Thinking (Interview / Demo Notes)

Personal reference for **why** the system is built this way — not a duplicate of `docs/ARCHITECTURE.md`. Focus: decisions that are non-obvious and worth explaining out loud.

**Last aligned with codebase:** 2026-06-11 (orchestrator vs agentic AI, Cursor SDK loop, design patterns).

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

**`LLMProvider` abstraction** — swap Cursor vs mock vs future providers without touching evidence plumbing.

---

## 6. 3-phase RCA — the impressive extension (PDF 3.4)

Single-pass “here’s your RCA” is easy to demo and easy to distrust. We split intent:

```text
Phase A — Investigation (MCP ON)
  Read tier 1 → call tier-2 tools (+ profiler + optional Graylog) → InvestigationSummary

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

**API surface (canonical, post-simplification):**

- `POST /phase2/run` — Phase A+B  
- `POST /phase2/clarify` — Phase C  
- `GET /phase2/status` — session state  

---

## 7. Multi-signal correlation — beyond FTDC

FTDC is **server metrics**, not application logs or query text.

| Signal | Source | When |
|--------|--------|------|
| Metrics & findings | mongo-ftdc bundle | Always |
| Metric slices | MCP `simagix-evidence` | Phase A & C |
| Slow queries | Uploaded `db.system.profile` JSON | Phase A (`get_profiler_samples`) |
| App/DB logs | Graylog MCP (optional) | Phase A if `GRAYLOG_*` configured |
| Charts | **Grafana** (`simagix/grafana-ftdc`) | Human exploration on run page |

**Talking point:** RCA cites **findings + metric windows + profiler + logs** where available — not a single monolithic dump.

---

## 8. Grafana: open in new tab + pipeline warmup

- **No iframe embed** — charts open at `localhost:3030` via **Open Anomaly View** / **Open All Metrics**.
- **After upload pipeline** — job warms Grafana (`POST /grafana/dir`) so you usually skip a second wait on the run page.
- **Future work** — single decode in mongo-ftdc so export and Grafana share one `ProcessFiles` pass (see `docs/PROJECT_STATUS.md`).

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
| Evidence librarian (not agent loop) | `backend/app/simagix/orchestrator.py` |
| Cursor SDK agent + MCP wiring | `backend/app/simagix/llm/cursor_provider.py` |
| 3-phase workflow orchestration | `backend/app/simagix/llm/service.py` |
| Investigation / clarify / RCA prompts | `backend/app/simagix/llm/prompts.py` |
| Tier-1 evidence block in prompts | `backend/app/simagix/prompt.py` |
| Mechanistic RCA format rules | `backend/app/simagix/llm/detail_requirements.py` |
| MCP evidence tools | `backend/app/simagix/llm/mcp_evidence_server.py` |
| Grounding rules | `backend/app/simagix/grounding.py` |
| Upload + pipeline thread | `backend/app/api/upload.py`, `backend/app/jobs/pipeline.py` |
| Job status store | `backend/app/jobs/store.py` |
| HTML pages (server-rendered) | `backend/app/web/routes.py` + `templates/` |
| Run page JS → JSON APIs | `backend/app/static/js/rca.js`, `grafana.js` |
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
GET  /simagix/runs/{run_id}/grafana/urls    → grafana.js
POST /simagix/runs/{run_id}/grafana/load   → grafana.js → opens localhost:3030 in new tab
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
- `Phase2Session` in `llm/session.py` — `run_id`, `orchestrator`, paths
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

**No extra orchestrator for the thread.** The pipeline thread only runs `subprocess` + Grafana warmup — it does **not** construct `SimagixRCAOrchestrator`.

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
simagix/           — evidence + RCA domain (bundle, tools, orchestrator, grounding)
simagix/llm/       — Phase 2 only: agent providers, prompts, MCP servers, session, parse
api/               — HTTP routers (thin)
web/               — HTML
jobs/              — upload pipeline async
```

`llm/` is not separate top-level because it **depends on** `SimagixRCAOrchestrator`, `GroundingRules`, bundle paths, and budgets. Keeping it under `simagix/` says: “LLM is a consumer of Simagix evidence, not a generic chat layer.”

---

### 13.9 `grounding.py` — why this structure

`GroundingRules` is a small class with one method `as_dict()` returning:

- `allowed_evidence_sources` — what citations may reference
- `citation_format` — `finding:…`, `metric:…`, `profiler:…`, etc.
- `score_semantics` — mongo-ftdc 0–100 scoring rules
- `rules` — anti-hallucination prose injected into Phase C prompt

**Design:** Rules live in **one Python module**, serialized to JSON in the prompt — not scattered in prompt strings. `orchestrator.build_phase2_llm_package()` attaches `grounding_rules` to the package; `prompts.py` embeds them in the final RCA message.

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

### 13.11 `get_raw_path` in orchestrator — why?

**Tier 3** forensic path: search `raw/raw_metric_values.jsonl.gz` for MongoDB metric **paths** (internal FTDC path strings), not normalized names.

Use when tier-2 normalized names aren’t enough — e.g. prove a specific internal counter path spiked. Returns small match slices (capped `limit`), never the whole gzip file.

Budget: `consume_tool_call("get_raw_path")` — same gated retrieval as tier-2 tools.

---

### 13.12 Budget — what decrements it?

`RetrievalBudget.consume_tool_call()` runs only inside **orchestrator** methods:

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
| `get_metric_window` | Yes (via orchestrator) |
| `get_normalized_series` | Yes |
| `get_raw_path` | Yes |
| `list_fallback_metrics` | **No** |
| `get_budget_status` | **No** |
| `get_profiler_samples` | **No** — calls `load_profiler_data()` directly, bypasses orchestrator budget |

So yes: MCP exposes **more tools** than the three budgeted retrieval calls. Listing metrics and reading profiler JSON are intentionally “free” (still traced in `tool_trace.json` for SDK/local/MCP activity; budget file tracks evidence retrieval caps).

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

- REST `simagix_runs.py`: new `SimagixRCAOrchestrator(workspace, run_id)` per request — stateless, cheap.
- Phase 2: one orchestrator **per run** inside `Phase2Session`, cached in `phase2_session_store`.
- MCP subprocess: one orchestrator built from env (`SIMAGIX_RUN_ID`, `SIMAGIX_BUDGET_STATE_PATH`) for that agent run.

A single global orchestrator would mix bundles and budgets across runs.

---

### 13.15 Where all prompts live

| File | What it builds |
|------|----------------|
| `simagix/prompt.py` | `build_tier1_evidence_block`, `build_phase2_prompt` — tier-1 findings/windows/activity text |
| `simagix/scoring.py` | `score_semantics_prompt_lines` — 0–100 score rules inlined in tier-1 block |
| `simagix/llm/prompts.py` | **Phase A** `build_investigate_user_message`; **Phase B** `build_clarify_user_message`; **Phase C** `build_phase2_user_message` |
| `simagix/llm/detail_requirements.py` | `DETAIL_REQUIREMENTS` — mechanistic RCA format + anti-echo rules (included in A & C) |
| `simagix/grounding.py` | `GroundingRules.as_dict()` — embedded as JSON in Phase C prompt |
| `simagix/orchestrator.py` | `build_phase2_llm_package()` — assembles prompt + grounding + schema + tool list (not prose itself) |
| `simagix/llm/mock_provider.py` | Deterministic stub text when `force_mock` (no cloud agent) |
| `simagix/llm/parse_output.py` | Post-parse lint (`warn_prompt_example_echo`) — not a prompt, guards output |

**Flow:** `service.py` calls `build_phase2_llm_package()` → provider sends user messages from `prompts.py` to Cursor agent (or mock).

---

### 13.16 `SimagixRCAOrchestrator` — not the agentic “orchestrator”

**File:** `backend/app/simagix/orchestrator.py`  
**Docstring:** “Orchestration-only RCA backend over Simagix analyzed bundles.”

This name is easy to confuse with **LangGraph / AutoGen / ReAct “orchestrator”** (the component that runs `think → act → observe` in a loop). Ours is **not** that.

| | Agentic AI “orchestrator” (theory) | `SimagixRCAOrchestrator` (this repo) |
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
mock_provider.py        → direct orchestrator calls in tests (no SDK)
```

**Who does *not* use it for the agent loop:** `cursor_provider.py` never implements ReAct — it delegates the loop to Cursor SDK. The SDK calls MCP; MCP calls orchestrator.

**Layer split (memorize this):**

```text
service.py           → workflow orchestrator (Phase A → B → C)     [Template Method]
Cursor SDK Agent     → agent runtime (tool loop, planning)         [ReAct driver — external]
SimagixRCAOrchestrator → evidence librarian (bundle + slices + budget) [Facade]
```

If renamed for clarity: `EvidenceService` or `RCABundleFacade` would match agentic terminology better; “Orchestrator” here means **orchestrating RCA backend access**, not orchestrating cognition.

**Design patterns (Refactoring.Guru):** Facade (this class), Adapter (MCP servers), Strategy (`LLMProvider`), Factory Method (`get_llm_provider`), Template Method (`service.py` phases). See §13.17 for where Cursor SDK sits.

---

### 13.17 How Cursor SDK runs Phase 2 (what we did *not* build in Python)

**We do not implement** the MCP client, JSON-RPC tool loop, or multi-turn agent state machine. **Cursor SDK** (`cursor-sdk` / `cursor_provider.py`) does.

**Our code’s job:** configure the agent once, send one user message per phase, stream messages for tracing, parse final JSON.

#### Setup (`cursor_provider.py`)

1. **`AgentOptions`** — `api_key`, `model` (`cursor_model`, default `composer-2.5`).
2. **`LocalAgentOptions(cwd=bundle_dir)`** — agent’s working directory is the **export bundle** for this run (not whole repo). Also exposes SDK built-ins (`read`, `grep`, `shell`) — prompts say to prefer MCP instead.
3. **`SandboxOptions(enabled=True)`** — restricts local agent FS/network per Cursor docs.
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
     - MCP tool → stdio to our mcp_evidence_server → orchestrator → JSON result
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
| Evidence slice logic + budget file | **Us** (orchestrator + MCP servers) |
| 3-phase workflow + human Q&A gate | **Us** (`service.py`) |
| Structured output validation | **Us** (`output_schema` + `parse_output.py`) |
| Swap Cursor for OpenAI | **Us** (`LLMProvider` — must reimplement tool loop for OpenAI) |

**Interview line:** “We built MCP **servers** and an evidence **Facade**; Cursor SDK is the managed **agent runtime** that runs the ReAct loop we deliberately didn’t duplicate in Python.”
