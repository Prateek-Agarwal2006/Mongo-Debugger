# Changelog & improvement log

Living record of **what changed**, **how**, and **why** — for demos, handoffs, and your own memory.  
For spec scorecard and milestones, see [PROJECT_STATUS.md](PROJECT_STATUS.md). For design rationale, see [DESIGN_NOTES.md](DESIGN_NOTES.md).

**Last updated:** 2026-06-24

**Maintenance guide:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) — which docs to update for each type of change.

---

## 2026-06-24 — Grafana run page: dashboard links survive reload; one tab per click

**What:** Reloading the run page during an FTDC decode no longer hides the **Anomaly View** / **All Metrics** links or reverts to "FTDC decode in progress". Each dashboard button opens exactly one Grafana tab, and the run's data is loaded once per browser session.

**How:** The health cache in `stack.py` moved from a per-instance attribute to a module-level `_HEALTH_CACHE`, so it survives the per-request `GrafanaStackManager` and masks a transient probe timeout while the single-threaded FTDC API is busy decoding. In `grafana.js`, the open buttons are real `<button>`s with one debounced `window.open` (no native `<a target=_blank>` double-fire), and the silent first-visit auto-load is guarded by `_wasLoadedThisSession` / `_loadInProgress` so reloads mid-decode don't stack duplicate `/grafana/load` calls.

**Why:** The cache was effectively dead (a fresh manager per request started empty), so every decode-time timeout reported the stack as down and the frontend hid the links; meanwhile reloads re-triggered the auto-load, piling decodes onto the busy FTDC API.

**Docs:** [OPERATIONS.md](OPERATIONS.md) § Grafana troubleshooting, [DESIGN_NOTES.md](DESIGN_NOTES.md) §8 + §14, [ARCHITECTURE.md](ARCHITECTURE.md) Zoom D, [RCA_BACKEND.md](RCA_BACKEND.md) § Grafana charts.

---

## 2026-06-24 — Grafana stack: stop killing Grafana on reload / FTDC recovery

**What:** Refreshing the run page or recovering a down FTDC API no longer tears down Grafana (`:3030`).

**How:** `ensure_running()` uses `docker compose up -d` without `--build`; if Grafana is healthy but FTDC is not, only the `ftdc` service is restarted. `ensure_stack_ready_for_load()` waits up to ~60s when FTDC is busy decoding before replacing the container. Compose adds `restart: unless-stopped`. (Run-page reload UX and health cache finalized in the entry above.)

**Why:** `compose up --build` on every load/recovery recreated both containers; page reload re-triggered a long `/grafana/dir` while FTDC looked unhealthy and got restarted mid-decode.

---

## 2026-06-24 — FTDC server: start without bootstrap diagnostic.data

**What:** Grafana stack FTDC API starts on `:5408` without `tmp/diagnostic.data`; upload-only workflows no longer crash the `ftdc` container at boot.

**How:** Patched `mftdc -server` (`patches/mftdc-server-deferred-load.patch`) skips `ProcessFiles` when no directory args are given; first load is `POST /grafana/dir` as before. Compose uses `mongo-debugger/ftdc:local` with `command: /mftdc -server -latest 0` (no path). `build-ftdc-local.sh` + `GrafanaStackManager` build the image when missing.

**Why:** Hardcoded `tmp/diagnostic.data` bootstrap failed for web-upload users; `/grafana/dir` already reloads per-run FTDC from `uploads/{run_id}/`.

---

## 2026-06-24 — Hatchet export: real merge_clients schema (no date column)

**What:** Hatchet jobs no longer fail at export with `no such column: date` after a successful ~30 min parse.

**How:** `query_connection_timeline()` in `hatchet_export.py` checks `PRAGMA table_info`: minute buckets when `date` exists, per-IP rollups when only `ip`/`accepted`/`ended` exist (Hatchet 7.x). Shared by tier-1 export and tier-2 MCP tools.

**Why:** Test fixtures assumed a `date` column on `merge_clients`; production Hatchet stores connection events without timestamps on that table.

---

## 2026-06-24 — Hatchet retry wipes partial hatchet.db

**What:** Log re-upload and **Retry Hatchet** start from a clean SQLite DB instead of reusing a half-written `hatchet.db` from killed Docker runs.

