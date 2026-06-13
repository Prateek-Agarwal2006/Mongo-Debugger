# Phase 2 — LLM Integration

Phase 2 wires the **agentic LLM brain** on top of the deterministic mongo-ftdc evidence pipeline.

**Status:** Complete (Cursor SDK + MCP + 3-phase RCA flow + live Graylog client).

## Components

| Component | Location | Status |
|-----------|----------|--------|
| Prompt builders | `backend/app/simagix/llm/prompts.py` | Complete |
| Cursor provider | `backend/app/simagix/llm/cursor_provider.py` | Complete |
| MCP evidence server | `backend/app/simagix/llm/mcp_evidence_server.py` | Complete |
| Graylog client + MCP | `graylog_client.py`, `graylog_mcp_server.py` | Complete |
| Phase 2 orchestration | `backend/app/simagix/llm/service.py` | Complete |

## 3-phase RCA flow (PDF 3.4)

```text
POST /phase2/run
  Phase A — Investigation (MCP ON, budget: PHASE2_INVESTIGATION_MAX_TOOL_CALLS)
    → InvestigationSummary persisted to phase2/investigation.json
  Phase B — Clarify (MCP OFF, max 10 LLM questions from investigation gaps)
    → ClarifyingQuestionsBlock in iterative_state.json

POST /phase2/clarify
  Phase C — Final RCA (MCP ON, budget: PHASE2_RCA_MAX_TOOL_CALLS)
    → tier-1 + investigation + operator answers → RCAReportDraft

GET /phase2/status
  → investigation, questions, answers, status
```

## Design rules

1. **Start from tier_1 analyzed evidence.** Findings are authoritative.
2. **Investigate before asking.** Tier-2 MCP (+ Graylog + profiler) runs before clarifying questions.
3. **Ask user once.** Up to 10 LLM-generated questions in a single block.
4. **Cite everything.** Final RCA cites findings, metric slices, profiler, logs, operator answers, and web sources.
5. **Web search is explicit.** The Cursor SDK does not search the internet unless the prompt says so. Phase A and Phase C prompts include *search the web* instructions; results land in `web_insights` (investigation) and `evidence_citations` / `reference_urls` (final RCA).
6. **Tool trace is ground truth.** Every SDK `tool_call` during investigation and final RCA is persisted to `phase2/tool_trace.json` and shown in the run page **Agent Tool Activity** panel. A Web count of 0 means the harness did not invoke web/fetch tools.
7. **Evidence-first mechanisms.** Prompt `EXAMPLES` are non-authoritative placeholders; `EVIDENCE_RULES` forbid keyword-only inference and copying example wording. Mock provider uses `[mock]` stubs for why/mechanism fields.
8. **Local vs MCP tools.** Phase A/C prompts require **simagix-evidence MCP only** for metric/profiler data (no `read`/`grep`/`shell`). The Cursor SDK still **exposes** built-in local tools (`read`, `grep`, `shell`) when `LocalAgentOptions(cwd=...)` is set — there is no documented flag to disable them entirely. Mitigations in this repo:
   - `cwd` scoped to the run export bundle (not the whole repo).
   - `sandbox_options.enabled=True` on the local agent (restricts FS/network per [Cursor SDK docs](https://cursor.com/docs/sdk/python); does not remove read/grep/shell).
   - Prompts explicitly forbid shell and local file tools; prefer MCP budget tools for tier-2 proof.
   - **MCP budget** (`tool_trace` category `mcp`) counts only simagix-evidence calls; local/shell appear separately in the trace UI.

**Deferred (not in this iteration):** curated runbook MCP / MCP resources from project PDFs — see [PROJECT_STATUS.md](PROJECT_STATUS.md) future enhancements.

## MCP tools

**simagix-evidence:** `get_metric_window`, `get_normalized_series`, `get_raw_path`, `list_fallback_metrics`, `get_budget_status`, `get_profiler_samples`

**graylog** (optional): `query_logs_around_window` — uses Graylog Universal Search absolute API when `GRAYLOG_API_URL` + `GRAYLOG_API_TOKEN` are set.

## Graylog setup

Graylog stores **application/DB text logs** (separate from FTDC metrics). Configure:

```bash
export GRAYLOG_API_URL="https://graylog.example.com"
export GRAYLOG_API_TOKEN="your-api-token"
export GRAYLOG_AUTH_MODE="token"   # or "basic"
export GRAYLOG_DEFAULT_QUERY="source:mongod OR mongodb"
```

Without Graylog, the MCP returns `configured: false` and a mock sample for demos.

## Endpoints

```bash
# Phase A+B: investigation + clarifying questions
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/run" \
  -H 'Content-Type: application/json' -d '{"force_mock": true}'

# Phase C: final RCA
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/clarify?force_mock=true" \
  -H 'Content-Type: application/json' \
  -d '{"answers": {"open_q_0": "No maintenance"}}'

# Session state (includes tool_trace_summary)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/status"

# SDK tool-call trace (MCP, web, local, shell)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/tool-trace"

# Profiler upload (optional, before RCA)
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/profiler" \
  -H 'Content-Type: application/json' \
  -d '[{"op":"query","millis":120,"ns":"db.coll"}]'
```

## Persistence

```text
simagix-workspace/runs/<run_id>/phase2/investigation.json
simagix-workspace/runs/<run_id>/phase2/iterative_state.json
simagix-workspace/runs/<run_id>/phase2/latest_report.json
simagix-workspace/runs/<run_id>/phase2/tool_trace.json
```

## Agent Tool Activity (UI)

On `/runs/{run_id}`, the RCA section uses a two-column grid: **Root Cause Analysis** and **Agent Tool Activity**. The panel loads `GET /phase2/tool-trace` and shows phase, category badge (MCP / Web / Local / Shell), tool name, status, and args/result summary.

Implementation: `backend/app/simagix/llm/tool_trace.py`, `backend/app/static/js/rca.js`.

## Schemas

- `InvestigationSummary` — Phase A output (`web_insights: string[]` optional URLs + takeaways)
- `ClarifyingQuestionsBlock` — Phase B output (max 10 questions)
- `RCAReportDraft` — Phase C output (`reference_urls: string[]` bibliography; `EvidenceCitation.source_type` includes `web` and `operator`)

## Grounding alignment

`GroundingRules` (`backend/app/simagix/grounding.py`) whitelists `investigation_summary`, `profiler_insights`, `log_insights`, `operator_clarifications`, `finding.suggestion`, and `web_search`. Phase-specific prompts use `build_tier1_evidence_block()` for tier-1 content; only Phase C appends the RCAReportDraft footer via `build_phase2_prompt()`.
