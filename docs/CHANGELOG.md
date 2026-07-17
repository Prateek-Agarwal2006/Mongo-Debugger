# Changelog & improvement log

Living record of **what changed**, **how**, and **why** — for demos, handoffs, and your own memory.  
For spec scorecard and milestones, see [PROJECT_STATUS.md](PROJECT_STATUS.md). For design rationale, see [DESIGN_NOTES.md](DESIGN_NOTES.md).

**Last updated:** 2026-07-17

**Maintenance guide:** [DOC_MAINTENANCE.md](DOC_MAINTENANCE.md) — which docs to update for each type of change.

---

## 2026-07-17 — Charts: LLM-authored matplotlib runs in Daytona sandbox (replaces in-pod render)

**What:** `render_metric_chart` (server-side matplotlib) replaced by `execute_plot_script`: the agent writes the plotting code (template lives in the `metric-plotter` skill) and it executes in an ephemeral Daytona microVM — never in a pod. Server pushes `data.csv` in, pulls `chart.png` out, stores it in `raw_files` (kind=`charts`); chart_id/report/download pipeline unchanged. matplotlib dropped from the API image; `daytona` SDK added to the `llm` extra.

**How:** `sandbox_plot.py` (fetch series → sandbox → store PNG, sandbox deleted in `finally`); `chart_tools.py` reduced to fetch/CSV/store helpers; MCP tool + prompts + skill rewired; `DAYTONA_API_KEY` in helm secret + both deployments. `test_sandbox_plot.py` mocks the SDK; live smoke + live E2E (143k points) verified against Kind data.

**Why:** LLM-generated code must not execute inside pods (credentials, cluster access). Sandbox = isolation for untrusted code; skill now carries real plotting code per mentor's design.

---

## 2026-07-16 — Phase A prompt: clear tiers + mandatory tier-3 + runtime MCP/skills inventory

**What:** Prompt text separates tier 1/2/3; Phase A **must** call tier-3 tools (prompt-only). Phase A/C/chatbot prompts list **MCP servers + skills actually attached this turn** (WorkArea checkboxes + catalog), not a blurry static tool list.

**How:** `build_runtime_attachments_block` via `build_mcp_server_specs` + `list_skill_dirs`; wired through `prepare_*` / chatbot with `enabled_mcp_ids`; `test_tier_prompt_policy.py`.

**Why:** “Available MCP tools: get_metric_window…” hid WorkArea MCPs/skills; tier copy was confused.

---

## 2026-07-16 — Pytest: refuse Kind/live DB; stop wiping operator runs

**What:** `pytest` refuses Kind/live `DATABASE_URL` (`postgres` / `debugger`). Per-test cleanup no longer `DELETE`s non-fixture `metrics` / `evidence` / `raw_files`.

**How:** `backend/tests/db_guard.py` + conftest import check; `_clean_job_tables` only `TRUNCATE`s `jobs` / `job_status` / `phase2_state`; guard unit tests; OPERATIONS + AGENTS warnings.

**Why:** Pointing the suite at Kind Postgres wiped operator uploads — must not be possible again by accident.

---

## 2026-07-16 — Skill ZIP upload: skip Finder junk / NUL bytes

**What:** Uploading a macOS zip that includes `.DS_Store` no longer returns HTTP 500; junk and any file containing NUL bytes are skipped, skill markdown is kept.

**How:** `upload_skill_zip` filters members via `_is_skippable_skill_member` before JSONB upsert; regression test in `test_skills.py`.

**Why:** Postgres `text`/`jsonb` reject `\u0000`; the UI then failed parsing plain `Internal Server Error` as JSON.

---

## 2026-07-16 — README architecture: Latency Dashboard–style pods + shared MCP

**What:** Root README runtime diagram matches Latency Dashboard style (UI nginx / API / worker / Postgres). Cursor and Gemini both use `build_mcp_server_specs` → **stdio MCP subprocesses on the API pod**; vendor clouds are model-only. Grafana `:3030` labeled Kind playground only.

**How:** Replaced Kind/NodePort-heavy Mermaid with pod subgraphs + provider/MCP tables.

**Why:** Mentors need accurate “where does MCP run?” for both LLM slots; `:3030` is not a prod pattern.

---

## 2026-07-16 — CI: Postgres service for backend tests

**What:** GitHub Actions `Backend Tests` starts Postgres 16, sets `DATABASE_URL`, and syncs `--extra prod` so `psycopg_pool` is installed. Tests expect JSON catalog / SPA (no Jinja HTML routes on API).

**How:** `services.postgres` + health check + `uv sync --extra prod --extra dev --extra llm` in `.github/workflows/test.yml`; update skill/catalog tests for nginx SPA.

**Why:** Suite is Postgres-backed; first CI run failed on missing `DATABASE_URL`, second on `psycopg_pool`, third on stale HTML assertions.

---

## 2026-07-16 — README + architecture diagrams (Kind / nginx / Postgres)

**What:** Root README is Kind-first and detailed: ui nginx entry, catalog gate, Postgres jobs/metrics, Grafana SimpleJSON, WorkAreas, rebuild/troubleshoot. Architecture master diagram updated on the same lines; docs hub points at root README.

**How:** Rewrote `README.md` Mermaid runtime lanes; refreshed `docs/ARCHITECTURE.md` steps 0–7; synced `docs/README.md` layout/flow.

**Why:** GitHub/README still showed FastAPI-as-UI + Docker FTDC `:5408` Grafana; mentors need the current Kind topology.

---

## 2026-07-16 — Future work: retry/crash recovery, LISTEN/NOTIFY, SSE

**What:** Documented three ops/UX upgrades as future work (not implemented).

**How:** [PROJECT_STATUS.md](PROJECT_STATUS.md) § Other future work + [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) Deferred list — (1) lease heartbeat / stale-job reaper + bounded auto-retry, (2) Postgres `LISTEN`/`NOTIFY` to wake workers instead of only polling, (3) SSE for job/Phase 2 progress instead of browser poll loops.

**Why:** Current crash recovery only self-requeues when the *same* worker returns; poll loops add latency and chatter. These are the natural next steps once multi-worker / prod UX matter more.

---

## 2026-07-16 — Postgres probe death spiral + catalog error copy

**What:** Kind Postgres no longer CrashLoops mid-WAL-recovery; SPA shows **Database unavailable** instead of raw `Catalog failed (500)` when catalog cannot reach Postgres.

**How:** Loosened Helm postgres readiness/liveness (`timeoutSeconds: 5`, liveness `initialDelaySeconds: 120`). `App.tsx` maps 500/502/503 catalog responses to a recovery hint.

**Why:** Tight `pg_isready` probes killed postgres during redo after heavy ingest; API then `PoolTimeout` → home/runs unusable.

---

## 2026-07-15 — Upload opens `/runs/{id}` (pipeline until Ready)

**What:** After upload, UI goes to **`/runs/{id}`** (not `/pipeline`). While Phase 1 runs, the same URL shows Decoding / Loading metrics; when the job succeeds the page reloads into RCA.

**How:** Upload redirect target changed; pipeline poll **reloads** if already on `/runs/{id}` (same-URL navigation would not repaint). Gate in `run_detail` unchanged.

**Why:** Operators asked for the run page; `/pipeline` felt like a dead-end while decode was still working.

---

**What:** Kind worker pod no longer crash-loops on startup (`ModuleNotFoundError` for `hatchet` / `pipeline` / `FileJobQueue`).

**How:** `worker.py` now imports `hatchet_job`, `ftdc_job`, and `JobQueue` (Postgres queue) — matching the renamed modules.

**Why:** Without a live worker, Phase 1 never finishes so the pipeline page never redirects to `/runs/{id}`.

---

## 2026-07-15 — Upload / Run RCA busy spinner

**What:** Start pipeline and Run RCA show a circular spinner, stay disabled, and block double-submit while work runs.

**How:** `static/js/btn-busy.js` + `.mdb-btn-spinner` in `stitch-nav.css`; upload form and `rca.js` call `MdbBtnBusy.start/stop`.

**Why:** Long Kind uploads looked stuck and allowed accidental duplicate runs.

---

**What:** Kind entry is a **ui** nginx pod (NodePort → `localhost:8000`). It serves the Vite Modern SPA + `/static` stitch assets and proxies `/simagix`, `/grafana`, `/docs`, `/health` to an **api** ClusterIP service. Classic Jinja UI removed from the API; API image has no `frontend/`.

