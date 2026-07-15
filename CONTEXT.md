# Mongo Debugger

Turns a MongoDB `diagnostic.data` capture into an evidence-backed root-cause report. The defining principle: **deterministic tools find the health issues; the LLM only explains them** — it never re-derives findings from raw metrics.

## Language

### Inputs

**Run**:
One upload and everything derived from it — inputs, evidence bundle, RCA reports, chatbot transcript — addressed by a `run_id`.
_Avoid_: job, session, case

**diagnostic.data**:
The raw FTDC capture a user uploads (a directory, zipped). The single source of truth for an analysis.
_Avoid_: metrics dump, ftdc files

**FTDC**:
MongoDB's Full-Time Diagnostic Data Capture format. The thing we decode; not a tool.

### Deterministic analysis

**mongo-ftdc**:
The Simagix Docker tool that decodes FTDC, scores health, flags anomaly windows, and writes the tiered evidence bundle. The authority on *what* is wrong.
_Avoid_: the analyzer, the decoder

**Hatchet**:
The Simagix Docker tool that parses an uploaded `mongod.log` into SQLite and a compact log summary for reasoning.
_Avoid_: log parser

**Pipeline worker**:
The background process that pulls upload jobs off a file queue on `DATA_ROOT` and runs the Docker tools, off the API process.
_Avoid_: background job, task runner

### Evidence

**Evidence bundle**:
The tiered JSON that `mongo-ftdc` writes for a run — the only thing reasoning is allowed to read.
_Avoid_: export, output, results

**Tier-1 findings**:
Authoritative deterministic conclusions (scores, anomalies, diagnoses). The LLM treats these as given.
_Avoid_: summary, highlights

**Tier-2 metric slices**:
On-demand metric detail the agent fetches via MCP to support tier-1 findings — never a raw full dump.
_Avoid_: raw metrics, full export

### Reasoning

**RCA agent**:
The 3-phase LLM workflow — **A investigate** (pull evidence via MCP), **B clarify** (ask the operator up to 10 questions), **C final report** — also called **Phase 2**.
_Avoid_: the model, the bot, Phase 2 (informal only)

**MCP evidence tools**:
The Model Context Protocol *servers* we implement so the agent retrieves metrics, logs, Hatchet data, and trusted `web_fetch`. We provide servers, not the agent runtime.
_Avoid_: plugins, functions

**MCP connector**:
An operator-configured optional MCP (HTTP URL or stdio template) stored in the operator registry and enabled per run via checkboxes — distinct from built-in servers like `simagix-evidence`.
_Avoid_: plugin, integration

**MCP WorkArea**:
The `/mcp-workarea` UI for listing, creating, and deleting MCP connectors. Run-page checkboxes only send ids at RCA click time; no saved defaults.

**LLM provider**:
A swappable reasoning backend filling one **slot** — `cursor` (Cursor Cloud), `gemini` (Gemini ADK), or `mock`. Each slot keeps its own artifacts; no cross-contamination.
_Avoid_: model, engine

### Outputs

**RCA report**:
The final per-run deliverable — JSON plus an HTML view, with citations back to evidence — followed by an optional post-report **chatbot**.
_Avoid_: result, analysis, summary

**Grafana**:
Grafana OSS (Helm pod) showing a run's metrics via the API SimpleJSON datasource over Postgres. Opens in a new tab with `var-run_id`.
_Avoid_: dashboards service, charts server, FTDC API load
