# Changelog & improvement log

Living record of **what changed**, **how**, and **why** — for demos, handoffs, and your own memory.  
For spec scorecard and milestones, see [PROJECT_STATUS.md](PROJECT_STATUS.md). For design rationale, see [DESIGN_NOTES.md](DESIGN_NOTES.md).

**Last updated:** 2026-06-16

**Maintenance guide:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) — which docs to update for each type of change.

---

## 2026-06-16 — Agent Tool Activity horizontal scroll

**What:** Agent Tool Activity table scrolls horizontally so long tool args/results are readable.

**How:** Removed `max-width`/ellipsis on `.trace-args`; table uses `width: max-content`; flex column chain gets `min-width: 0` and `overflow: auto` on `.tool-trace-scroll`.

**Why:** Args were clipped at 200px with no way to pan sideways in the panel.

---

## 2026-06-16 — Phase rail scroll fade

**What:** A→B→C phase rail fades out when scrolling down; reappears when scrolling up or near the top.

**How:** Sticky `#phase-rail-shell` slides up with `translateY` on wheel/scroll (including chat + tool-trace panels); cache-bust `phase-rail.js?v=2`.

**Why:** Sticky rail blocked reading long reports and chat threads.

---

## 2026-06-16 — Chatbot markdown rendering + copy

**What:** Assistant replies render as formatted markdown (tables, headings, lists, code); each reply has a **Copy** button (ChatGPT-style).

**How:** `marked` + `mermaid` on run detail page; GFM table styles and scrollable table wrapper in `clarify-chat.css`; clipboard copy in `agent-chat.js`.

**Why:** Long agentic answers were unreadable as plain text with `<br>` only.

---

## 2026-06-16 — Chatbot generating indicator

**What:** Post-report chatbot shows “Generating…” with a spinner while the agent reply is in flight.

**How:** Optimistic user bubble + loading assistant bubble in `agent-chat.js`; spinner styles in `clarify-chat.css`; submit button shows a small spinner when busy.

**Why:** Agentic replies can take several seconds — users need visible feedback that work is in progress.

---

## 2026-06-16 — Phase 3 agentic chatbot + expanded agent tools

**What:** Post-report **chatbot** (agentic per message, disk transcript, summarize/replay memory), trusted HTTPS **web_fetch** for all LLM slots, and relaxed **read/grep/shell** (writes only under `chatbot_scratch/`).

**How:**
- Renamed `cursor_web_tools.py` → `web_fetch.py` — shared SSRF policy + fetch for Cursor and Gemini.
- Phase A/C prompts + Cursor `cwd` → `chatbot_scratch/`; chatbot in `service.py` + `/phase2/chatbot` API.
- Frontend `agent-chat.js` uses chatbot API; panel visible when `has_report`.

**Why:** Light session memory without Hindsight; operators can dig deeper after Phase C with real agent tools.

---

## 2026-06-14 — Swagger API quick-link cards

**What:** Upload / Runs / Phase 2 / Grafana shortcut cards on `/docs` now jump to the matching operation in Swagger UI.

**How:** New `swagger-docs.js` captures the Swagger system on spec load, calls `layoutActions.show` + `scrollTo`, and falls back to DOM (`data-tag`, `data-path`) with retries; fixed Upload tag `simagix-upload`.

**Why:** URL bar changed but the docs panel did not scroll or expand — looked broken.

---

## 2026-06-14 — Phase rail state machine fix

**What:** Phase rail reliably shows grey → blue (waiting) → amber (running) → green (done); no stale green on LLM switch or re-run.

**How:** Rewrote `phase-rail.js` with single `railState`, `applyState()`, explicit `getNodeVisual` priority; reset on new Run RCA; progress bar width set directly; `running_rca` API status maps to Phase C amber on reload.

**Why:** Mutable `Set` + class priority caused incorrect node colors and fill bar.

---

## 2026-06-14 — Phase rail states, home pipeline, tool trace scroll

**What:** Home A/B/C is a clean horizontal track (no shallow 3D scroll); phase rail uses amber=running, blue=current, green=done; submit locks during Phase C; tool trace panel scrolls to match RCA column height.

**How:** `phase-rail.js` state machine; `clarify-wizard.setSubmitting`; `pipeline-track` CSS; `rca-grid` flex heights.