**How:** `Dockerfile.ui` + `nginx-ui.conf`; Helm `ui/` Deployment+Service; API Service type ClusterIP; `GET /simagix/catalog` (+ `/{run_id}`) for SPA bootstrap and Phase 1 RCA gate; React boots from URL and fills `#mdb-page-data` for stitch iframes.

**Why:** Same topology as Merged Dev — UI and API deploy independently; API does JSON only; Classic theme dropped.

---

**What:** After upload succeeds, UI goes straight to the Phase 1 pipeline page (no wait on Upload). Badges say **Decoding** vs **Loading metrics**. Run RCA only opens when Phase 1 job is **succeeded** (fixtures without a job still work).

**How:** Stitch/classic upload redirect to `/runs/{id}/pipeline`. `phase1_progress_label()` from job message; catalog `phase1_label`. `run_detail` returns pipeline while job is running/failed even if evidence exists.

**Why:** Operators thought decode was stuck / RCA was ready mid-COPY; redirect waited for full Phase 1.

---

## 2026-07-15 — Phase 1 “3600s timeout” was actually `ftdc-slice` index (120s)

**What:** Full FTDC uploads no longer die as a fake `Pipeline timed out after 3600s` right after metrics COPY. UI “failed” was often a **120s** `ftdc-slice --mode index` timeout mislabeled by a broad `except TimeoutExpired`.

**How:** Catch llm-export timeout only around the pipeline subprocess; ingest failures report `Ingest failed` with the real error. Index timeout scales with file count (`max(300, 90×n)`); catalog timeout 300s. Unit tests lock the mislabel fix.

**Why:** Evidence + ~3.6M metrics were already in Postgres; only raw_file_index/catalog remained. Operators thought decode ran for an hour when wall clock was ~12 minutes.

---

## 2026-07-15 — Docker: pip dep-layer cache (code-only rebuilds skip wheels)

**What:** API and worker images install Python deps from `pyproject.toml` **before** copying app code, so editing `backend/` / `frontend/` no longer re-runs the fat `pip install`.

**How:** Stub `backend/` → `pip install` extras → `COPY` real code → `pip install --no-deps .` (fast, keeps site-packages current for MCP cwd≠/app). Worker stays `.[prod]` only. (BuildKit pip download mounts skipped — Colima here has no `docker-buildx`; Docker **layer** cache is the win.)

**Why:** Day-to-day Kind rebuilds were dominated by re-downloading `cursor-sdk`/`google-adk` after any Python edit. First/clean builds stay slow; code-only rebuilds should drop to roughly minutes of COPY + thin reinstall (+ Kind load).

---

## 2026-07-15 — Worker image: `.[prod]` only (drop LLM pip)

**What:** Worker Docker image no longer installs `cursor-sdk` / `google-adk` (`[llm]` extra).

**How:** `Dockerfile.worker` uses `pip install ".[prod]"` only. API keeps `.[prod,llm]` (Phase 2 MCP).

**Why:** Worker is Phase 1 (ingest / llm-export / ftdc-slice). LLM wheels were most of rebuild time and unused on the worker.

---

## 2026-07-15 — API ships `ftdc-slice`; tier-3 window correctness + Cursor smoke

**What:** API image includes `ftdc-slice` (~4.5 MB) so Phase 2 `get_raw_window` works in the API pod. Integration tests assert series match an independent CLI oracle; local Cursor MCP smoke verified `point_count`/`first`/`last` against that oracle, then the smoke script was deleted.

**How:** Multi-stage `Dockerfile.api` (same Go build as worker, copy binary to `/usr/local/bin`). `test_get_raw_window_matches_cli_oracle` compares PG-reassembled window to `ftdc-slice --mode window` on original FTDC bytes. Cursor smoke called `simagix-evidence/get_raw_window` and matched oracle `[1780650587, 510832455]`…`[1780650617, 510832455]` (31 points).

**Why:** Without the binary on the API, tier-3 MCP fails after Postgres migration; non-empty series alone is a weak test — oracle equality proves correct bytes were retrieved.

---

## 2026-07-15 — Remove dead `get_raw_path` MCP/REST stub

**What:** Dropped the legacy tier-3 `get_raw_path` tool (MCP + REST + prompts + tool-trace allowlist). Tier-3 is only `list_raw_paths` → `get_raw_window`.

**How:** Deleted stub from `ftdc_tools` / `rca_service` / `evidence.py` MCP server; removed `GET …/tools/raw-path`; updated prompts and docs (§13.11, PHASE2_LLM, RCA_BACKEND).

**Why:** Stub always returned “not available after Postgres migration” — wasted tool-call budget and distracted the LLM from working tools.

---

## 2026-07-15 — Grafana: Anomaly View + All Metrics dashboards

**What:** Evidence tab again has **Anomaly View** and **All Metrics** buttons with full panel sets (not the 4-panel stub).

**How:** Provisioned `anomaly-focus.json` (11 triage panels) + `all-metrics.json` (ported simagix analytics, 35 charts). `/grafana/simple/config` returns both UIDs; `/range` adds `anomaly_from`/`anomaly_to` from `top_anomaly_windows`. Stub `mongo-ftdc-metrics` removed.

**Why:** Operators need the old dual-tab workflow — incident zoom vs full FTDC catalog — on Postgres SimpleJSON.

---

## 2026-07-15 — Grafana empty panels: deep-link capture window

**What:** **Open in Grafana** shows the run's FTDC charts instead of blank panels.

**How:** `GET /grafana/simple/runs/{run_id}/range` returns padded min/max metric `ts`; `grafana.js` appends `from`/`to` to the dashboard URL. Dashboard default widened to `now-90d` as a fallback when opened without a deep link.

**Why:** FTDC timestamps are from the capture (often weeks old); Grafana defaulted to `now-6h`, so every panel was "No data" even when Postgres had metrics.

---

## 2026-07-15 — Metrics ingest: DELETE + COPY (replace), not row upserts

**What:** Phase 1 metrics load for multi‑million-point FTDC no longer uses row-wise upserts.

**How:** `_ingest_time_series` does `DELETE FROM metrics WHERE run_id=…` then Postgres `COPY … FROM STDIN` streaming from `time_series.jsonl.gz`. Evidence JSON commits in its own transaction before metrics. Local smoke on the **same** Kind-run series (`time_series.jsonl.gz` ~23.7 MB, **3,869,232** points): **COPY ≈ 385 s** (~6.4 min) vs prior Kind path **~20+ min** still in `executemany`; tiny unit test locks replace semantics. Smoke script deleted after the run.

**Why:** Write-once-per-run series should be replace+bulk load; `ON CONFLICT` batches were the wrong tool. Remaining ~6 min is mostly Python decode/`write_row` + PK build (further win: binary COPY / drop-index-during-load later).

---

**What:** Large/any FTDC upload no longer freezes the API on “Uploading…”; schema apply no longer waits forever on a locked relation.

**How:** Stream zip to disk; unpack/PG raw store/enqueue in `asyncio.to_thread`. Connection pool `timeout=30`; `SET lock_timeout = '10s'` before `ensure_schema()`. (Ops: terminate `idle in transaction` sessions that hold metric INSERT locks.)

**Why:** Sync store on uvicorn’s only worker + a leftover `idle in transaction` INSERT blocked `ensure_schema` DDL — health stayed up (no DB) while upload hung.

---

**What:** Big `diagnostic.zip` uploads no longer hang the whole API (UI stuck on “Uploading…”; `/health` times out).

**How:** Stream zip to disk; run unpack + Postgres raw-file store + enqueue in `asyncio.to_thread` so the single uvicorn worker keeps serving health/UI. Upload pages show size + 30m abort timeout.

**Why:** Sync `file.read()` + `_store_ftdc_raw_files` on the event loop blocked Kind’s one API worker for the whole FTDC chunk write.

---

**What:** Modern (Stitch) upload picker no longer greys out a valid `.zip` of `diagnostic.data`. Copy clarifies zip-of-folder is the intended Mac path; unzipped folder drops show a clear tip.

**How:** Removed `accept=".zip,.tar.gz,.tgz,.metrics.*"` from `frontend/static/stitch/upload.html` (multi-dot / `metrics.*` filters break macOS). Classic + Stitch copy updated; empty folder-drop message added. Test `test_upload_accepts_zipped_diagnostic_data_folder` locks nested `diagnostic.data/metrics.*` unpack.

