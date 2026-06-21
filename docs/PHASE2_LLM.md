# Phase 2 — LLM Integration

Phase 2 wires the **agentic LLM brain** on top of the deterministic mongo-ftdc evidence pipeline.

**Last updated:** 2026-06-21

**Status:** Complete (Cursor SDK **or** Gemini ADK + MCP/evidence tools + 3-phase RCA flow + live Graylog client).

## Components


| Component             | Location                                         | Status   |
| --------------------- | ------------------------------------------------ | -------- |
| Prompt builders       | `backend/app/simagix/llm/prompts.py`             | Complete |
| Cursor provider       | `backend/app/simagix/llm/cursor_provider.py`     | Complete |
| Gemini ADK provider   | `backend/app/simagix/llm/gemini_adk_provider.py` | Complete |
| ADK evidence tools    | `backend/app/simagix/llm/adk_evidence_tools.py`  | Complete |
| MCP evidence server   | `backend/app/simagix/llm/mcp_evidence_server.py` | Complete |
| Graylog client + MCP  | `graylog_client.py`, `graylog_mcp_server.py`     | Complete |
| Phase 2 orchestration | `backend/app/simagix/llm/service.py`             | Complete |
| Web fetch (shared)    | `backend/app/simagix/llm/web_fetch.py`           | Complete |
| Post-report chatbot   | `service.py` + `/phase2/chatbot` API             | Complete |

## LLM providers

Set `LLM_PROVIDER` in `.env` (see `.env.example`):

