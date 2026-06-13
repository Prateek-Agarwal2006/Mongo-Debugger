# Changelog & improvement log

Living record of **what changed**, **how**, and **why** — for demos, handoffs, and your own memory.  
For spec scorecard and milestones, see [PROJECT_STATUS.md](PROJECT_STATUS.md). For design rationale, see [DESIGN_NOTES.md](DESIGN_NOTES.md).

**Last updated:** 2026-06-13

**Maintenance guide:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) — which docs to update for each type of change.

---

## 2026-06-13 — GitHub-ready README, gitignore, repo setup script

**What:** Proper root README, `.env.example`, `.gitignore` for local uploads/exports/repos, and `scripts/setup-simagix-repos.sh` before first GitHub push.

**How:** Expanded [README.md](../README.md) with quick start, architecture summary, and doc links; excluded ~1GB runtime data while keeping `phase1test20260609T133314Z` test fixture.

**Why:** Safe public push without secrets or machine-local FTDC blobs; onboarding for clone → install → Docker → run.

---

## 2026-06-11 — Orchestrator vs agentic AI + Cursor SDK loop in DESIGN_NOTES

**What:** Clarified that `SimagixRCAOrchestrator` is the evidence librarian (Facade), not a LangGraph-style agent orchestrator; documented how Cursor SDK runs the tool loop vs what we own in Python.

**How:** Added `docs/DESIGN_NOTES.md` §13.16–§13.17 and extended §12 code index.

**Why:** Common confusion between RCA backend “orchestration” and agentic AI orchestration; needed a durable reference before adding alternate LLM providers.

---

## 2026-06-11 — Theory Q&A in DESIGN_NOTES (no new doc)

**What:** Personal walkthrough answers (config cache, web→API flow, jobs/pipeline threading, budget vs MCP tools, prompts map, grounding) live in one place.

**How:** Extended `docs/DESIGN_NOTES.md` §13 and §12 code index; no separate `MY_UNDERSTANDING.md`.

**Why:** User already uses DESIGN_NOTES for theory/design; avoid doc sprawl.

---

## 2026-06-11 — Remove committed mongo-ftdc HTML artifact

**What:** Repo-root `html/` folder removed from version control.

**How:** Deleted stale `html/ftdc_diagnosis.html`; added `html/` to `.gitignore`. mongo-ftdc still writes there at pipeline runtime; per-run copies remain under `simagix-workspace/reports/mongo-ftdc/<run_id>/`.

**Why:** That file was generated output, not app source. The web UI serves Phase 2 reports via FastAPI (`report_html.py`), not this static file.

---

## 2026-06-11 — High-level architecture diagram + interactive canvas

**What:** Engineers get a connected end-to-end system map (upload → pipeline → bundle → run page → RCA / Grafana → reports) with zoom detail, technology stack table, and a clickable Cursor Canvas for steps 1–7.

**How:**
- `docs/ARCHITECTURE.md`: master mermaid (steps 1–7), zoom A–D, UI→API table, tech stack + layer diagram; canvas link at top of system map.
- `canvases/mongo-debugger-architecture.canvas.tsx`: SVG DAG layout, step selector, detail panels (summary, call chain, tech).
- `docs/README.md`: architecture row points to system map + canvas.

**Why:** Onboarding and demos need one story that ties UI, API, Docker, MCP, and Grafana — without reading the whole codebase.

---

## How to read this

Each entry uses:

| Field | Meaning |
|-------|---------|
| **What** | User-visible or architectural outcome |
| **How** | Code, config, or doc changes |
| **Why** | Problem solved or trade-off accepted |

---

## 2026-06-11 — Grafana load UX, tool-usage footer, SDK sandbox, debug cleanup

**What:** Full-text RCA reports show real MCP/trace counts (not “Tools used: 0”); Grafana auto-loads FTDC per run; debug session instrumentation removed; Phase 2 agent runs with sandbox enabled.