**Why:** Backend already unpacked nested zips; the Modern theme filter made “zipped folder” look unsupported in the file picker.

---

**What:** Investigation / RCA / chatbot MCP tool budgets default to **1_000_000** (demo “infinite”).

**How:** `Settings.phase2_*_max_tool_calls` defaults + Helm ConfigMap `PHASE2_*_MAX_TOOL_CALLS`.

**Why:** Kind RCA demos were hitting the old 5–6 call caps before evidence MCP + operator tools finished.

---

## 2026-07-15 — Grafana: Postgres SimpleJSON + Helm pod; delete Docker stack

**What:** Evidence tab opens Grafana against ingested PG metrics. Kind deploys a Grafana pod. Old Load FTDC / ftdc-api / compose path is gone.

**How:** Keep `/grafana/simple`; add Helm Grafana **10.4.7** (Angular SimpleJSON plugin; Grafana 11 refuses it) with datasource → `http://api:8000/grafana/simple`, dashboard `mongo-ftdc-metrics` with `$run_id`. UI is one **Open in Grafana** button. Deleted `grafana_routes.py`, `backend/app/grafana/*`, `grafana-compose.yaml`, `run-grafana-stack.sh`, deferred-load patch; dropped `FTDC_API_URL` / startup-wait settings.

**Why:** Production Decision 4 — no shared volume, no 2-minute warm, multi-run via template variable. Kind had no Grafana pod and the UI still called the dead Docker path.

---

## 2026-07-15 — Kind: restore simagix-evidence MCP discovery

**What:** Cursor/ADK no longer report `simagix-evidence` as discovery-failed in Kind while `web_fetch` still works.

**How:** Builtin MCP stdio `cwd` is `repo_root()` (`/app` in the image); `PYTHONPATH` puts the code root first. `SIMAGIX_WORKSPACE_ROOT` still carries `DATA_ROOT`. Dockerfiles install after `COPY backend/` so `backend` is on site-packages.

**Why:** Spawning `python -m backend…` with `cwd=/data` (DATA_ROOT) raised `ModuleNotFoundError: No module named 'backend'`, so metric/raw tools never registered.

---

## 2026-07-01 — Chatbot MCP center modal (blur backdrop)

**What:** MCP picker is a centered modal with blurred/faded backdrop; **MCP**, **Attach**, and **Send** sit together on the right of the composer.

**How:** `#chatbot-mcp-modal` moved outside the chat form (fixed overlay); backdrop blur + **×** / Escape / backdrop click to close. Fixes popover clipping inside the chat card.

**Why:** User-requested modal UX; prior anchor popover was clipped and split buttons left vs right.

---

## 2026-07-01 — Chatbot MCP popover (composer button)

**What:** Chatbot MCP selection opens from an **MCP** button left of **Attach**; top-right **×** closes the panel.

**How:** `#chatbot-mcp-picker` popover in composer actions; `agent-chat.js` toggle/close; styles in `clarify-chat.css` + `agent-chat-stitch.css`.

**Why:** Keep chat focused; MCP selection on demand like a tool picker.

---

## 2026-07-01 — Chatbot MCP panel on Chatbot tab

**What:** Post-report chatbot has its own MCP connector checkboxes on the Chatbot tab (and report-section chat panel on Bootstrap run page), independent of Investigation.

**How:** `#chatbot-mcp-run-checkboxes` panel in `run_workspace.html` / `run_detail.html`; `rca.js` loads connectors into both Investigation and chatbot panels; `agent-chat.js` sends `selectedChatbotMcpIds()` per message. Not persisted to `chatbot_chat.json`.

**Why:** Operators on the Chatbot tab should pick MCPs without switching back to Investigation.

---

## 2026-07-01 — Chatbot MCP selection (stateless per message)

**What:** Post-report chatbot accepts `enabled_mcp_ids` on each message like Phase A and Phase C.

**How:** `POST /phase2/chatbot/messages` accepts `enabled_mcp_ids`; service passes through to `run_chatbot()` on all providers.

**Why:** Operators expect WorkArea connectors on follow-up questions without a saved selection.

---

## 2026-06-30 — Grafana dashboard buttons visible on Stitch run page

**What:** **Anomaly view** and **All metrics** buttons appear on the Evidence tab after the stack is healthy or FTDC load completes.

**How:** `grafana.js` — `setGrafanaElVisible()` toggles Tailwind `class="hidden"` and HTML `hidden` (Stitch markup uses both); cache-bust `?v=5`.

**Why:** `_applyOpenLinks` only cleared the `hidden` attribute; Tailwind `hidden` kept buttons invisible — same class of bug as Phase B Skip on Stitch.

---

## 2026-06-30 — README: Colima / Docker stuck recovery (Mac)

**What:** Quick-start docs explain how to recover when Colima says Running but Docker socket fails (Grafana 503, pipeline Docker errors).

**How:** New **Colima / Docker stuck** subsection in root `README.md`; matching operator table in `OPERATIONS.md`.

**Why:** Common Mac failure mode — `colima start` alone does not fix a dead socket forward; operators need `colima stop` then `colima start`.

---

## 2026-06-30 — ADK Phase C tool trace: scope call_id by phase

**What:** Phase C (final RCA) MCP/web tool calls appear in Agent Tool Activity with phase badge **C**, not dropped as duplicates of Phase A rows.

**How:** `adk_tool_trace_call_id(tool_context, phase)` prefixes ids as `{phase}:{function_call_id}`; test `test_adk_tool_trace_call_id_scoped_by_phase`.

**Why:** One `tool_trace.json` per LLM slot accumulates A+C; ADK may reuse `function_call_id` across separate agent sessions — dedup on raw id silently dropped Phase C rows while terminal still showed `CallToolRequest`.

---

## 2026-06-30 — Phase B Skip button visible after submit / re-run

**What:** Skip (and Prev/Next/Submit) reappear on Phase B clarifying questions after submit, LLM switch, or a second Run RCA on the same page; Skip on the last question clears the textarea and updates progress dots.

**How:** `clarify-wizard.js` — `resetClarifyActions()` restores `#clarify-actions` visibility and re-enables buttons from `showClarifyWizard`, `hideClarifyWizard`, and `setSubmitting(false)`; Skip always calls `renderWizardCard()`; Stitch buttons get `text-on-surface`; cache-bust `?v=4`.

**Why:** `setSubmitting(true)` hid the entire `#clarify-actions` bar; success path called `hide()` without restoring it, so a later `show()` rendered questions but left the action bar hidden. Last-question Skip cleared the answer in memory without re-rendering.

---

## 2026-06-30 — ADK tool trace: one row per MCP call (+ error status)

**What:** Gemini ADK activity panel shows every MCP/web tool call with correct status; docs explain Cursor vs ADK trace IDs and failures.

**How:** `adk_tool_trace_call_id()` uses `function_call_id` (not `invocation_id`); `adk_tool_trace_status()` marks MCP/ADK errors; PHASE2_LLM + DESIGN_NOTES §13.18 talking points.

**Why:** Shared `invocation_id` deduped six real calls into one row; failed MCP executions should show `error`/`failed` like Cursor when the provider reports them.

---

## 2026-06-30 — Gemini ADK: MCP stdio timeout + skill slot fix

**What:** Gemini ADK Phase 2 registers simagix-evidence MCP tools again; operator skill folder renamed to match SKILL.md `name:`.

**How:** `ADK_MCP_STDIO_TIMEOUT_SEC=60` on `StdioConnectionParams` (ADK default 5s < evidence server cold import ~14s); preflight `_ensure_adk_mcp_toolsets_ready` in ADK runner; `upload_skill_zip` syncs frontmatter `name:` to slot; `operator/skills/trial` → `mongo-rca-playbook`.

**Why:** ADK MCP session timed out during initialize → only `web_fetch` registered → `get_metric_window` not found; skill `mongo-rca-playbook` vs folder `trial` failed ADK load.

---

## 2026-06-30 — Cursor: drop auto_review from LocalAgentOptions

**What:** Phase 2 Cursor runs no longer pass `auto_review=True` to the SDK.

**How:** Removed `auto_review` from `providers/cursor/provider.py` `LocalAgentOptions` (SDK default).

**Why:** User request; rely on SDK default instead of forcing Smart Auto Review on MCP phases.