| Value | Provider | Requirements |
|-------|----------|--------------|
| `cursor` (default) | `CursorLLMProvider` | `CURSOR_API_KEY` — SDK runs tool loop + stdio MCP |
| `gemini` | `GeminiAdkLLMProvider` | `GOOGLE_API_KEY` from [AI Studio](https://aistudio.google.com/apikey) — ADK `InMemoryRunner` runs tool loop with in-process evidence function tools |
| `mock` | `MockLLMProvider` | None — deterministic, reads real bundle |

`get_llm_provider()` also falls back to mock when `LLM_PROVIDER=cursor` and no `CURSOR_API_KEY`. Pass `llm=mock` in API bodies or use `{"llm":"mock"}` on `POST .../phase2/run`.

**Per-run LLM slot:** Each run stores Phase 2 artifacts under `phase2/llm/{mock|cursor|gemini}/`. The run detail UI (`/runs/{run_id}`) uses one **LLM** dropdown (`#llm-context-select`) for both starting RCA and viewing status/trace/report for that slot. Re-running with the same LLM overwrites only that folder.

Install Gemini deps: `uv sync --extra dev --extra llm`.

## Shared vs per-LLM

| Layer | Scoped by | Notes |
|-------|-----------|-------|
| FTDC export bundle | `run_id` only | `uploads/{run_id}/phase1/evidence/` — same tier-1 data for all LLMs |
| `SimagixEvidenceService` | `(run_id, llm)` | New instance per `Phase2Session`; own `RetrievalBudget` |
| Phase 2 artifacts | `llm` | investigation, iterative_state, tool_trace, report, budget, metadata |


## 3-phase RCA flow (PDF 3.4)

```text
POST /phase2/run  (body: {"llm": "mock"} or {"llm_provider": "gemini"})
  Phase A — Investigation (MCP ON, budget: PHASE2_INVESTIGATION_MAX_TOOL_CALLS)
    → InvestigationSummary persisted to phase2/llm/{llm}/investigation.json
  Phase B — Clarify (MCP OFF, max 10 LLM questions from investigation gaps)
    → ClarifyingQuestionsBlock in phase2/llm/{llm}/iterative_state.json

POST /phase2/clarify?llm=mock
  Phase C — Final RCA (MCP ON, budget: PHASE2_RCA_MAX_TOOL_CALLS)
    → tier-1 + investigation + operator answers → RCAReportDraft

GET /phase2/status?llm=mock
  → investigation, questions, answers, status for that LLM slot
```

## Design rules

1. **Start from tier_1 analyzed evidence.** Findings are authoritative.
2. **Investigate before asking.** Tier-2 MCP (+ Graylog + profiler) runs before clarifying questions.
3. **Ask user once.** Up to 10 LLM-generated questions in a single block.
4. **Cite everything.** Final RCA cites findings, metric slices, profiler, logs, operator answers, and web sources.
5. **Web search is explicit.** The Cursor SDK does not search the internet unless the prompt says so. Phase A and Phase C prompts include *search the web* instructions; results land in `web_insights` (investigation) and `evidence_citations` / `reference_urls` (final RCA).
6. **Tool trace is ground truth.** Every SDK `tool_call` during investigation and final RCA is persisted to `phase2/llm/{llm}/tool_trace.json` and shown in the run page **Agent Tool Activity** panel. Provider-specific adapters normalize into one `ToolTraceEntry` schema (see below). A Web count of 0 means the harness did not invoke web/fetch tools.
7. **Evidence-first mechanisms.** Prompt `EXAMPLES` are non-authoritative placeholders; `EVIDENCE_RULES` forbid keyword-only inference and copying example wording. Mock provider uses `[mock]` stubs for why/mechanism fields.
8. **Local vs MCP tools.** Phase A/C and chatbot may use **read/grep/shell** for analysis; **writes only** under `phase2/llm/{llm}/chatbot_scratch/`. MCP stdio `cwd` stays workspace root; Cursor agent `cwd` for MCP-on phases is `chatbot_scratch/`.
  - **Clarify-only** runs: `cwd` = export bundle, MCP off.
  - **Investigation / final RCA / chatbot** (MCP on): agent `cwd` = `chatbot_scratch/`; bundle and session artifacts reachable by absolute paths in read/grep.
  - **MCP budget** counts simagix-evidence calls; local/shell/web appear separately in the trace UI.
9. **Post-report chatbot (Phase 3).** After `latest_report.json` exists, `GET|POST /phase2/chatbot` drives an agentic thread per `(run_id, llm)`. Full history in `chatbot_chat.json`; prompt uses report + investigation + `summary_of_older` + last N messages. Summarize runs via text-only LLM call when thread exceeds `PHASE2_CHATBOT_SUMMARIZE_AFTER_MESSAGES`. **Attachments:** `POST .../chatbot/attachments` stores files under `chatbot_scratch/attachments/` (text-friendly types, size cap).
10. **Trusted web fetch.** `web_fetch.py` validates HTTPS URLs (SSRF blocks; optional `PHASE2_WEB_ALLOWLIST_SUFFIXES`). Used by Cursor and Gemini — not mongodb-only.

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
  -H 'Content-Type: application/json' -d '{"llm": "gemini"}'

# List configured providers
curl "http://localhost:8000/simagix/runs/phase2/llm-providers"

# List per-LLM slots for a run
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/llm"

# Phase C: final RCA
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/clarify?llm=mock" \
  -H 'Content-Type: application/json' \
  -d '{"answers": {"open_q_0": "No maintenance"}}'

# Session state (requires llm)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/status?llm=mock"

# SDK tool-call trace
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/tool-trace?llm=mock"

# Latest report
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/reports/latest?llm=mock&format=pretty"

# Profiler upload (optional, before RCA)
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/profiler" \
  -H 'Content-Type: application/json' \
  -d '[{"op":"query","millis":120,"ns":"db.coll"}]'

# Post-report chatbot (requires latest_report.json)
curl "http://localhost:8000/simagix/runs/<run-id>/phase2/chatbot?llm=mock"
curl -X POST "http://localhost:8000/simagix/runs/<run-id>/phase2/chatbot/messages?llm=mock" \
  -H 'Content-Type: application/json' \
  -d '{"content": "Explain the root cause in plain language"}'
```

**Migration:** Delete legacy flat files at `phase2/*.json` (run root) and re-run RCA per LLM. No automatic migration.

## Persistence

```text
simagix-workspace/runs/<run_id>/phase2/
  llm_index.json                 # optional index of slots
  llm/
    mock/
      budget_state.json
      investigation.json
      iterative_state.json
      tool_trace.json
      latest_report.json
      session_metadata.json
      chatbot_chat.json
      chatbot_scratch/
    cursor/
      ...
    gemini/
      ...
```

FTDC bundle (`uploads/<run_id>/phase1/evidence/`) is **not** duplicated per LLM.

## Tool trace (one schema, provider adapters)

Storage and UI are shared; **recording** differs per provider:

| Provider | Recording path | Notes |
|----------|----------------|-------|
| Cursor SDK | `cursor_provider.py` → `ToolTraceCollector.record_sdk_message()` | Parses streamed `tool_call` messages; `resolve_tool_identity()` unwraps `"mcp"` payloads |
| Gemini ADK | `adk_runner.py` → `after_tool_callback` + `record_grounding_metadata` | Evidence tools as MCP; `GoogleSearchTool` + grounding metadata as **web** (`google_search`) |
| Mock | `write_mock_tool_trace()` | Deterministic demo rows |

All paths write to the same `tool_trace.json` under the active LLM folder. The API and **Agent Tool Activity** panel only read the normalized entries — no separate trace viewer per provider.

## Agent Tool Activity (UI)

On `/runs/{run_id}`, the RCA section uses a two-column grid: **Root Cause Analysis** and **Agent Tool Activity**. The panel loads `GET /phase2/tool-trace?llm=...` (selected LLM from dropdown) and shows phase, category badge (MCP / Web / Local / Shell), tool name, status, and args/result summary.

Cursor SDK records MCP calls as tool name `"mcp"` with the real tool in args (`toolName`, `providerIdentifier`). `resolve_tool_identity()` in `tool_trace.py` normalizes these to readable names like `simagix-evidence/get_metric_window`. The API also reads `tool_trace.json` from disk after server restart (session store is in-memory).

Implementation: `backend/app/simagix/llm/tool_trace.py`, `frontend/static/js/rca.js`.

## Schemas

- `InvestigationSummary` — Phase A output (`web_insights: string[]` optional URLs + takeaways)
- `ClarifyingQuestionsBlock` — Phase B output (max 10 questions)
- `RCAReportDraft` — Phase C output (`reference_urls: string[]` bibliography; `EvidenceCitation.source_type` includes `web` and `operator`)

## Grounding alignment

`GroundingRules` (`backend/app/simagix/grounding.py`) whitelists `investigation_summary`, `profiler_insights`, `log_insights`, `operator_clarifications`, `finding.suggestion`, and `web_search`. Phase-specific prompts use `build_tier1_evidence_block()` for tier-1 content; only Phase C appends the RCAReportDraft footer via `build_phase2_prompt()`.