**How:**
- `tool_usage.py` + `session_metadata.tool_usage` snapshot; `format_report` footer uses trace + budget.
- `run_phase2` no longer resets investigation MCP budget; cumulative max across phases.
- Grafana: auto `POST /grafana/load` on run page, correct anomaly dashboard slug, `load.ok` validation.
- `cursor_provider`: `SandboxOptions(enabled=True)`; `cwd` scoped to export bundle; MCP-only prompt rules.
- Removed `agent_debug_log` and debug ingest calls from grafana/service/cursor paths.
- Docs: `OPERATIONS.md` (Load FTDC flow), `PHASE2_LLM.md` (rules 7–8 local vs MCP).

**Why:** Report footer read post-reset budget while trace had real calls; Grafana panels empty without per-run FTDC API load; temporary debug logs should not ship; SDK has no MCP-only flag — sandbox + docs set expectations.

---

## 2026-06-11 — Remove deterministic mock RCA; evidence-first prompts

**What:** Mock provider no longer invents mechanism narratives; live agent prompts require evidence-backed "why" reasoning.

**How:**
- Deleted `rich_rca_content.py` (keyword → mechanism templates).
- Mock provider fills `what_observed` from tier-1 facts only; `why_it_happened` / timeline `mechanism` use `[mock]` stubs.
- Split `detail_requirements.py` into FORMAT_REQUIREMENTS, EXAMPLES (non-authoritative), EVIDENCE_RULES (binding).
- Grounding rules: no keyword inference; prompt examples are not evidence.

**Why:** Deterministic mechanism text in mock risked being mistaken for product behavior and let the LLM copy templates instead of reasoning from MCP tool output.

---

## 2026-06-11 — Detailed mechanistic RCA reports (what + why)

**What:** RCA JSON and plain/HTML reports include per-finding analyses, incident timeline, and mechanism summary — not symptom-only statements like "tickets dropped."

**How:**
- Schema: `FindingAnalysis`, `TimelineEvent`; added to `InvestigationSummary` and `RCAReportDraft` (`mechanism_summary`, `finding_analyses`, `incident_timeline`).
- Prompts: `DETAIL_REQUIREMENTS` in Phase A/C; grounding rule requiring mechanism explanation.
- Reports: `format_report.py` / `report_html.py` render MECHANISM, TIMELINE, FINDING ANALYSES sections.
- Mock provider initially used keyword-based mechanism templates (later removed — see entry above).

**Why:** Users need causal explanations (cache → I/O → tickets → latency), not abbreviated symptom lists.

---

## 2026-06-11 — Grounding fixes, explicit web search, tool trace UI

**What:** Phase 2 RCA grounding aligns with investigation outputs; prompts explicitly request web search; run page shows SDK tool-call activity (MCP vs web vs local).

**How:**
- Extended `GroundingRules` (`profiler`, `log`, `operator`, `suggestion`, `web_search`) and `EvidenceCitation.source_type` (`web`, `operator`).
- `build_tier1_evidence_block()` surfaces `description`, `symptoms`, `suggestion`, `instruction`, `activity_summary`; investigate/clarify prompts no longer append RCA footer.
- Phase A/C prompts include *search the web* instructions; `InvestigationSummary.web_insights` and `RCAReportDraft.reference_urls`.
- `tool_trace.py` + `cursor_provider` capture SDK `tool_call` stream → `phase2/tool_trace.json`; `GET /phase2/tool-trace` and summary on `/phase2/status`.
- Run page: two-column RCA grid + **Agent Tool Activity** panel (`rca.js`, `app.css`).
- Mock provider populates sample web fields and trace rows for demos.

**Why:** Tier-1 suggestions and tier-2 investigation were not whitelisted for citations; RCA footer conflicted with investigate/clarify schemas; web search requires explicit prompt text in Cursor SDK; operators need visibility into whether the agent actually searched the web or only used local/MCP tools.