---

## 2026-06-30 — Phase A: require MCP, block bundle file reads

**What:** Investigation prompt forbids read/grep on export bundle paths; tier-2 proof must go through simagix-evidence MCP.

**How:** `INVESTIGATION_SCRATCH_RULES` in `prompts.py` (Phase A only); Phase C/chatbot keep permissive `SCRATCH_RULES`.

**Why:** With sandbox off, Cursor agent read `phase1/mongo-ftdc/normalized/*.json` directly (461 local / 0 MCP on 2026-06-30) instead of calling simagix-evidence.

---

## 2026-06-30 — Cursor sandbox always off (fix Phase B 500)

**What:** All Phase 2 Cursor phases (investigation, clarify, final RCA, chatbot) run with `SandboxOptions(enabled=False)`.

**How:** `providers/cursor/provider.py` — `enabled=False` for every `_agent_options` call; no per-phase toggle.

**Why:** Phase B (clarify, MCP off) enabled sandbox and Cursor SDK returned `BadRequestError` (“sandboxing is not supported in this environment”) → unhandled 500 on `POST /phase2/run`.

---

## 2026-06-30 — Verbatim errors: Phase 2 + upload (no Unexpected token)

**What:** Phase 2 RCA, chatbot, and upload failures show the full response body instead of `Unexpected token 'I'…` JSON parse errors.

**How:** `readResponseBody` + `errorFromBody` in `api-error-text.js`; `rca.js` and `agent-chat.js` parse text-first on all error paths; upload POST uses same helper; Phase 1 job error embedded via `#mdb-job-error-json` (`tojson`) instead of raw `<template>`.

**Why:** Bare `response.json()` on HTML/plain-text 502 bodies surfaced SyntaxError text instead of the real server message.

---

## 2026-06-30 — Verbatim Phase 1 errors (no JSON.parse on stack traces)

**What:** Failed Phase 1 jobs show the full stored error (Docker panic, stderr) instead of `Unexpected token` in the UI.

**How:** `job_error` removed from `#mdb-page-data` JSON; errors live in `<template id="mdb-job-error">` or are fetched via `MdbPageData.fetchJob`. Stitch `pipeline.html` and upload poll paths use `page-data.js` + `readResponseBody` instead of bare `response.json()`.

**Why:** Embedding multi-line stderr inside a hand-built JSON script tag broke `JSON.parse`, so the Stitch iframe never read page data and poll failures surfaced as parse errors.

---

## 2026-06-30 — Nav label: Uploads → Runs (UI only)

**What:** User-facing list/nav copy says **Runs** instead of **Uploads**; upload action labels unchanged.

**How:** Classic nav, Stitch iframe pages, Jinja templates, React `ModernShell` / `StitchShell` / `RunsTable`; rebuilt `frontend/static/modern/assets/index.js`.

**Why:** “Runs” matches `/runs` and the analysis workflow; API paths and `simagix-workspace/uploads/` dirs unchanged.

---

## 2026-06-30 — Fake FTDC upload cleanup

**What:** Removed eight duplicate fake-FTDC upload runs and their failed/pending jobs; one canonical test fixture remains.

**How:** Deleted `upload20260620T082155Z`, `upload20260621T124610Z`, `upload20260621T125755Z`, `upload20260627T010718Z`, `upload20260627T144723Z`, `upload20260629T131844Z`, `upload20260629T132543Z`, `upload20260630T081605Z` under `simagix-workspace/uploads/` (each had a 17-byte `fake-ftdc-content` metrics file). Added `backend/tests/fixtures/fake_ftdc/metrics.2026-06-10T00-00-00Z-00000`; `test_upload_zip_starts_job` reads from it via `FAKE_FTDC_METRICS`.

**Why:** Repeated fake uploads cluttered the runs list and caused identical mongo-ftdc decoder panics on retry; real uploads (`upload20260625T131510Z`, etc.) unchanged.

---

## 2026-06-30 — Verbatim job and Phase 2 errors in UI

**What:** Phase 1 pipeline page (Modern Stitch shell), upload poll, and Phase 2 RCA show the full stored error string — no summarizing, no `detail.msg` parsing, no 2k stderr trim.

**How:** `job_error` in pipeline `page_data`; `stitch/pipeline.html` `<pre>` + poll shows `job.error`; `api-error-text.js`; Cursor provider returns full SDK JSON / raw model text; `pipeline.py` / `hatchet.py` store full stderr.

**Why:** Retries looked identical because the UI hid the real failure (e.g. Docker daemon down) behind generic labels or parsed Cursor messages.

---

## 2026-06-30 — Cursor sandbox off when MCP on (superseded)

**What:** Earlier attempt: sandbox off only when MCP on; clarify kept sandbox on.

**How:** `enabled=not include_mcp` — replaced same day by “Cursor sandbox always off” above.

**Why:** Superseded — clarify phase still hit sandbox unsupported error.

---

## 2026-06-29 — Tool trace MCP classify uses Cursor SDK name

**What:** Agent Tool Activity MCP badge covers all Cursor MCP calls, including operator connectors like `dummy_test`.

**How:** `classify_tool_category()` returns `"mcp"` when the SDK `tool_name` is `"mcp"` (raw name, not decoded display); classification no longer calls `resolve_tool_identity()`. Display names still use resolve. Test for `dummy_test`/`echo`.

**Why:** Cursor wraps every MCP invocation as tool `"mcp"` with connector in args; allowlisting inner tool names mis-bucketed unknown connectors as `other`.

---

## 2026-06-29 — Phase A lists all retrievable metric names

**What:** Investigation (Phase A) prompt includes every unique metric from `fallback_retrieval_index.json`, not only mongo-ftdc assessment highlights.

**How:** `unique_metrics_from_index()` in `fallback_tools.py`; `assemble_prompt_context()` adds `retrievable_metrics`; `build_investigate_user_message()` renders the list and softens tier-1 anchoring text.

**Why:** Highlighted metrics alone could anchor the agent; full catalog matches MCP `list_fallback_metrics` so operators can explore beyond Simagix priorities.

---

## 2026-06-29 — Cursor autoReview for headless MCP (sandbox on)

**What:** Phase 2 Cursor runs with MCP servers use `LocalAgentOptions(auto_review=True)` so MCP tool calls are not rejected for missing interactive approval.

**How:** `providers/cursor/provider.py` — `auto_review=True` when `include_mcp`; sandbox stays enabled.

**Why:** Local SDK runs cannot prompt for MCP approval; users saw all MCP calls rejected with sandbox policy error.

---

## 2026-06-29 — Local test HTTP MCP connector

**What:** Streamable HTTP test MCP server on `http://127.0.0.1:8765/mcp` plus `local-test-http` registry entry (fill `Authorization` header yourself).

**How:** `test_mcp_http_server.py`; `_validate_http_mcp_url` allows `http://127.0.0.1` / `localhost` for local test endpoints.

**Why:** Operators can verify HTTP MCP wiring (ADK/Cursor tool trace) without a remote HTTPS endpoint.

---

## 2026-06-29 — Local test MCP connector (ping/echo)

**What:** Shipped `test_mcp_server.py` stdio MCP plus `test-ping-mcp` WorkArea template.

**How:** `simagix-workspace/operator/mcp_connectors/test_mcp_server.py`; `STDIO_TEMPLATES["test-ping-mcp"]`.

**Why:** Stdio MCP wiring check without GitHub or remote HTTP.

---

## 2026-06-29 — Legacy profiler citations stripped on report load

**What:** Old `latest_report.json` files with `evidence_citations.source_type=profiler` load without Pydantic validation errors.

**How:** `load_persisted_rca_report()` applies `_normalize_rca_payload` when reading disk; `session.load_persisted_report()` uses it.

**Why:** Profiler removal dropped `profiler` from the schema; existing Gemini/Cursor reports on disk still cited profiler and broke report HTML view.

---

## 2026-06-29 — Gemini API 503 mapped to HTTP 503 (not ASGI crash)

**What:** Gemini `ServerError` / upstream API failures return JSON 503/429/502 from Phase 2 endpoints instead of unhandled ASGI exceptions.

**How:** `gemini_errors.py` + `except` handlers on `/phase2/run`, `/clarify`, `/chatbot/messages`.

**Why:** Google returned 503 UNAVAILABLE (model high demand); operators need a clear retry message.

