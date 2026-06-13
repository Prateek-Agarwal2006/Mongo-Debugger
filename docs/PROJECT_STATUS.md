# FTDC Analyzer — Project Status & Delivery Roadmap

**Reference spec:** [FTDC_Analyzer_AI_Agent_Intern_Project_final.pdf](../FTDC_Analyzer_AI_Agent_Intern_Project_final.pdf)

**Last updated:** 2026-06-11

**Improvement history:** [CHANGELOG.md](CHANGELOG.md) · **Doc update matrix:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md)

---

## Executive summary

Mongo Debugger implements an **AI-powered FTDC Analyzer** that ingests MongoDB `diagnostic.data`, runs deterministic health analysis via [simagix/mongo-ftdc](https://github.com/simagix/mongo-ftdc), and produces structured root-cause analysis through an agentic LLM layer (Cursor SDK + MCP evidence tools).

| Layer | Status |
|-------|--------|
| FTDC parsing & tiered export | **Complete** |
| RCA orchestration backend | **Complete** |
| Phase 2 agent (3-phase RCA + MCP) | **Complete** |
| Web UI (upload, runs, Grafana, RCA panel) | **Complete** |
| Hybrid anomaly correlation | **Complete** |
| 3-phase iterative RCA (investigate → clarify → RCA) | **Complete** |
| Graylog MCP + profiler ingestion (PDF 3.4 Step 2) | **Complete** |
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
| **3.4 Step 2** | Profiler data | **Done** | Upload API + `get_profiler_samples` wired in investigation |
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
- [x] **M6** — Graylog MCP (live client) + profiler upload/MCP tool
- [x] **M7** — HTML report view (Grafana for interactive charts)
- [x] **M8** — Tests, demo script, documentation refresh
- [x] **M9** — 3-phase iterative RCA (investigation before clarify)
- [x] **M10** — PDF 3.4 Step 2 completion (Graylog + profiler wiring)
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
| `POST /simagix/runs/{id}/phase2/profiler` | Upload profiler JSON |
| `GET /simagix/runs/{id}/phase2/reports/latest/view` | HTML report |

---

## Environment variables

| Variable | Purpose |
|----------|---------|
| `CURSOR_API_KEY` | Live Phase 2 agent (Cursor SDK) |
| `CURSOR_MODEL` | Agent model (default `composer-2.5`) |
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

- **Curated runbook MCP / MCP resources** — tiered excerpts from project PDFs (`WiredTiger_read_ticket_drop_analysis.pdf`, `May_Incident_RCA.pdf`, etc.) with finding→runbook mapping; auditable offline citations that replace or supplement open web search
- **Single FTDC decode for RCA + Grafana** — today `llm-export` and `/grafana/dir` each decode `diagnostic.data`; unify in mongo-ftdc (shared cache or push stats to FTDC API once)
- **LLM model comparison** — run the same 3-phase RCA (investigation → clarify → final) across models (e.g. `composer-2.5`, Claude, GPT) on identical tier-1 bundles; compare citation quality, tool use, latency, token cost, and RCA accuracy side by side
- Pre-built `llm-export` Docker image (avoid `go run` compile on each export)
- PDF export for HTML reports
- Hatchet log enricher when MongoDB logs are available
- Multi-run comparison dashboard