**How:** `RunWorkspace.clear_hatchet_artifacts()` removes `hatchet.db*` plus `summary.json` / `status.json` before enqueue on upload and retry.

**Why:** Interrupted merges left multi-GB WAL/DB files; re-parsing into that state caused long runs and `SQLITE_BUSY` near completion.

---

## 2026-06-23 — Hatchet UI: hide stale error while job running

**What:** Run page no longer shows old “Permission denied” error while a newer Hatchet job is processing.

**How:** Only render `hatchet_job.error` when `hatchet_status == 'failed'`; show an info banner during `processing`.

**Why:** Failed attempt JSON lingered in the UI after retry succeeded or a new run started.

---

## 2026-06-23 — Fix Hatchet worker script invocation (Permission denied)

**What:** Hatchet jobs failed instantly with `[Errno 13] Permission denied` on `run-hatchet-job.sh`.

**How:** Worker now runs `bash run-hatchet-job.sh …` (script was mode 644); replaced Bash 4 `mapfile` with a macOS-compatible read loop.

**Why:** Upload succeeded but Docker never ran — subprocess tried to execute a non-executable shell script.

---

## 2026-06-23 — Fix log upload isinstance (Starlette vs FastAPI UploadFile)

**What:** Log upload returned 400 “No log files received” for every client (browser, curl, tests).

**How:** `_collect_log_uploads` now checks `isinstance(item, starlette.datastructures.UploadFile)` — `request.form()` returns Starlette instances, not FastAPI wrapper types.

**Why:** Manual multipart parsing skipped every file part due to a false-negative isinstance check.

---

## 2026-06-23 — Fix Hatchet log upload (multipart + zip + large files)

**What:** Log upload on the run detail page accepts browser multipart reliably, supports `.zip`/`.tar.gz` of log files, and streams large logs to disk.

**How:** `POST …/logs` reads `request.form().getlist("files")` instead of `list[UploadFile]` binding; extracts nested log files from archives; chunked writes for multi-GB uploads; UI accepts zip/tar and passes explicit filenames in `FormData`.

**Why:** Server logs showed repeated **400** with nothing saved — typical causes were empty multipart binding from the browser and uploading a zip of case-7 logs (FTDC-style) instead of raw `.log` files.

---

## 2026-06-23 — Fix Hatchet log upload (rotated filenames + UI)

**What:** Log upload on the run detail page works for rotated MongoDB log names (e.g. `mongod.log.2026-06-16T03-22-01`) and surfaces upload errors instead of leaving the button disabled.

**How:** Expanded `_is_log_filename()` in `upload.py`; FastAPI multi-file binding uses `Annotated[list[UploadFile], File()]`; run page upload JS registers before RCA init, wraps `fetch` in try/catch, and shows inline status; file picker `accept` includes gzip/plain text.

**Why:** Case-7 prod logs use rotated names that failed server validation (400) and were often hidden from the picker; network/422 errors left “Upload logs” disabled with no feedback.

---

## 2026-06-23 — Hatchet v2: MCP tier-2 log tools

**What:** Added Hatchet MCP tools for deeper log evidence retrieval during Phase 2 investigation and final RCA when `summary.json` + `hatchet.db` exist.

**How:** New `HatchetEvidenceTools` (`hatchet_tools.py`) queries SQLite via `store_paths` from `summary.json`. Exposed as MCP server `hatchet-evidence` (Cursor) and ADK function tools (Gemini); shares the session retrieval budget with simagix-evidence. Tools: `get_hatchet_slow_ops`, `get_hatchet_log_examples`, `get_hatchet_audit`, `get_hatchet_connection_timeline`.

**Why:** v1 summary-only tier 1 keeps prompts small; v2 lets the agent pull additional log slices on demand without Hatchet HTML or a separate web service.

---

## 2026-06-23 — Hatchet v1: log upload, queue dispatch, Phase 2 gate

**What:** Implemented optional Hatchet log evidence beside mongo-ftdc: second upload on the run page, `job_type`-aware worker dispatch, SQLite → `summary.json` export, and Phase 2 readiness gate when logs exist.