---

## 2026-06-29 — Remove MongoDB profiler feature entirely

**What:** Removed profiler upload API, `get_profiler_samples` MCP tool, `profiler_insights` schema field, and chatbot profiler JSON auto-upload.

**How:** Deleted `profiler.py`; stripped MCP/prompts/mock/UI/tests; legacy `profiler_insights` stripped on parse.

**Why:** User requested full removal — profiler calls caused Gemini failures and are out of scope.

---

## 2026-06-29 — Profiler MCP call optional in Phase 2 prompts

**What:** Investigation and final RCA prompts no longer require `get_profiler_samples` (or other evidence tools) when MCP is unavailable.

**How:** `prompts.py` — optional profiler check; fallback tools only when registered.

**Why:** Gemini ADK crashed when MCP toolsets failed but prompt forced `get_profiler_samples` call.

---

## 2026-06-29 — Cursor SDK sandbox enabled

**What:** Cursor agent built-in tools (`read`/`grep`/`shell`) run with `SandboxOptions(enabled=True)` for all phases.

**How:** `cursor/provider.py` — sandbox on; MCP servers unchanged (separate subprocesses).

**Why:** User testing tighter filesystem boundary; prompts still steer writes to `chatbot_scratch/`. May limit absolute-path reads outside cwd — use MCP for evidence.

---

## 2026-06-29 — Stitch Phase B wizard styling (progress dots + answer area)

**What:** Clarifying-question progress dots are visible on Stitch; terracotta theme instead of green; polished answer label and textarea.

**How:** `clarify-chat-stitch.css`; `clarify-wizard--stitch` on run workspace form; stitch-specific card/answer markup in `clarify-wizard.js`.

**Why:** Dots used white-on-light (invisible); green accent clashed with Stitch palette; Bootstrap form styles looked out of place.

---

## 2026-06-29 — Phase B clarifying questions visible in Stitch run workspace

**What:** Clarifying-question wizard appears after Run RCA on Modern/Stitch run workspace (Investigation tab).

**How:** `clarify-wizard.js` toggles both HTML `hidden` and Tailwind `class="hidden"` (Stitch uses Tailwind; Classic uses attribute only).

**Why:** `showClarifyWizard` only cleared the `hidden` attribute; Stitch `#clarify-form` kept `display:none` from Tailwind.

---

## 2026-06-29 — Modern theme flash fix (Classic chrome before React shell)

**What:** Modern theme no longer flashes Classic dark navbar before the React/Stitch shell appears.

**How:** Inline head script preloads Modern CSS; `theme-modern.css` hides `#classic-chrome` when `data-app-theme=modern`; `app-theme.js` syncs shell on script load (not only DOMContentLoaded).

**Why:** Classic chrome was visible until deferred `app-theme.js` ran; user saw previous theme then current.

---

## 2026-06-29 — Unified MCP WorkArea footer on all pages

**What:** Every page uses the same footer as MCP WorkArea (Mongo Debugger + © 2026 + API link).

**How:** `stitch-nav.js` renders shared footer; `mdb-stitch-footer` CSS; `StitchFooter` React component; Classic `base.html` markup aligned.

**Why:** User requested consistent footer across all pages.

---

## 2026-06-29 — Nav: remove Documentation footer link; API only

**What:** Documentation tab removed from all footers; single working **API** link to `/docs` on Stitch pages, Classic base template, and Modern shells.

**How:** Footer cleanup in `static/stitch/*.html`; `target="_top` for iframe pages; `StitchShell` / `ModernShell` / `base.html`; pipeline footer added.

**Why:** User request — no Documentation tab; API link must work from every page.

---

## 2026-06-29 — Stitch report heading scale fix

**What:** Sub-headings (section titles, labelled blocks, finding/causal step titles) are no longer smaller than body text.

**How:** Bumped `.report-stitch-section-title`, `.report-stitch-labelled-heading`, and card `h4` sizes in `report-viewer-stitch.css`.

**Why:** User reported headings smaller than the prose below them.

---

## 2026-06-29 — Stitch report: paragraphs by default, bullets only from JSON structure

**What:** Summary, mechanism, findings prose render as normal paragraphs; bullets only for JSON arrays (`safe_fixes`, `causal_chain`, …) or strings that already contain newlines.

**How:** Removed semicolon/sentence splitting in `report-viewer.js`; `buildStitchTextBlock` newline-only rule.

**Why:** User — frontend should not invent bullet points; LLM structures content in JSON.

---

## 2026-06-29 — Stitch report: bullet lists + section order fix

**What:** Executive summary and mechanism show visible bullet points; findings/timeline split semicolon clauses; section order matches classic (summary → mechanism → timeline → findings → causal chain).

**How:** `list-style: disc` overrides Tailwind reset; safer `splitToBulletItems` (no sentence-split); labelled sub-blocks in `report-viewer.js`.

**Why:** User reported executive summary/mechanism broken — bullets were invisible and long fields rendered as paragraph walls.

---

## 2026-06-29 — Stitch report: smaller overview + bullet-first layout

**What:** Overview headline and body text are smaller; summary, mechanism, causal steps, and timeline render as bullet points instead of serif paragraphs.

**How:** `splitToBulletItems()` in `report-viewer.js`; Public Sans at `0.875rem` in `report-viewer-stitch.css`.

**Why:** User feedback — overview font too large; content should scan as points not walls of text.

---

## 2026-06-29 — Stitch report tab (Claude-like reading surface)

**What:** Modern workspace Report tab uses side nav, Lora serif body, confidence ring, causal chain, timeline, and dark log evidence blocks — matching the Stitch design paste without fake chrome.

**How:** `report-viewer-stitch.css`; `report-viewer.js` `buildReportDomStitch()` when `#report-viewer` has `report-viewer--stitch`; Report tab shell in `run_workspace.html`; `rca.js` Tailwind `hidden` class toggles for empty state.

**Why:** User provided Stitch HTML for report layout; classic Bootstrap report viewer unchanged on classic theme.

---

## 2026-06-29 — Chatbot Claude-like reading surface (Modern workspace)

**What:** Post-report chatbot uses warm cream `#FAF9F5`, white assistant cards, and dark readable prose — not grey dark-theme log styling.

**How:** `agent-chat-stitch.css` scoped to `#agent-chat-panel.agent-chat-stitch` in `run_workspace.html`.

**Why:** User reported grey muddy chatbot background; wanted Claude-like clarity.

---

## 2026-06-29 — Tool activity scroll fix (filters + table)

**What:** Horizontal/vertical scroll works on tool activity with any filter active; wheel passes to page when table has no overflow; drag-to-pan on table area.

**How:** Single `#tool-trace-scroll` container, `overscroll-behavior: auto`, flex height bounds on panel, removed nested wrap; chip row scrolls horizontally.

**Why:** User reported scroll stuck on table and broken when filters applied.

---

## 2026-06-29 — Tool activity: horizontal scroll + category filter chips

**What:** Agent tool activity table scrolls horizontally; summary chips match category badge colors; click MCP/Web/Local/Shell to filter rows (Total clears).

**How:** `tool-trace.css` chip colors + table wrap; `rca.js` filter state and click handlers (Stitch Modern only).

**Why:** User request — movable wide args column, colored headings, frontend category filter.

---

## 2026-06-29 — Remove dot-grid backgrounds (upload flow pages)

**What:** Flat cream `#FAF9F5` backgrounds on Modern upload, runs, run workspace, and pipeline — no polka-dot grid pattern.

**How:** Dropped `radial-gradient` dot grid from `run_workspace.html` and `pipeline.html`; explicit flat body on upload/runs; `mdb-modern-page` body override in `theme-modern.css`.

**Why:** User request — dot pattern on upload flow pages.

---

## 2026-06-29 — Agent tool activity tab (Stitch theme + row hover)

**What:** Tool activity tab matches Modern cream/clay theme; summary chips; hovered row lifts with shadow.

**How:** `tool-trace.css`, stitch markup in `run_workspace.html`, `rca.js` stitch-aware badges and row classes.

**Why:** User reported blunt table that did not blend with theme; wanted active row to pop on hover.

---

## 2026-06-29 — Run workspace Phase A/B/C rail (Modern iframe)

**What:** Phase progress rail on `/runs/{id}` shows track, fill, and node states in Modern theme.