**Why:** UX feedback — users thought report was ready when C started; irregular home scroll and mismatched panels.

---

## 2026-06-14 — Clarify wizard, post-report chat, report UI restore

**What:** Report back to section-based viewer (not 3D deck); home A/B/C panels shorter; Phase B one-question cards (answer/skip/prev); follow-up chat after RCA using report context + Profiler API.

**How:** `clarify-wizard.js`, `agent-chat.js`, `clarify-chat.css`; same `POST /phase2/clarify` payload; chat uses sessionStorage + report JSON Q&amp;A (no new backend routes).

**Why:** User preferred prior report UX; less scroll on home pipeline; guided clarify flow; operator follow-up without changing Phase A/B/C APIs.

---

## 2026-06-14 — Webflow-style 3D scroll (native, no Lenis)

**What:** Report + home pipeline use sticky-panel 3D flip transitions on scroll (Webflow-style); causal chain is one 3D panel per step with animated connector lines.

**How:** `scroll-3d.js` + `scroll-3d.css` — single passive scroll listener + rAF, CSS `rotateX`/`translateZ` per panel progress; report viewer restructured as scroll deck.

**Why:** User wanted Webflow-like 3D scroll cool factor without smooth-scroll friction.

---

## 2026-06-14 — Fast scroll + interactive report viewer

**What:** Native-speed scrolling site-wide; RCA report renders as scroll sections with SVG causal-chain connectors, sticky section nav, and confidence ring.

**How:**
- Removed Lenis + GSAP ScrollTrigger; `motion.js` uses Intersection Observer + CSS transforms (`once` only).
- Added `report-viewer.js` / `report-viewer.css` — fetches JSON report, 3D section reveals, animated chain paths.
- Run page panels no longer use heavy scroll animations; `rca.js` drives the new viewer.

**Why:** Lenis/GSAP were causing scroll friction; structured JSON report enables causal-chain UX plain text cannot.

---

## 2026-06-14 — Immersive scroll UI (GSAP + phase rail)

**What:** Cinematic home/run/upload pages — 3D scroll reveals, smooth Lenis scrolling, sticky Phase A→B→C progress bar on run detail, dramatic report section entrance.

**How:**
- `frontend/static/css/motion.css`, `motion.js`, `phase-rail.js`; GSAP ScrollTrigger + Lenis via CDN in `base.html`.
- Templates updated with `data-reveal`, glass cards, hero pipeline story; `rca.js` drives `FtdcPhaseRail` during RCA.

**Why:** Product UI should feel premium and guide users through the 3-phase RCA without external design tools.

---

## 2026-06-14 — API docs dark-theme contrast fix

**What:** Swagger UI and ReDoc text readable on dark backgrounds (`/docs`, `/redoc`).

**How:** Expanded `swagger-theme.css` (markdown, models, code blocks, tables); ReDoc theme + `redoc-theme.css` overrides for content and sidebar.

**Why:** Default Swagger/ReDoc styles left dark gray copy on our dark shell.

---

## 2026-06-14 — Branded Bootstrap API docs (`/docs`, `/redoc`)

**What:** OpenAPI browser pages match the main app — dark theme, navbar, quick links to Upload / Runs / RCA / Grafana.

**How:**
- Custom `swagger_ui.html` + `redoc_ui.html` in `frontend/templates/`; routes in `backend/app/web/api_docs.py`.
- `docs_url=None` / `redoc_url=None` on FastAPI; themed CSS in `swagger-theme.css` and `redoc-theme.css`.

**Why:** Devs get a consistent, polished API reference instead of default Swagger styling.

---

## 2026-06-14 — Bootstrap UI in `frontend/` folder

**What:** Professional dark Bootstrap 5 UI for home, upload, runs, and run detail; legacy custom CSS templates removed.

**How:**
- New `frontend/` — `templates/`, `static/css/theme.css`, `static/js/rca.js`, `grafana.js`.
- `main.py` serves static from `frontend/static`; `web/routes.py` loads Jinja from `frontend/templates`.
- MongoDB-green accent theme, Bootstrap Icons, phase stepper, improved tables and upload dropzone.
- Standalone HTML reports use Bootstrap + `theme.css` (`report_html.py`).