**Deferred:** Curated runbook MCP from PDFs → [PROJECT_STATUS.md](PROJECT_STATUS.md) future enhancements only.

---

## 2026-06-11 — Doc maintenance habit (agents + humans)

**What:** Document updates are mandatory in the same session as code changes; every doc has a clear role and change matrix.

**How:**
- Added [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) — doc roles, change matrix, session checklist, CHANGELOG template.
- Added `.cursor/rules/doc-maintenance.mdc` (`alwaysApply: true`) and root [AGENTS.md](../AGENTS.md).
- Linked maintenance guide from `README.md`, `PROJECT_STATUS.md`, and this file.

**Why:** Changelog alone is not enough — API, ops, architecture, and contract docs drift separately. A matrix + always-on rule makes “update relevant docs” automatic for Cursor agents and reviewable for humans.

---

## 2026-06-11 — Documentation consolidation

**What:** All project documentation lives under `docs/`; root and subsystem READMEs are short stubs.

**How:**
- Moved `Theory_my_understanding.md` → `DESIGN_NOTES.md`, `Mongo Debugger Docs.md` → `FTDC_REFERENCE.md`, `Previous Works.md` → `PREVIOUS_WORKS.md`, and Simagix contract/toolchain docs into `docs/`.
- Created `SIMAGIX_WORKSPACE.md`; merged backend module map into `RCA_BACKEND.md`.
- Rewrote `docs/README.md` as the single index (quick start + doc map); slimmed root `README.md`.
- Updated internal links and `backend/tests/test_simagix_rca.py` export-contract path.

**Why:** Many overlapping READMEs and scattered markdown made it unclear which doc was authoritative. One index reduces duplication; `PROJECT_STATUS` owns current status, `FTDC_REFERENCE` is explicitly historical deep-dive.

---

## 2026-06-11 — Upload UX (Mac file picker)

**What:** Users could not select FTDC archives in the upload UI — files appeared grayed out.

**How:** Removed restrictive `accept=".zip,.tar,.tar.gz,.tgz"` on the file input in `upload.html`. Upload API unchanged; archives still flattened via `rglob("metrics.*")` in `upload.py`.

**Why:** macOS file picker + strict `accept` often blocks valid `.zip` / folder selections. Let the server validate format instead of the browser filter.

---

## 2026-06-11 — Grafana & Docker errors

**What:** Grafana “Load charts” failed (black screen / 503); pipeline and upload jobs failed silently when Docker was down.

**How:**
- Documented **Colima** in quick start and operations (`colima start --cpu 4 --memory 8` before Docker workflows).
- Clearer Docker-unavailable messages in `grafana_routes.py` and `grafana.js`.
- Confirmed charts open in **new browser tabs** (`localhost:3030`), not iframe embed.

**Why:** On Mac, Docker runs via Colima — if it is not started, `docker compose` fails. Iframe Grafana was removed earlier for reliability; external tabs are the supported chart path.

---

## 2026-06-11 — Superlog research

**What:** Documented lessons from Superlog (fingerprinting, heuristic→LLM grouping, post-AI policy, cost controls) without copying their architecture.

**How:** Added [SUPERLOG_ANALYSIS.md](SUPERLOG_ANALYSIS.md) with prioritized recommendations for Mongo Debugger.

**Why:** Inform future preprocessing/post-AI improvements while keeping our tiered-bundle + MCP design.

---

## 2026-06-11 — Data hygiene

**What:** Removed fake FTDC upload directories used for testing.

**How:** Deleted stub dirs under `simagix-workspace/data/uploads/` containing 17-byte `fake-ftdc-content` files. Kept real uploads and profiler fixtures.

**Why:** Fake data cluttered the runs list and confused upload/path debugging.

---

## 2026-06-10 — Single RCA path (simplification)

**What:** One canonical 3-phase RCA flow; no parallel “quick RCA” or custom chart stack.