**How:** New `frontend/static/css/phase-rail.css` (Stitch light theme); linked from `run_workspace.html` — JS was already loaded but `motion.css` never reached the iframe.

**Why:** User reported individual run rail not working in Modern shell.

---

## 2026-06-29 — Upload page pipeline rail + runs table polish

**What:** “What happens next” vertical timeline on `/upload` shows the connecting rail; runs table View link is always visible; footer API links point to `/docs`.

**How:** Explicit `.pipeline-rail-line` CSS in `upload.html` (replaces broken Tailwind `before:` pseudo); step labels aligned to Phase 1 + Phase 2 A/B/C; `runs.html` View link + API href; `STITCH_ASSET_V` bump.

**Why:** User reported uploads/upload page rail not rendering; hover-only View was easy to miss.

---

## 2026-06-29 — Skill WorkArea Modern Stitch page

**What:** `/skill-workarea` in Modern theme uses Stitch HTML iframe with shared nav, skills table, and ZIP upload form wired to `skill-workarea.js`.

**How:** `frontend/static/stitch/skill_workarea.html`, `SkillWorkareaPage.tsx`, table + tab support in `skill-workarea.js` (mirrors MCP WorkArea pattern).

**Why:** User request — same Modern treatment as MCP WorkArea.

---

## 2026-06-29 — MCP WorkArea Modern Stitch page

**What:** `/mcp-workarea` in Modern theme uses Stitch HTML iframe with shared `/runs` nav, connector table, and configure-new form wired to `mcp-workarea.js`.

**How:** `frontend/static/stitch/mcp_workarea.html`, `McpWorkareaPage.tsx`, table + tab support in `mcp-workarea.js`.

**Why:** User Stitch paste; replace Classic-only fallback with full Modern workarea.

---

## 2026-06-29 — Fix stale Modern UI cache (Stitch iframes + nav script)

**What:** Nav and Stitch page updates now load after refresh; browsers were caching iframe HTML and `stitch-nav.js` without cache busting.

**How:** `stitchAssets.ts` version query on iframe `src`; `?v=` on stitch-nav assets; `MODERN_ASSET_V` in `app-theme.js`; `FrontendStaticFiles` sends `Cache-Control: no-cache` for stitch/modern HTML and nav assets.

**Why:** User reported UI not refreshing after nav changes.

---

## 2026-06-29 — Shared Stitch nav (matches /runs on every page)

**What:** One nav bar across all Modern Stitch pages — same markup as `/runs`, no Home tab; brand links home.

**How:** `frontend/static/js/stitch-nav.js` + `stitch-nav.css`; mount point on home, runs, upload, run workspace, pipeline; `StitchShell.tsx` aligned.

**Why:** User request — nav was inconsistent per page due to duplicate inline markup and theme tokens.

---

## 2026-06-29 — Consistent Modern nav: brand links home, wider chatbot

**What:** All Stitch pages drop the Home nav link; bug icon + “Mongo Debugger” brand links to `/`. Chatbot tab uses full content width.

**How:** `home.html`, `runs.html`, `upload.html`, `run_workspace.html`, `pipeline.html`, `StitchShell.tsx`; chatbot panel `max-w-*` removed in `run_workspace.html`.

**Why:** User request for consistent navbar and wider chat surface.

---

## 2026-06-29 — Run workspace: separate Chatbot and Agent tool activity tabs

**What:** Modern run workspace has five tabs — Evidence, Investigation, Report, Agent tool activity, Chatbot — instead of bundling tool trace with Investigation and chat with Report.

**How:** `frontend/static/stitch/run_workspace.html` tab layout; `switchTab` refreshes tool trace and chat when those tabs are opened.

**Why:** User request for dedicated surfaces for live MCP tool calls vs post-report chat.

---

## 2026-06-29 — Modern shell routing fallbacks (pipeline + unknown page fix)

**What:** “This page is not in the Modern shell yet” no longer appears for run workspace, Phase 1 pipeline, or stale `page: "results"` payloads.

**How:** `resolveModernPage()` in `pageData.ts` maps `results` → `run_workspace` and infers page from URL; `PipelinePage` + `stitch/pipeline.html`; `run_pipeline.html`, MCP/Skill templates emit `mdb-modern-page` + `page_data`.

**Why:** Users on Modern theme hit fallback when `page_data` was missing, legacy, or on `/runs/{id}/pipeline` before export completed.

---

## 2026-06-29 — Run workspace Stitch UI (full Phase 2 shell)

**What:** Modern `/runs/{id}` uses full RCA workspace: phase rail, Evidence (Hatchet + Grafana), Investigation (Run RCA, MCP panel, 10-Q wizard, tool trace), Report + chatbot.

**How:** `frontend/static/stitch/run_workspace.html` (glass + bug nav); iframe via `RunWorkspacePage.tsx`; reuses `rca.js`, `clarify-wizard`, `report-viewer`, `agent-chat`, `grafana.js`. `page_data` extended on `run_detail.html`.

**Why:** Replace thin read-only Results page with real interactive workspace; user Stitch paste cleaned to match product structure.

---

## 2026-06-29 — Runs page literal Stitch HTML + iframe hydration

**What:** Modern `/runs` loads Stitch runs HTML via iframe; table and stat cards filled from server `page_data.runs`.

**How:** `frontend/static/stitch/runs.html`; `RunsPage.tsx` iframe; script reads parent `#mdb-page-data`. Nav wired with `target="_top`.

**Why:** Same copy-paste fidelity as home/upload; real catalog data instead of placeholder rows.

---

## 2026-06-29 — Upload page: remove run label and notes fields

**What:** Run label and notes inputs removed from Modern upload UI.

**How:** Deleted fields from `frontend/static/stitch/upload.html` (not wired to API).

**Why:** User request; fields were display-only with no backend support.

---

## 2026-06-29 — Upload page literal Stitch HTML + iframe

**What:** Modern `/upload` loads user’s Stitch upload HTML verbatim via iframe (same pattern as home).

**How:** `frontend/static/stitch/upload.html`; `UploadPage.tsx` iframe only; `App.tsx` bypasses `StitchShell` for upload. Wired: drag-drop, `POST /simagix/uploads`, job poll, redirect on success. Nav links `target="_top`.

**Why:** Match home copy-paste fidelity; avoid React reimplementation.

---

## 2026-06-29 — Home HTML literal paste + MCP/Skill nav tabs

**What:** `frontend/static/stitch/home.html` replaced with the user’s Stitch export verbatim (hero `fade-slide-left`/`fade-slide-right`, Three.js background, buttons unchanged). Only addition: **MCP WorkArea** and **Skill WorkArea** nav links.

**How:** Full-page iframe in `HomePage.tsx`; new nav tabs use `href="/mcp-workarea"` and `href="/skill-workarea"` with `target="_top"`. All other markup matches the paste (`href="#"` on Home/Uploads/Upload/footer).

**Why:** User asked for copy-paste fidelity with WorkArea tabs only.

---

## 2026-06-29 — Home is literal Stitch HTML (no React rewrite)

**What:** Modern home loads the user’s Stitch HTML file verbatim in a full-page iframe — same Tailwind CDN, Three.js script, animations, and markup.

**How:** `frontend/static/stitch/home.html` (paste of Stitch export); `HomePage.tsx` iframe only; `target="_top"` on wired links (`/upload`, `/runs`, `/docs`). Removed React Three.js port.

**Why:** User asked to copy-paste the design, not reimplement it in React.

---

## 2026-06-29 — Stitch animated home (Three.js + scroll reveal)

**What:** Modern Home matches the updated Stitch export: full-screen hero on dark 3D background, scroll animations, flip cards, and wired CTAs.

**How:** `HomePage.tsx` from user Stitch HTML; `HomeThreeBackground.tsx` (three.js database nodes); `useScrollReveal`; nav includes MCP + Skill WorkArea; links to `/upload`, `/runs`, `/docs`, workareas.

**Why:** User provided updated Stitch home with animation — wire APIs/links without redesigning layout.

---

## 2026-06-29 — Home page matches Stitch export exactly

**What:** Modern Home and shell header/footer now mirror `.stitch/designs/home.html` markup and copy — no extra recent-runs block or rewritten bullet text.

**How:** `HomePage.tsx` copied from Stitch body sections; `StitchShell.tsx` restored simple Mongo Debugger nav (Home / Uploads / Upload) and footer text from the export.