**Why:** Swappable presentation layer — product logic stays on `/simagix/*` APIs; future reskins only touch `frontend/`.

---

## 2026-06-14 — Cursor web_fetch + report section UX

**What:** Cursor RCA can record real web fetches in the tool trace; the UI points users to where the report lands after Phase C.

**How:**
- `cursor_web_tools.py` — `web_fetch` CustomTool (HTTPS `mongodb.com` only), writes `web` rows to `tool_trace.json`.
- Prompts require `web_fetch` before citing URLs in investigation / final RCA.
- `rca.js` scrolls to `#report-section` after clarify; status text mentions top links + bottom section.
- `run_detail.html` — short help blurb under RCA Report heading.

**Why:** Cursor has no built-in web search (unlike Gemini ADK); URLs in reports were often unsourced. Users missed the saved report at the bottom of the run page.

---

## 2026-06-14 — Fix Cursor MCP evidence tools rejected at runtime

**What:** Cursor Phase A/C can call simagix-evidence MCP tools again (metrics, profiler, budget).

**How:**
- MCP stdio `cwd` → project workspace root; `PYTHONPATH` in `mcp_server_env()`.
- Agent `cwd` + sandbox: workspace + sandbox off when MCP on; bundle + sandbox on for clarify-only.
- Phase C resets RCA retrieval budget (`phase2_rca_max_tool_calls`) instead of sharing exhausted investigation cap.

**Why:** Agent cwd was the FTDC export bundle only — MCP subprocess could not import `backend` or persist budget under `runs/.../phase2/llm/`.

---

## 2026-06-14 — Robust Cursor/Gemini RCA JSON parsing

**What:** Phase C no longer fails when the agent returns preamble text plus a fenced JSON block with nested `finding_analyses` / `incident_timeline`.

**How:** Brace-balanced JSON extraction in `parse_output.py`; prefer longer streamed assistant text in `cursor_provider.py`; light RCA payload normalization (missing `root_cause`, string `confidence`, bad citations).

**Why:** Cursor often wraps valid RCA JSON in markdown; the old non-greedy regex stopped at the first `}` inside nested objects.

---

## 2026-06-14 — Gemini ADK web search in tool trace UI

**What:** Gemini RCA runs now include Google Search alongside evidence tools; web calls appear in Agent Tool Activity (same `google_search` / Web badge as mock/Cursor).

**How:**
- `build_adk_agent_tools()` adds `GoogleSearchTool(bypass_multi_tools_limit=True)`.
- `adk_runner.py`: `after_tool_callback` classifies `google_search_agent` as web; `record_grounding_metadata()` captures grounding chunks from ADK events.
- Tests: `test_adk_tool_trace.py`.

**Why:** Prompts require web research in Phase A/C; Gemini traces previously showed MCP only.

---

## 2026-06-14 — Per-LLM Phase 2 isolation (breaking)

**What:** Phase 2 state is fully isolated per LLM (`mock`, `cursor`, `gemini`) under `phase2/llm/{llm}/`. One slot per LLM per run — re-run overwrites that folder only. FTDC export bundle stays shared per `run_id`.

**How:**
- New `llm_paths.py`: `llm_folder_name()`, `llm_session_dir()`, `list_llm_sessions()`, `update_llm_index()`.
- `Phase2Session` + `Phase2SessionStore` keyed by `f"{run_id}:{llm}"`; separate `SimagixEvidenceService` + `RetrievalBudget` per LLM.
- APIs require `llm` on `GET .../status`, `.../tool-trace`, `.../reports/latest` (and `/view`). `POST .../run` accepts `llm` or `llm_provider`. New `GET .../phase2/llm` lists slots.
- Run page: single **LLM** dropdown (`#llm-context-select`) drives run + view; `rca.js` passes `llm` on all Phase 2 calls.
- Tests: `test_llm_isolation.py`; updated paths to `phase2/llm/mock/`. `scripts/demo.sh` uses `{"llm":"mock"}`.
- **No migration:** delete legacy flat `phase2/*.json` at run root and re-run RCA per LLM.

**Why:** One shared `Phase2Session` per run caused budget/trace bleed across LLM providers; operators need to compare mock vs live runs side by side on the same evidence bundle.