**How:** Added `POST /simagix/uploads/runs/{run_id}/logs` and `POST …/logs/retry`; queue tickets carry `job_type` (`mongo_ftdc` | `hatchet`); worker runs `run-hatchet-job.sh` (`mongo-debugger/hatchet:local`, `-merge`, no `-report`) then `hatchet_export.write_hatchet_artifacts()`; Phase 2 prompts include `build_hatchet_evidence_block()` and block with HTTP 409 until `summary.json` exists when logs were uploaded.

**Why:** Delivers the locked v1 design without Hatchet HTML/MCP — compact tier-1 log evidence in the same RCA flow as FTDC metrics.

---

## 2026-06-23 — Hatchet `-merge` local patch (drop gate)

**What:** Patched upstream Hatchet so `-merge` keeps all log files (not only the last). Documented and tracked the patch outside the gitignored clone.

**How:** Added `shouldDropHatchetBeforeBegin()` — skip `Drop()` on `-merge` when `mergeMarker > 1`. Patch file: `simagix-workspace/patches/hatchet-merge-drop-gate.patch`. Build with `simagix-workspace/scripts/build-hatchet-local.sh` → image `mongo-debugger/hatchet:local`. `scripts/setup-simagix-repos.sh` applies the patch after clone.

**Why:** Upstream commit `fd28370` (Dec 2025) drops tables on every `Begin()` for re-process overwrite; that wipes prior files in a multi-file `-merge` run. Smoke test on Hatchet's `replica.tar.gz` confirmed the regression; concat workaround loses per-file markers.

---

## 2026-06-23 — Design: Hatchet log evidence integration

**What:** Locked the pre-implementation design for adding Hatchet as an optional log evidence source beside mongo-ftdc.

**How:** Use a second run-page log upload (`inputs/mongodb-logs/`), enqueue tool-specific Phase 1 tickets (`job_type: "mongo_ftdc"` or `"hatchet"`) on the existing queue, run one Hatchet job with parse + SQLite-to-`summary.json` export, keep Hatchet's default table names, and include compact connection timeline rollups in tier 1.

**Why:** This uses Hatchet's SQLite-backed analysis directly like mongo-ftdc, avoids depending on its web service, keeps logs optional, and preserves a small LLM prompt while leaving deeper slices for future MCP tools.

---

## 2026-06-17 — Run layout: `inputs/` + `phase1/mongo-ftdc/` (Option A naming)

**What:** Renamed upload inputs from `raw/` to `inputs/` and the FTDC export bundle from `phase1/evidence/` to `phase1/mongo-ftdc/` so tool outputs are symmetric and “raw” is not overloaded.

**How:** `RunWorkspace.inputs_dir`, `mongo_ftdc_dir`, `resolve_mongo_ftdc_dir`; read fallbacks for legacy `raw/` and `phase1/evidence/`; pipeline scripts and committed fixture moved; docs updated.

**Why:** Run-level `raw/` conflicted with bundle tier-3 `raw/`; generic `evidence/` hid that the folder is mongo-ftdc-only before Hatchet adds `phase1/hatchet/`.

---

## 2026-06-21 — Docs: align remaining paths with Option A layout

**What:** Updated stale `exports/mongo-ftdc/`, `data/uploads/`, and `runs/` references in README, ARCHITECTURE, OPERATIONS, PHASE2_LLM, RCA_BACKEND, FTDC_REFERENCE.

**How:** Point evidence bundle and Phase 2 paths at `uploads/{run_id}/phase1/evidence/` and `uploads/{run_id}/phase2/`; note legacy read fallbacks where relevant.

**Why:** Option A migration was documented in SIMAGIX_WORKSPACE/CHANGELOG but index and ops docs still showed the old tree.

---

## 2026-06-21 — Fix Grafana link tests on CI (no tmp/diagnostic.data)

**What:** GitHub Actions failed `test_grafana_links` / `test_grafana_urls_api` with `FileNotFoundError: No diagnostic.data path found`.

**How:** `_resolve_input_path` falls back to `RunWorkspace.resolve_upload_diagnostic_dir(run_id)`; fixture gets `raw/diagnostic.data/.gitkeep`; `run_manifest.json` input points at Option A upload path.

**Why:** CI has no gitignored `tmp/diagnostic.data`; local dev masked the bug via that fallback.