**Why:** User asked to use the Stitch home design verbatim instead of customized React variants.

---

## 2026-06-29 — Modern Stitch shell polish and run page recovery

**What:** Fixed the Modern Stitch navigation, restored WorkArea discoverability, separated Phase 1 and Phase 2 status on the runs page, and recovered the individual run detail page from the stale live server `500`.

**How:**
- **`StitchShell.tsx`** — branded nav block with Stitch icon treatment, active pill navigation, MCP WorkArea and Skill WorkArea links.
- **`RunsTable.tsx` / `runStatus.ts`** — explicit Phase 1 decode and Phase 2 RCA columns instead of one mixed status/phase view.
- **`base.html`** — Skill WorkArea link added to Classic navigation too.
- **Dev server** — restarted the stale listener on port 8000; fresh app instance returns `200` for run detail.

**Why:** The previous Stitch wiring was visually too close to plain hyperlinks, hid key WorkArea routes, and made pipeline state ambiguous.

---

## 2026-06-27 — Stitch designs wired into Modern React shell

**What:** Modern UI now uses Google Stitch HTML layouts (Tailwind + Public Sans + Material Symbols) with live API data — not ad-hoc CSS approximations.

**How:**
- **Tailwind v4** + Stitch color tokens in `frontend/src/styles/stitch.css` (from `.stitch/designs/*.html`).
- **`StitchShell`** — fixed nav/footer from Stitch home/uploads/upload screens.
- **Pages** — `HomePage`, `RunsPage`, `UploadPage`, `ResultsPage` rebuilt from `.stitch/designs/` markup; `RunsTable` + `loadResultsData` feed real catalog and Simagix APIs.
- **Removed** DotGrid/mongo-green hero; Stitch preview images and phase sidebar from upload design.

**Why:** User asked to take Stitch designs and wire them — prior Modern shell only loosely matched Stitch tokens.

**Docs:** [CHANGELOG.md](CHANGELOG.md); `.stitch/metadata.json`.

---

## 2026-06-27 — Modern Results wired to Simagix APIs

**What:** Modern `ResultsPage` loads live tier-1 context, Phase 2 status, and latest RCA report instead of hardcoded demo metrics; Home/Runs/Upload share Claude/Stitch cream palette.

**How:**
- **`loadResultsData.ts`** — fetches `/context`, `/phase2/status`, `/phase2/reports/latest`; maps anomaly windows, activity summary, findings, and report fields into metric cards, FTDC chart, RCA block, and phase accordions.
- **`ResultsPage.tsx`** — async load with loading/error states; Download Report uses `format=pretty`; “Full RCA workspace” switches to Classic theme.
- **`run_detail.html`** — `page_data` passes only `run_id`, `selected_llm`, `upload_time_utc` (no fake ticket counts).
- **`routes.py`** — `upload_time_utc` in run detail template context.
- **`app.css` / HomePage** — Public Sans, cream `#FAF9F5`, clay accent `#C96442`.

**Why:** Demo data (128 tickets, 2024 dates) misaligned with real APIs; users need truthful Modern results and consistent navigation across Home, Uploads, Upload, and run detail.

**Docs:** [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.

---

## 2026-06-29 — Modern Analysis Results Detail view

**What:** Added a professional results and analysis detail view to the Modern React shell, generated via Stitch MCP CLI, with real-time responsive SVG charts, stat grids, RCA details, and phase accordions.

**How:**
- **Stitch generation**: Generated a high-fidelity results detail page via Stitch MCP (`generate_screen_from_text`) using project design tokens (background `#faf9f5`, accent `#C96442`, Public Sans font).
- **`ResultsPage.tsx`**: Created a modular React page for analysis detail including breadcrumbs, severity metrics, custom responsive SVG sparklines + area charts, interactive RCA timeline/causal chain, and collapsible phase sections.
- **`run_detail.html`**: Added `mdb-modern-page` class and custom JSON page data block to bootstrap `ResultsPage` in the Modern shell when modern theme is active.
- **Vite compilation**: Validated compilation of modern modules with Vite production build pipelines.

**Why:** Closing the gap in the modern user interface layout, replacing static classic views with unified modern React dashboard views.

**Docs:** [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.

---

## 2026-06-27 — Scoped reading surface (light/dark toggle)

**What:** RCA report section + post-report chatbot use a scoped Claude-like reading surface with a header toggle between warm light (`#FAF9F5`) and warm dark (`#1A1917`); rest of run page keeps Mongo dark chrome.

**How:**
- **`reading-surface.css`** — CSS variables + overrides for report viewer, chat, raw report inside `#reading-surface`.
- **`reading-surface.js`** — toggle, `localStorage` key `mdb-reading-theme`, `prefers-color-scheme` default when unset.
- **`run_detail.html`** — sun/moon button in report header; `card-body` is `#reading-surface`.
- **`agent-chat.js`** — mermaid theme follows reading surface mode.

**Why:** Mentor asked for Claude-like report/chat readability without reskinning uploads, Grafana, or the phase rail.

**Docs:** [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.

---

## 2026-06-26 — Skill WorkArea + native ADK MCP/skills

**What:** Operator Skill WorkArea (ZIP upload by slot name); all uploaded skills attach automatically on Phase A, Phase C, and chatbot. ADK uses native `McpToolset` + `SkillToolset`; custom `mcp/client.py` bridge removed.

**How:**
- **`skills/registry.py`** — pass-through zip extract to `operator/skills/{slot_name}/`, list/delete, `copy_all_to_cursor_scratch`, `build_adk_skill_toolset_all` via `load_skill_from_dir`.
- **`api/skill_workarea.py`** + **`/skill-workarea`** UI — multipart upload (name + ZIP), list, delete; nav link in base template.
- **Cursor** — `copytree` all skills to `{scratch}/.cursor/skills/`; `setting_sources=["project"]` when catalog non-empty.
- **ADK** — `to_adk_mcp_toolsets()` in `mcp/registry.py`; runner attaches `McpToolset` + optional `SkillToolset(all)` + `web_fetch`; async `close()` in `finally`.
- **Deleted** `mcp/client.py`; `build_web_fetch_tool()` moved to `web_fetch.py`.

**Why:** Skills are playbooks (not MCP tools); provider-native attachment avoids prompt injection and run-page checkbox complexity. ADK `McpToolset`/`SkillToolset` replace a custom MCP bridge we no longer need.

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md), [RCA_BACKEND.md](RCA_BACKEND.md), [DESIGN_NOTES.md](DESIGN_NOTES.md) §14.

---

## 2026-06-26 — Unified MCP + providers layout (`feat/unified-mcp-providers`)

**What:** Single MCP tool surface for Cursor and Gemini ADK; providers moved under `llm/providers/`; WorkArea `enabled_mcp_ids` wired for ADK.

**How:**
- **`mcp/`** — `specs.py`, `connectors.py`, `registry.py` (`build_mcp_server_specs`, `to_cursor_sdk_servers`), `client.py` (`ClientSessionGroup` bridge for ADK), `servers/{evidence,graylog,hatchet}.py`.
- **`providers/`** — `cursor/provider.py`, `adk/{provider,runner}.py`, `mock.py`; `service.py` imports from `providers`.
- ADK runner opens the same MCP subprocess specs as Cursor, plus in-process `web_fetch`; deleted `adk_evidence_tools.py`.
- Removed legacy shim modules; subprocess entrypoints are `python -m backend.app.simagix.llm.mcp.servers.{evidence,graylog,hatchet}`.

**Why:** One `@mcp.tool()` source of truth; operator WorkArea parity across providers; room for future OpenAI provider without duplicating tool lists.

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md), [RCA_BACKEND.md](RCA_BACKEND.md), [DESIGN_NOTES.md](DESIGN_NOTES.md) §13.18, §14.

---

## 2026-06-26 — Operator MCP WorkArea + per-run connector selection

**What:** MCP WorkArea UI and disk-backed connector registry; run page checkboxes send `enabled_mcp_ids` on Phase A and Phase C (Cursor only).

**How:**
- Registry: `{DATA_ROOT}/simagix-workspace/operator/mcp_connectors/registry.json` via `mcp/connectors.py`.
- REST: `GET/POST/DELETE /simagix/mcp-connectors` (`api/mcp_connectors.py`).
- Web: `GET /mcp-workarea` — tab 1 lists configured connectors; tab 2 creates HTTP or stdio-template (GitHub MCP) connectors.
- Run page: stateless checkboxes (no defaults except locked `simagix-evidence`); `POST /phase2/run` and `POST /phase2/clarify` accept `enabled_mcp_ids`.
- `CursorLLMProvider._mcp_config()` merges built-ins + selected user connectors via `build_user_mcp_servers()`.

**Why:** Operators need to attach optional MCPs (e.g. GitHub, remote HTTP) without editing `.env` or code; selection must be explicit per run, not persisted as defaults.

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md), [RCA_BACKEND.md](RCA_BACKEND.md), [DESIGN_NOTES.md](DESIGN_NOTES.md) §14, [CONTEXT.md](../CONTEXT.md).