**How:**
- Removed single-pass sync RCA, SSE streaming endpoints, `analyze.html`, `stream_phase2`, and legacy graph API (`graphs.py`, Chart.js in reports).
- **`POST /phase2/run`** = Phase A+B (investigate + clarifying questions); **`POST /phase2/clarify`** = Phase C (final RCA); **`GET /phase2/status`** for session state.
- Merged three prompt builders into `prompts.py`; folded `iterative.py` into `service.py`.
- Simplified `run_detail.html` — one RCA panel, Grafana-only charts.

**Why:** Multiple RCA and chart paths duplicated behavior, confused the API surface, and made tests/docs drift. “One lab, one clerk, one detective” is easier to demo and maintain. See [DESIGN_NOTES.md](DESIGN_NOTES.md) §9.

---

## 2026-06-09 — Phase 2 agent (Cursor SDK + MCP)

**What:** Live agentic RCA with tier-2 evidence on demand via MCP tools.

**How:**
- `LLMProvider` abstraction; `CursorProvider` uses Cursor SDK **managed agent** (we implement MCP servers, not a custom tool loop).
- In-process `mcp_evidence_server.py` exposes same tools as REST (`get_metric_window`, etc.) with disk-backed `budget_state.json`.
- **3-phase flow:** investigation (MCP on) → clarify (MCP off, up to 10 questions) → final RCA (MCP on + operator answers).
- Fixes: `Agent.create(AgentOptions(...))` not `**kwargs`; `SendOptions(mode="agent")`; parse `result.result` for JSON output.

**Why:** Tier 1 alone is insufficient when findings are empty or correlation needs proof slices. Agent-driven tool calls keep escalation in the LLM policy layer, not hidden backend magic. Split tool budgets (`PHASE2_INVESTIGATION_MAX_TOOL_CALLS` vs `PHASE2_RCA_MAX_TOOL_CALLS`) prevent investigation from exhausting the final RCA budget.

---

## 2026-06-09 — Tiered evidence bundle (Phase 1)

**What:** Deterministic mongo-ftdc export as LLM-optimized evidence package (`v1.0.0`).

**How:**
- Docker pipeline scripts in `simagix-workspace/scripts/`; `cmd/llm-export` produces tier_1 / tier_2 / tier_3 layout.
- RCA backend loads tier_1 always; tier_2/3 only via fallback tools.
- Contract: [export_contract.md](export_contract.md); rationale: [EVIDENCE_GUIDE.md](EVIDENCE_GUIDE.md).

**Why:** Full normalized FTDC can exceed hundreds of MB — unusable in LLM context. Pre-analyzed tier_1 (~10–50 KB) plus on-demand slices is the core optimization.

---

## 2026-06-09 — Web UI & upload pipeline

**What:** End-to-end workflow: upload → background Docker pipeline → run page with Grafana + RCA.

**How:**
- `POST /simagix/uploads` → `simagix-workspace/data/uploads/<run_id>/` → `PipelineJobRunner`.
- Jinja2 UI: `/`, `/upload`, `/runs/{id}`.
- Shared Grafana stack (`run-grafana-stack.sh`, `:3030` / `:5408`); pipeline can warm Grafana after upload.

**Why:** PDF spec §4 requires a web workflow; disk-only scripts are not enough for operators.

---

## Planned (tracked, not done)

See [PROJECT_STATUS.md](PROJECT_STATUS.md) § Future enhancements:

- Single FTDC decode shared by export + Grafana (avoid double `ProcessFiles`).
- LLM model comparison on identical bundles.
- Pre-built `llm-export` Docker image.
- PDF export, Hatchet log enricher, multi-run comparison dashboard.

---

## Maintenance

Follow [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md): add a dated section here (newest first) **and** update every doc from the change matrix. Keep **PROJECT_STATUS** for spec/milestone truth; use this file for narrative and reasoning.
