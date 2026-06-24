# Mongo Debugger Documentation

Single documentation index for the **AI-Powered FTDC Analyzer**. All project docs live in this folder.

## Quick start

### Prerequisites

```bash
brew install docker docker-compose colima
colima start --cpu 4 --memory 8 --disk 60
uv python install 3.11
uv sync --extra dev --extra llm
```

Clone Simagix toolchain sources (required for upload pipeline; not in git):

```bash
./scripts/setup-simagix-repos.sh
cd simagix-workspace/repos/mongo-ftdc && ./build.sh docker && cd -
```

See [Operations](OPERATIONS.md) for Colima, upload, and Grafana.

```bash
# Mac: Docker via Colima — once per session (upload pipeline + Grafana need Docker)
colima start --cpu 4 --memory 8

uv run uvicorn backend.app.main:app --reload --port 8000
```

Open **http://localhost:8000** — upload FTDC data or browse existing runs.

### Demo and tests

```bash
./scripts/demo.sh
uv run pytest backend/tests -q
```

Manual pipeline from disk (Docker required): see [Operations](OPERATIONS.md#pipeline-from-disk).

---

## Documentation map

### Core guides

| Document | Audience | Description |
|----------|----------|-------------|
| [**Changelog**](CHANGELOG.md) | Everyone | What we improved, how, and why (living log) |
| [**Doc maintenance**](DOC_MAINTENANCE.md) | Agents & contributors | Which doc to update for each type of change |
| [**Project Status**](PROJECT_STATUS.md) | Everyone | Spec scorecard, milestones, future work |
| [Architecture](ARCHITECTURE.md) | Engineers | **High-level system map** (steps 1–7), zoom diagrams, tech stack; [interactive canvas](/Users/prateek.agarwal/.cursor/projects/Users-prateek-agarwal-Documents-Intern-Projects-Mongo-Debugger/canvases/mongo-debugger-architecture.canvas.tsx) |
| [Operations](OPERATIONS.md) | Operators | Setup, upload, pipeline, Grafana, troubleshooting |
| [RCA Backend API](RCA_BACKEND.md) | Integrators | REST endpoints, backend module layout |
| [Phase 2 LLM](PHASE2_LLM.md) | AI engineers | Cursor agent, MCP tools, 3-phase RCA |
| [Design Notes](DESIGN_NOTES.md) | Demo / interview | Why the system is built this way; **§13 theory Q&A**, **§14 tradeoffs (why not LangGraph/Hindsight/etc.)** |

### Simagix workspace and evidence

| Document | Description |
|----------|-------------|
| [Simagix Workspace](SIMAGIX_WORKSPACE.md) | Folder layout, **RunWorkspace adapter**, **symlinks**, **on-disk JSON catalog**, cloned repos, inputs |
| [Simagix Toolchain](SIMAGIX_TOOLCHAIN.md) | mongo-ftdc, Hatchet, Keyhole, Maobi roles |
| [Export Contract](export_contract.md) | Tiered evidence bundle schema (`v1.0.0`) |
| [Evidence Guide](EVIDENCE_GUIDE.md) | Why the bundle is optimized for LLM context |
| [Fallback Index](FALLBACK_INDEX.md) | `fallback_retrieval_index.json` field reference |

### Reference and research

| Document | Description |
|----------|-------------|
| [FTDC Reference](FTDC_REFERENCE.md) | Deep FTDC theory, mongo-ftdc research, integration ideas |
| [Previous Works](PREVIOUS_WORKS.md) | Prior related projects and notes |
| [Superlog Analysis](SUPERLOG_ANALYSIS.md) | Lessons from Superlog for Mongo Debugger |

---

## What this project does

```text
Upload / disk → mongo-ftdc (deterministic) → tiered evidence bundle
  → FastAPI orchestration + Bootstrap UI (frontend/)
  → Cursor SDK / Gemini ADK agent + MCP evidence tools
  → RCA report (JSON + HTML) + post-report chatbot + Grafana charts
```

For current implementation status, see [Project Status](PROJECT_STATUS.md) — do not rely on status tables inside [FTDC Reference](FTDC_REFERENCE.md) (historical notes).

## Recommended reading order

1. [Changelog](CHANGELOG.md) — recent improvements
2. [Project Status](PROJECT_STATUS.md)
3. [Architecture](ARCHITECTURE.md)
4. [Operations](OPERATIONS.md)
5. [RCA Backend API](RCA_BACKEND.md) and [Phase 2 LLM](PHASE2_LLM.md)
6. [Design Notes](DESIGN_NOTES.md) before a demo or interview

## Repository layout

```text
Mongo Debugger/
  docs/                         All documentation (this index)
  frontend/                     Bootstrap UI (templates + static; swappable)
  backend/                      FastAPI APIs + web route wiring
  scripts/demo.sh               One-command demo
  simagix-workspace/
    uploads/<run_id>/           One tree per upload (Option A)
      inputs/diagnostic.data/      Web upload FTDC
      phase1/mongo-ftdc/          Tiered mongo-ftdc export bundle
      phase1/jobs|queue/        Pipeline worker state
      phase2/llm/               RCA session artifacts
    reports/mongo-ftdc/         Human HTML + console reports
    scripts/                    Docker pipeline wrappers
    repos/                      Cloned simagix tool sources
  tmp/                          Default FTDC input for CLI (gitignored)
```

See [SIMAGIX_WORKSPACE.md](SIMAGIX_WORKSPACE.md) for full layout.

## Evidence bundle (quick reference)

Each export under `simagix-workspace/uploads/<run_id>/phase1/mongo-ftdc/`:

```text
tier_1_analyzed   → primary LLM input (findings, anomalies, assessment)
tier_2_normalized → fallback tool retrieval (time series, repl lags)
tier_3_raw        → forensic fallback (opt-in)
```

Start with `manifest.json` and `llm/executive_context.json`. Use MCP fallback tools for proof — do not load entire normalized files into LLM context. Full schema: [export_contract.md](export_contract.md).