---

## 2026-06-26 — PHASE2_LLM + DESIGN_NOTES: Cursor vs ADK layout, MCP client, WorkArea (v1)

**What:** Literal mentor Q&A capture for provider file organization, why ADK has extra files, MCP WorkArea Cursor-only behavior, `@mcp.tool` vs `AdkEvidenceTools`, and when an MCP client is needed.

**How:** New section **Mentor Q&A — Cursor vs Gemini ADK layout, MCP client, and WorkArea (v1)** in `PHASE2_LLM.md` (tables, diagrams, tradeoffs, interview lines). Added `DESIGN_NOTES.md` **§13.18** (Gemini ADK parallel to §13.17), §14 rows (ADK in-process tools, provider file split, unified MCP future), talking points. Expanded `RCA_BACKEND.md` Phase 2 file layout table.

**Why:** Design walkthrough content was only in chat; needed same literal capture habit as 2026-06-25 Cursor SDK Q&A for demos and future unify (ADK/OpenAI + shared MCP client).

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md), [DESIGN_NOTES.md](DESIGN_NOTES.md) §13.18, §14, [RCA_BACKEND.md](RCA_BACKEND.md) § Backend layout.

---

## 2026-06-25 — README: literal Cursor SDK → MCP runtime diagram

**What:** Replaced the abstract “RCA agent → MCP → LLM” boxes on the README architecture diagram with the actual Cursor runtime chain.

**How:** Mermaid subgraph now shows `Phase2 service.py` → `CursorLLMProvider` → `Cursor SDK Agent.create` → MCP subprocesses + Cursor Cloud tool loop. Updated intro prose and key-read callout to match (Gemini ADK noted as in-process tools).

**Why:** The prior diagram implied a separate RCA agent process calling MCP; with Cursor, the SDK spawns MCP and the cloud model never touches the bundle directly.

**Docs:** [README.md](../README.md) § Architecture (30 seconds).

---

## 2026-06-25 — PHASE2_LLM: full Cursor SDK mentor Q&A (conversation capture)

**What:** Replaced condensed agent-scope section with **Mentor Q&A — Cursor SDK agent runtime** in `PHASE2_LLM.md` — verbatim user questions + full assistant answers from the design walkthrough.

**How:** Eight Q/A blocks with exact user wording (including typos): `_best_agent_text` / `_collect_assistant_text`, MCP wiring, `AgentOptions` / `LocalAgentOptions`, built-ins, sandbox ON, env/path scopes, why `cwd` follows `include_mcp`, and where-to-write-docs meta Q&A. Includes tables, diagrams, code snippets, and one-line summaries from chat.

**Why:** User requested literal conversation capture (all questions and answers), not a summary-only section.

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md) § Mentor Q&A — Cursor SDK agent runtime.

---

## 2026-06-25 — PHASE2_LLM: agent cwd, env, sandbox scopes (Cursor SDK)

**What:** Added **Agent workspace: cwd, env, sandbox (Cursor SDK)** to `PHASE2_LLM.md` — full Q&A on where the agent can work (built-ins vs MCP vs prompts).

**How:** New section mirrors the mentor walkthrough: three scopes diagram, path table by phase, `mcp_server_env()` vars, why `cwd` follows `include_mcp` not sandbox, bugfix history (2026-06-14), built-ins vs MCP vs custom. Fixed stale DESIGN_NOTES §13 bullets (`cwd`, sandbox).

**Why:** Important debugging context was only in chat; Phase 2 operators need one canonical doc.

**Docs:** [PHASE2_LLM.md](PHASE2_LLM.md) § Agent workspace, [DESIGN_NOTES.md](DESIGN_NOTES.md) §13 Setup.

---

## 2026-06-25 — Fix Excalidraw export for excalidraw.com import

**What:** `mongo-debugger-runtime-flow.excalidraw.json` now opens on excalidraw.com instead of showing “invalid file”.

**How:** Regenerated the file in the official Excalidraw schema (`type`, `source`, `files`, full element properties). The prior MCP export omitted required root fields and used a non-portable element shape.

**Why:** Users opening the diagram on excalidraw.com need a valid `.excalidraw` JSON document, not the MCP server’s internal export format.

**Docs:** [mongo-debugger-runtime-flow.excalidraw.json](mongo-debugger-runtime-flow.excalidraw.json), [README.md](../README.md).

---

## 2026-06-25 — README: single runtime flow diagram

**What:** README **Architecture (30 seconds)** now shows one runtime flow diagram only; removed the earlier simplified diagram and mentor/manager wording.

**How:** Kept the concrete runtime Mermaid view (Docker Grafana stack, agent → MCP, UI output routing). Renamed Excalidraw export to `mongo-debugger-runtime-flow.excalidraw.json` and updated its title.

**Why:** GitHub README should present one clear architecture picture without duplicate diagrams or mentor/manager labels.

**Docs:** [README.md](../README.md) § Architecture (30 seconds), [mongo-debugger-runtime-flow.excalidraw.json](mongo-debugger-runtime-flow.excalidraw.json).

---

## 2026-06-25 — README mentor flow diagram v2 + cleaner Excalidraw export

**What:** Appended a concrete runtime mentor/manager flow to the README and replaced the cluttered Excalidraw export with a cleaner lane-based diagram.

**How:** README now has two views: the original role-lane Mermaid diagram plus **Mentor/Manager Flow (Concrete Runtime)** showing Grafana as Docker (`:3030` + FTDC API `:5408`), RCA agent → MCP tool calls (not LLM → MCP), and Grafana loading uploaded `diagnostic.data` via `/grafana/dir`. Mermaid render spacing/font settings make the GitHub view larger, and output arrows now return to the UI instead of implying the system talks directly to the user after upload. Excalidraw MCP rebuilt the visual as five color-coded lanes with short labels (36 elements vs 71).

**Why:** Mentor/manager walkthrough needed accurate runtime semantics without diagram clutter.

**Docs:** [README.md](../README.md) § Architecture (30 seconds), [mongo-debugger-mentor-flow.excalidraw.json](mongo-debugger-mentor-flow.excalidraw.json).

---

## 2026-06-25 — README conceptual flow diagram + CONTEXT.md glossary

**What:** Added role-lane Mermaid flow diagrams to the README **Architecture (30 seconds)** section (mentor/manager audience), exported an editable Excalidraw version of the concrete runtime flow, and added a new root `CONTEXT.md` ubiquitous-language glossary.

**How:** The first diagram groups boxes by role left-to-right — Input → Backend (FastAPI) → Deterministic analysis (mongo-ftdc + Hatchet) → Evidence bundle → Reasoning (RCA agent + MCP + LLM providers) → Outputs (report/chatbot + Grafana) — with the deterministic-vs-reasoning split made explicit and pipe-separated capability labels. A second concrete runtime diagram clarifies that Grafana is a Docker stack (`:3030` + FTDC API `:5408`), the RCA agent calls MCP while the LLM provider only returns model output, and Grafana loads the run's uploaded `diagnostic.data` path through `/grafana/dir` rather than reading the evidence bundle. `CONTEXT.md` defines the project's terms (Run, evidence bundle, tier-1 findings, RCA agent, LLM slot, etc.) per the domain-modeling format.

**Why:** A `/grill-with-docs` session asked for a clear, non-low-level flow picture for explaining the system to a mentor/manager, plus a glossary so the diagram's terms are unambiguous and a more precise view for answering implementation-flow questions.

**Docs:** [README.md](../README.md) § Architecture (30 seconds), [mongo-debugger-mentor-flow.excalidraw.json](mongo-debugger-mentor-flow.excalidraw.json), [CONTEXT.md](../CONTEXT.md).

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