---

## 2026-06-17 — Docs: worker `finally`, retry module layout

**What:** Documented worker `try`/`finally` + `complete()` (queue lease vs job JSON), failure implications without `finally`, and why `retry.py` is separate from `upload.py`.

**How:** New sections in `RCA_BACKEND.md` (retry API, pipeline worker, jobs module table); expanded Layer 1 in `SIMAGIX_WORKSPACE.md`; DESIGN_NOTES §14.4 talking points + §14 decision row.

**Why:** Onboarding from chat — single reference for cleanup semantics and retry architecture.

---

## 2026-06-17 — SIMAGIX_WORKSPACE reference: JSON catalog, RunWorkspace, symlinks

**What:** Added onboarding sections to `SIMAGIX_WORKSPACE.md`: three workspace concepts, RunWorkspace adapter + `resolve()`, symlinks (`uploads/latest`), and full per-upload JSON catalog (four layers).

**How:** Copied from mentor/grill session into docs; aligned DESIGN_NOTES §14.3 adapter diagram with Option A paths.

**Why:** Single place for “what lives on disk and who writes it” without spelunking chat or five files.

---

## 2026-06-20 — Upload rollback + fix false “2 tries” on catalog

**What:** Rejected uploads (wrong file type, no `metrics.*`) no longer leave orphan folders. Catalog “(2 tries)” no longer appears for a single decode when `uploads/latest` symlink duplicates the job scan.

**How:** `upload.py` removes `uploads/{run_id}/` on validation failure; `iter_upload_run_dirs()` skips `latest`; job reads dedupe by `job_id`. Deleted three failed log-upload folders manually.

**Why:** Failed log zips were saved without jobs; pipeline script’s `latest` symlink double-counted the same job JSON.

---

## 2026-06-17 — Remove simagix-workspace/data/ (CLI inputs → tmp/)

**What:** Deleted `simagix-workspace/data/` entirely. Local FTDC sample moved to `tmp/diagnostic.data/`; Hatchet/Keyhole placeholders use `tmp/mongodb-logs/` and `tmp/keyhole-output/`.

**How:** Updated pipeline script defaults; docs for SIMAGIX_WORKSPACE, OPERATIONS, SIMAGIX_TOOLCHAIN.

**Why:** Web uploads use `uploads/{run_id}/` only; `data/` was legacy clutter.

---

## 2026-06-17 — Physical workspace layout (remove legacy scaffold)

**What:** On-disk `simagix-workspace` now uses **only** the Option A tree under `uploads/`. Removed empty legacy dirs (`data/uploads`, `data/jobs`, `data/job_queue`, `exports/`, `runs/`). Test fixture moved to `uploads/phase1test20260609T133314Z/`.

**How:** Migrated committed fixture; updated `.gitignore` and `backend/tests/fixture_paths.py`.

**Why:** Code already wrote to Option A paths but old top-level folders remained and caused confusion.

---

## 2026-06-17 — Option A upload tree (one folder per upload)

**What:** Each upload lives under `simagix-workspace/uploads/{run_id}/` with `raw/`, `phase1/` (jobs, queue, evidence), and `phase2/` (LLM RCA). Orphaned `pending` jobs without a queue file show **Not enqueued** (stale) with Retry. Legacy `data/uploads`, `data/jobs`, `exports/mongo-ftdc`, and `runs/` remain readable.

**How:** `RunWorkspace` canonical paths + `resolve_*` fallbacks; per-run queue at `uploads/{run_id}/phase1/queue/`; pipeline scripts write evidence to `phase1/evidence/`; catalog `stale` status; UI badges + retry for stale/failed.

**Why:** One tree per incident is easier to reason about on PVC/K8s and fixes false “Queued” when job JSON existed but the queue file did not.

---

**What:** Home and `/runs` share one upload catalog with **Upload ID**, **Phase 1** (decode), and **Phase 2** (run analysis) columns; Phase 1 detail page lists decode attempts; user-facing “Upload” / “Run analysis” vocabulary.

**How:** Extended `list_run_catalog()` with `phase2_status`, `upload_time_utc`, attempt counts; shared `partials/upload_catalog_table.html`; Home drops separate jobs table.