---

## 2026-06-14 — UI LLM provider picker for Phase 2 RCA

**What:** Run detail page lets operators choose **Cursor**, **Gemini ADK**, **Mock**, or **Default** (.env) before starting RCA; choice persists through all three phases.

**How:**
- `llm_provider` on `POST .../phase2/run` body and `POST .../phase2/clarify` query; stored in `iterative_state.json`.
- `GET /simagix/runs/phase2/llm-providers` lists options with configured/unconfigured state.
- `run_detail.html` + `rca.js`: dropdown replaces mock checkbox; locks after Phase A starts.
- `get_llm_provider(llm_provider=...)` errors on explicit cursor/gemini without API keys.

**Why:** Switch providers per run without editing `.env` or restarting the server.

---

## 2026-06-14 — Gemini ADK provider (Option A: AI Studio + google-adk)

**What:** Added **`GeminiAdkLLMProvider`** as an alternative Phase 2 LLM backend using Google ADK `InMemoryRunner` and a Google AI Studio API key — no custom tool loop in Python.

**How:**
- New modules: `gemini_adk_provider.py`, `adk_runner.py`, `adk_evidence_tools.py` — same evidence tools as MCP, traced as `simagix-evidence/*`.
- `Settings`: `LLM_PROVIDER`, `GOOGLE_API_KEY`, `GOOGLE_MODEL`, `GOOGLE_GENAI_USE_VERTEXAI`.
- `get_llm_provider()`: `gemini` → ADK; `cursor` → Cursor SDK (mock if no key); `mock` → deterministic mock.
- `pyproject.toml` optional `llm` extra adds `google-adk>=1.35.0`; `.env.example` documents Gemini vars.
- Tests: provider selection, ADK evidence tools, missing-key guard.

**Why:** Straightforward path to a managed model/tool loop without duplicating ReAct in Python — ADK runs the agent locally while reusing existing evidence plumbing and 3-phase RCA flow.

---

## 2026-06-14 — Pipeline deduplication documented as future work

**What:** Recorded that upload pipeline runs duplicate FTDC decode/diagnosis (`simagix/ftdc` then `llm-export`) and planned consolidation.

**How:** Added **Pipeline deduplication (upload path)** to [PROJECT_STATUS.md](PROJECT_STATUS.md) § Other future work; updated [DESIGN_NOTES.md](DESIGN_NOTES.md) §8 cross-link.

**Why:** Capture agreed follow-up after architecture review — RCA only needs `exports/` from `llm-export`; second `mftdc` pass is optional for human HTML today.

---

## 2026-06-11 — Multi-agent orchestration scoped in PROJECT_STATUS (future work)

**What:** Documented multi-agent orchestration vs current 3-phase workflow, ROI assessment (mostly overkill), recommended incremental path, and mentor discussion questions.

**How:** Expanded [PROJECT_STATUS.md](PROJECT_STATUS.md) § Future enhancements with “Trust & cost” priorities and “Multi-agent orchestration (mentor discussion)” subsection; cross-links to DESIGN_NOTES §13.16 and SUPERLOG_ANALYSIS §5.

**Why:** Capture architecture conversation for mentor scope review without committing to a full LangGraph-style build.

---

## 2026-06-11 — Rename orchestrator → SimagixEvidenceService + MCP tool trace UI

**What:** Renamed `SimagixRCAOrchestrator` to **`SimagixEvidenceService`**; fixed Agent Tool Activity panel (404 stuck on “Loading…”, generic `"mcp"` tool names).

**How:**
- New module `backend/app/simagix/evidence_service.py`; `Phase2Session.evidence` replaces `.orchestrator`.
- `tool_trace.py`: `resolve_tool_identity()` maps Cursor SDK `"mcp"` payloads to `simagix-evidence/get_metric_window`.
- `session.get_or_load()` restores sessions when any Phase 2 artifact exists (not only `latest_report.json`).
- `GET .../phase2/tool-trace` reads `tool_trace.json` from disk when in-memory session is missing.
- `rca.js`: 404 → empty state instead of infinite loading.

**Why:** “Orchestrator” implied an agent loop; this class is the evidence librarian (Facade). Tool trace is ground truth for demo trust — names and loading had to match what the SDK actually records.

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
