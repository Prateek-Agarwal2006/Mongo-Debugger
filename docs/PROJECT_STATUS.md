# FTDC Analyzer — Project Status & Delivery Roadmap

**Reference spec:** [FTDC_Analyzer_AI_Agent_Intern_Project_final.pdf](../FTDC_Analyzer_AI_Agent_Intern_Project_final.pdf)

**Last updated:** 2026-07-16

**Improvement history:** [CHANGELOG.md](CHANGELOG.md) · **Doc update matrix:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md)

---

## Executive summary

Mongo Debugger implements an **AI-powered FTDC Analyzer** that ingests MongoDB `diagnostic.data`, runs deterministic health analysis via [simagix/mongo-ftdc](https://github.com/simagix/mongo-ftdc), and produces structured root-cause analysis through an agentic LLM layer (Cursor SDK + MCP evidence tools).

| Layer | Status |
|-------|--------|
| FTDC parsing & tiered export | **Complete** |
| RCA orchestration backend | **Complete** |
| Phase 2 agent (3-phase RCA + MCP) | **Complete** |
| Web UI (upload, runs, Grafana, RCA panel, chatbot) | **Complete** |
| Phase 3 post-report agentic chatbot | **Complete** |
| Per-LLM artifact isolation (cursor / gemini / mock) | **Complete** |
| Hybrid anomaly correlation | **Complete** |
| 3-phase iterative RCA (investigate → clarify → RCA) | **Complete** |
| Graylog MCP (PDF 3.4 Step 2) | **Complete** |
| HTML report with graph placeholders | **Complete** |

---

## Spec coverage scorecard

| PDF section | Requirement | Status | Implementation |
|-------------|-------------|--------|----------------|
| **3.1** | Upload & parse `diagnostic.data` | **Done** | `POST /simagix/uploads`, Docker pipeline |
| **3.1** | Structured metric time series | **Done** | `normalized/time_series.jsonl.gz` in export bundle |
| **3.2** | Anomaly detection | **Hybrid** | mongo-ftdc deterministic + `GET .../phase2/anomaly-correlation` |
| **3.3** | Automated graph generation | **Done** | Shared Grafana stack; Open Anomaly View / Open All Metrics (new tab) |
| **3.4 Step 1** | Iterative RCA agent | **Done** | 3-phase flow: investigation (MCP) → clarify → final RCA |
| **3.4** | Ask user all at once | **Done** | LLM-generated questions (max 10) after tier-2 investigation |
| **3.4 Step 2** | Graylog MCP | **Done** | Live Universal Search client in `graylog_client.py` |
| **3.6** | Final RCA report | **Done** | `RCAReportDraft`, pretty text, HTML view |
| **4** | End-to-end web workflow | **Done** | `/`, `/upload`, `/runs/{id}`, 3-phase RCA panel |

---

## Architecture

```text
diagnostic.data (upload or disk)
  → mongo-ftdc Docker pipeline (human report + tiered export)
  → FastAPI orchestration backend (tier_1 context + fallback tools)
  → Phase A: Investigation agent + MCP (+ optional Graylog)
  → Phase B: Clarifying questions (LLM, max 10)
  → Phase C: Final RCA agent + MCP + operator answers
  → RCAReportDraft (JSON + HTML report)
```

**Key design choice:** Deterministic mongo-ftdc findings are authoritative. The LLM interprets and correlates; it does not re-derive health scores from raw FTDC.

---

## Milestone checklist

- [x] **M0** — `docs/PROJECT_STATUS.md`, stable Phase 2 report persistence
- [x] **M1** — Upload API + background pipeline jobs
- [x] **M2** — Server-rendered UI (Jinja2 + static assets)
- [x] **M3** — Grafana charts (shared Docker stack, external dashboard links)
- [x] **M4** — Hybrid anomaly correlation endpoint
- [x] **M5** — Iterative RCA + clarifying questions (all at once)
- [x] **M6** — Graylog MCP (live client)
- [x] **M7** — HTML report view (Grafana for interactive charts)
- [x] **M8** — Tests, demo script, documentation refresh
- [x] **M9** — 3-phase iterative RCA (investigation before clarify)
- [x] **M10** — PDF 3.4 Step 2 completion (Graylog wiring)
- [x] **M11** — Docs scorecard correction

---

## How to demo

```bash
# 0. Mac: start Docker (Colima) once per session
colima start --cpu 4 --memory 8

# 1. Start backend
uv run uvicorn backend.app.main:app --reload --port 8000

# 2. Open web UI
open http://localhost:8000

# 3. Or use existing run
open http://localhost:8000/runs/phase1test20260605T071425Z

# 4. One-command demo script
./scripts/demo.sh
```

---

## API quick reference

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Web home |
| `POST /simagix/uploads` | Upload FTDC archive, start pipeline |
| `GET /simagix/uploads/jobs/{job_id}` | Pipeline job status |
| `GET /simagix/runs` | List completed export runs |
| `POST /simagix/runs/{id}/phase2/run` | Phase A+B: investigate + clarifying questions |
| `POST /simagix/runs/{id}/phase2/clarify` | Phase C: submit answers + final RCA |
| `GET /simagix/runs/{id}/phase2/status` | RCA session state |
| `GET /simagix/runs/{id}/phase2/reports/latest/view` | HTML report |

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `LLM_PROVIDER` | Phase 2 backend: `cursor` (default), `gemini`, or `mock` |
| `CURSOR_API_KEY` | Live Phase 2 agent (Cursor SDK) when `LLM_PROVIDER=cursor` |
| `CURSOR_MODEL` | Agent model (default `composer-2.5`) |
| `GOOGLE_API_KEY` | Google AI Studio key when `LLM_PROVIDER=gemini` |
| `GOOGLE_MODEL` | Gemini model for ADK (default `gemini-2.5-flash`) |
| `GOOGLE_GENAI_USE_VERTEXAI` | `true` for Vertex AI instead of AI Studio |
| `PHASE2_INVESTIGATION_MAX_TOOL_CALLS` | Investigation phase budget (default 6) |
| `PHASE2_RCA_MAX_TOOL_CALLS` | Final RCA phase budget (default 6) |
| `PHASE2_MAX_CLARIFYING_QUESTIONS` | Max operator questions (default 10) |
| `GRAYLOG_API_URL` | Graylog base URL for log MCP |
| `GRAYLOG_API_TOKEN` | Graylog API token |
| `GRAYLOG_AUTH_MODE` | `token` (Bearer) or `basic` |
| `GRAYLOG_DEFAULT_QUERY` | Default log search query |
| `GRAYLOG_SEARCH_LIMIT` | Max log messages per query |
| `GRAFANA_URL` | Grafana base URL (default `http://localhost:3030`) |
| `FTDC_API_URL` | FTDC API for chart load (default `http://localhost:5408`) |

---

## Validated runs

| Run ID | Data window | Findings |
|--------|-------------|----------|
| `phase1test20260609T133314Z` | Jun 2–3, 2026 | Replication lag, missing indexes, CPU, memory |
| `phase1test20260605T071425Z` | Jun 5–6, 2026 | Working set exceeds RAM, memory fragmentation |

---

## Future enhancements

### Trust & cost (recommended before multi-agent)

These deliver most of the **accuracy/trust** benefit of “multi-agent” without a full orchestration graph. See [SUPERLOG_ANALYSIS.md](SUPERLOG_ANALYSIS.md) §5 for prioritization rationale.

| Priority | Idea | Effort | Why |
|----------|------|--------|-----|
| 1 | **Deterministic citation verifier** — after Phase A/C, compare `RCAReportDraft` / `InvestigationSummary` claims to `tool_trace.json` (e.g. metric cited but `get_metric_window` never called) | Med | Highest trust ROI; Python-only, no second LLM |
| 2 | **Tier-1 short-circuit** — skip Phase A when tier-1 has no findings and no anomaly windows | Low | Cost; mirrors Superlog “skip LLM when heuristic suffices” |
| 3 | **Closed RCA taxonomy + confidence** — enum root-cause category + `low\|medium\|high` on verdict; UI shows low confidence as “hypothesis” | Low | Honest uncertainty; filterable reports |
| 4 | **Prompt-cache tier-1** across Phases A/B/C + token usage logging per phase | Med | Cost measurable and reducible |

### Multi-agent orchestration (mentor discussion)

**Status:** Not implemented — documented for scope/ROI discussion.

**What we have today:** Fixed **3-phase workflow** in `service.py` (investigate → clarify → human → final RCA). Each phase spawns **one** Cursor SDK agent (`Agent.create()` per phase). That is **workflow orchestration**, not dynamic multi-agent routing. `SimagixEvidenceService` is the shared evidence librarian (Facade), not an agent loop — see [DESIGN_NOTES.md](DESIGN_NOTES.md) §13.16. **Post-report chatbot, memory, and “why not LangGraph/Hindsight”** tradeoffs: [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.

**What “multi-agent orchestration” would mean:** A Python **coordinator** runs multiple **specialist agents** (investigator, metrics-only, logs-only, verifier, writer) with routing, retries, and shared state — e.g. verifier rejects unbacked claims and sends investigator back for another round.

```text
Today:     service.py → Agent A → Agent B → human → Agent C
Multi-agent: Orchestrator → Investigator → Verifier → (retry?) → Clarifier → Writer
             (+ optional parallel Metrics + Logs agents → Synthesizer)
```

**When it is justified**

| Use case | Fits Mongo Debugger? |
|----------|----------------------|
| Verify claims against tool trace (auditor agent) | **Yes** — but start with deterministic Python check (#1 above) |
| Parallel metrics + logs on huge incidents | **Maybe** — only if single investigator repeatedly misses one signal |
| Dynamic supervisor (LangGraph-style routing) | **Weak fit** — single upload, deep RCA; adds cost/latency/complexity |
| High-volume triage / cross-incident grouping | **No** — out of scope (one FTDC upload per run; see SUPERLOG §4) |

**Assessment for this project:** Full multi-agent orchestration is **likely overkill** for the current single-incident RCA use case. The product bet is **one reasoning brain per incident** plus deterministic tier-1 (SUPERLOG §4). More agents increase API cost, latency, and failure modes without clear gain if tier-1 + one investigation pass already surfaces the story.

**If we add anything multi-agent-shaped, prefer this order:**

1. **Deterministic verifier** (Python on `tool_trace.json`) — not a second agent
2. **Optional LLM verifier** (one extra MCP-OFF agent after Phase A) — only if (1) is too brittle on real runs
3. **Parallel specialists** (metrics + logs) — only with eval evidence that Phase A misses signals
4. **Dynamic supervisor graph** — defer unless requirements shift to fleet-scale triage

**Likely touch points if built:** `llm/multi_agent.py` (orchestrator loop), `output_schema.py` (`VerificationResult`), extend `iterative_state.json` + `tool_trace.json` (`agent_role`), wire from `service.py`; API can stay `POST /phase2/run` internally.

**Questions for mentor**

1. Is **trust** (citation verification) the real gap, or **coverage** (need separate metrics vs logs agents)?
2. Should verification be **deterministic** (tool trace) or **LLM auditor** (second agent)?
3. Is multi-agent worth the **demo narrative** if eval on fixture runs doesn’t show single-agent failures?
4. Any intern-scope cap (e.g. verifier only, no parallel agents)?

---

### Other future work

- **Robust retry + crash recovery (jobs)** — Today a worker that dies mid-job leaves a `PROCESSING` row until *that* pod restarts and self-requeues (`claimed_by = me`). Gaps: dead workers that never come back; no lease heartbeat; Phase 1/Hatchet retries are manual (`…/retry`). **Planned:** lease heartbeat + timeout **reaper** (stale `PROCESSING` → `PENDING`), bounded auto-retry with backoff / new `job_id` audit trail, clearer failed-vs-retryable classification. See [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) Decision 7 (accepted tradeoff) and Deferred list.
- **Worker wake-up: Postgres `LISTEN` / `NOTIFY` (replace poll loop)** — Worker today sleeps on `PIPELINE_WORKER_POLL_SECONDS` and scans `jobs`. **Planned:** `NOTIFY` on enqueue + worker `LISTEN` so claim latency drops without busy polling; keep a slow poll as safety net if a notify is missed. Same `SKIP LOCKED` claim path.
- **UI progress: SSE (replace status polling)** — Upload / pipeline / Phase 2 UIs poll `GET …/jobs/{id}` and `GET …/phase2/status`. **Planned:** Server-Sent Events (or one multiplexed SSE) for job + Phase 2 state transitions so the browser gets push updates; keep poll as fallback for proxies that buffer SSE. Complements LISTEN/NOTIFY on the worker side (DB events → API → SSE).
- **Pipeline deduplication (upload path)** — `run-mongo-ftdc-pipeline.sh` runs `run-mongo-ftdc.sh` (`simagix/ftdc` `/mftdc`) then `run-llm-export.sh`; both call `ProcessFiles` + diagnosis on the same `diagnostic.data`, roughly doubling pipeline time. **Planned:** run `llm-export` only for RCA/API (writes `exports/`), optionally emit HTML/console from the same pass or on demand; keep `simagix/ftdc` image for Grafana server mode (`-server`), not a second analysis container per upload. See [DESIGN_NOTES.md](DESIGN_NOTES.md) §8.
- **Curated runbook MCP / MCP resources** — tiered excerpts from project PDFs (`WiredTiger_read_ticket_drop_analysis.pdf`, `May_Incident_RCA.pdf`, etc.) with finding→runbook mapping; auditable offline citations that replace or supplement open web search
- **Single FTDC decode for RCA + Grafana** — today `llm-export` and `/grafana/dir` each decode `diagnostic.data`; unify in mongo-ftdc (shared cache or push stats to FTDC API once)
- **LLM model comparison** — run the same 3-phase RCA (investigation → clarify → final) across models (e.g. `composer-2.5`, Claude, GPT) on identical tier-1 bundles; compare citation quality, tool use, latency, token cost, and RCA accuracy side by side
- Pre-built `llm-export` Docker image (avoid `go run` compile on each export)
- PDF export for HTML reports
- Hatchet log enricher when MongoDB logs are available
- Multi-run comparison dashboard