**Why:** “Job” vs “run” was ambiguous; Home and `/runs` showed different rows.

---

## 2026-06-18 — Failed pipeline retry + runs catalog (queued / processing / finished / failed)

**What:** Failed uploads stay on disk and can be **retried without re-uploading**. `/runs` lists all runs (exports + in-flight/failed jobs) with pipeline status badges. Failed jobs are **removed from the file queue** when the worker finishes; retry enqueues a **new** `job_id` for the same `run_id`.

**How:** `POST /simagix/uploads/runs/{run_id}/retry` (`backend/app/jobs/retry.py`); `FileJobQueue.has_active_job_for_run()` blocks double-enqueue; `list_run_catalog()` + `/runs/{run_id}/pipeline` UI; Retry buttons on runs table and pipeline page; tests in `test_pipeline_retry.py`, `test_run_catalog.py`.

**Why:** Docker/Colima failures should not force a second upload; operators need one place to see queued, processing, finished, and failed runs.

---

## 2026-06-18 — Doc habit: in-flight tradeoffs + talking points

**What:** Agents must document **low-level concepts** and **decisions made while coding** (not only post-hoc Q&A) in DESIGN_NOTES §14 same session.

**How:** DOC_MAINTENANCE § Low-level concept notes + § In-flight tradeoffs; cursor rule step 7; AGENTS.md step 6; §14.4 decision table example.

**Why:** Chain-of-thought tradeoffs should not live only in chat — mentor demos and future you need §14.

---

## 2026-06-18 — Pipeline worker talking points + doc habit (low-level concepts)

**What:** Mentor/demo notes in DESIGN_NOTES §14.4 (`job_id` vs `run_id`, extra load, rename-as-lock, poll loop); new **Low-level concept notes** rule in DOC_MAINTENANCE + AGENTS + cursor rule.

**How:** §14.4 “Talking points” subsection; DOC_MAINTENANCE matrix row; `.cursor/rules/doc-maintenance.mdc` step 6.

**Why:** Low-level explanations from review/grill should not live only in chat — capture for next presentation.

---

## 2026-06-18 — Standalone pipeline worker (file queue + crash recovery)

**What:** Upload enqueues jobs to disk; a **standalone worker process** claims and runs the mongo-ftdc pipeline. Durable job status survives API/worker restarts. Crash recovery requeues `processing/` → `pending/` on worker startup.

**How:** `backend/app/jobs/queue.py` (`FileJobQueue`), `worker.py` (`python -m backend.app.jobs.worker`), `run_pipeline_job()` in `pipeline.py`; `JobStore` persists to `data/jobs/{job_id}.json`; queue under `data/job_queue/pending|processing/`; removed upload daemon thread.

**Why:** K8s-ready long work — API pod and worker pod share PVC via `DATA_ROOT`; atomic rename claims jobs (v1: **one worker replica**). See DESIGN_NOTES §14.4.

---

## 2026-06-18 — RunWorkspace path adapter (full backend migration)

**What:** `RunWorkspace` centralizes all run-scoped filesystem paths; optional `DATA_ROOT` env for K8s PVC; every backend caller migrated off `_workspace_root()` and inline `simagix-workspace/...` strings.

**How:** `backend/app/core/run_workspace.py` (`exports_dir`, `uploads_dir`, `phase2_dir`, `llm_session_dir`, `list_run_ids`, …); `config.data_root` from `DATA_ROOT`; callers in `api/*`, `web/routes.py`, `jobs/*`, `simagix/*`, `grafana/*`, `llm_paths.py`; `backend/tests/test_run_workspace.py` (8 tests); `main.py` uses `repo_root()` for static assets.

**Why:** Single path seam for K8s prep — configurable root *and* deduplicated layout strings (DESIGN_NOTES §14.3); tests inject `RunWorkspace(tmp_path)` instead of patching five modules.

---

## 2026-06-18 — RunWorkspace path-seam decision (docs)

**What:** Documented why we implement full **RunWorkspace** (not minimal `get_data_root()` only): comparison table, Adapter vs Strategy, planned interface sketch.

**How:** [DESIGN_NOTES.md](DESIGN_NOTES.md) §14 row + §14.3; [ARCHITECTURE.md](ARCHITECTURE.md) § RunWorkspace.

**Why:** K8s prep and architecture review — one seam for configurable root *and* deduplicated layout strings; learning reference before implementation.

---

## 2026-06-18 — Matt Pocock skills repo setup

**What:** Per-repo agent config for `.agents/skills/` — local issue tracker, triage labels, domain doc rules.

**How:** `docs/agents/{issue-tracker,triage-labels,domain}.md`; `## Agent skills` block in `AGENTS.md`.

**Why:** `/to-issues`, `/triage`, `/to-prd`, and domain skills know where issues and tradeoffs live.

---

## 2026-06-16 — Chatbot attachment button fix

**What:** Paperclip opens the file picker reliably; unsupported types show an inline warning.

**How:** Native `<label for="agent-chat-file">` instead of JS `input.click()`; cache-bust `agent-chat.js?v=2`; `content-visibility: visible` on chat panel.

**Why:** Clicks appeared to do nothing (stale JS cache + programmatic file-input open is flaky in some browsers).

---

## 2026-06-16 — Chatbot file attachments

**What:** Post-report chatbot composer has a paperclip — upload text-friendly files into `chatbot_scratch/attachments/` for the agent to read.

**How:** `POST /phase2/chatbot/attachments` (multipart); messages accept `attachments[]`; UI chips + `agent-chat.js` upload flow; `PHASE2_CHATBOT_MAX_ATTACHMENT_BYTES`.

**Why:** Operators can attach profiler exports, logs, or notes without pasting huge JSON into the textarea.

---

## 2026-06-16 — Favicon: `unnamed.png` only

**What:** Browser tab icon uses single uploaded `unnamed.png`; removed other logo/favicon PNGs.

**How:** `base.html` + `/favicon.ico` → `/static/unnamed.png`; deleted `Sprinklr_Brand_Logo.png`, `favicon-32.png`, `favicon-icon.png`.

**Why:** User-provided asset is the only favicon source.

---

## 2026-06-16 — Sprinklr logo favicon + phase rail scroll fix

**What:** Favicon uses uploaded `Sprinklr_Brand_Logo.png` (cropped splash icon); A→B→C rail shows correct state at page top without scrolling to the bottom.

**How:** `favicon-32.png` / `favicon-icon.png` from brand PNG; simplified `phase-rail.js` scroll-hide (window scroll only, no wheel/sentinel traps); `showShell()` on API status hydrate.

**Why:** User-provided branding; rail was hidden or stuck until full-page scroll due to aggressive wheel/inner-panel hide logic.

---

## 2026-06-16 — Sprinklr-style favicon

**What:** Browser tab shows a Sprinklr-inspired splash icon on all web UI pages.

**How:** `frontend/static/favicon.svg`; `<link rel="icon">` in `base.html`; `GET /favicon.ico` serves the same asset.

**Why:** Intern/demo branding in the tab bar without changing app behavior.

---

## 2026-06-16 — §14 tradeoff habit in doc maintenance

**What:** Documented the habit: architecture “why not X?” decisions go in `DESIGN_NOTES.md` §14 same session as the code.

**How:** `DOC_MAINTENANCE.md` §14 habit + checklist; `.cursor/rules/doc-maintenance.mdc` step 5; `AGENTS.md` step 4.

**Why:** Managers and future you can trace tradeoffs without a sprawl of one-off docs.

---

## 2026-06-16 — Design Notes §14 mentor tradeoffs

**What:** Added **§14 Architecture tradeoffs** to `DESIGN_NOTES.md` — why this, not LangGraph/Hindsight/vector memory/etc.

**How:** Single table + sound bites + “when to revisit”; cross-links from `docs/README.md` and `PROJECT_STATUS.md`. No separate dilemma doc.

**Why:** Manager/mentor can ask “why this approach?” from one living doc alongside §13 code Q&A.

---

## 2026-06-16 — CI: ADK tool test matches web_fetch

**What:** Fixed failing `test_build_adk_agent_tools_includes_google_search` in GitHub Actions.

**How:** Renamed assertion to `web_fetch` — Gemini ADK uses shared HTTPS fetch, not `GoogleSearchTool`.

**Why:** Phase 3 replaced Google Search with policy-gated `web_fetch`; stale test expected the old tool.

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
