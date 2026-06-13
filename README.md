# Mongo Debugger

**AI-powered MongoDB FTDC analyzer** — upload `diagnostic.data`, run deterministic analysis with [simagix/mongo-ftdc](https://github.com/simagix/mongo-ftdc), then generate **agentic root-cause reports** via a 3-phase LLM workflow (Cursor SDK + MCP evidence tools).

```text
Upload → Docker pipeline → tiered evidence bundle → Web UI + FastAPI
       → Phase A: investigate (MCP) → Phase B: clarify → Phase C: final RCA
       → JSON/HTML report + optional Grafana charts
```

---

## Features

| Area | What you get |
|------|----------------|
| **Deterministic lab** | mongo-ftdc diagnosis, assessment scores, anomaly windows, tiered LLM export |
| **Web app** | Upload `.zip`/`.tar.gz`, browse runs, RCA panel, Grafana links |
| **Agentic RCA** | Investigation → up to 10 clarifying questions → final report with citations |
| **Evidence-first** | Tier-1 findings are authoritative; LLM fetches metric slices via MCP, not raw dumps |
| **Optional signals** | Profiler upload, Graylog MCP, Grafana dashboards |

**Status:** See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) · **Changelog:** [docs/CHANGELOG.md](docs/CHANGELOG.md)

---

## Quick start

### 1. Prerequisites

- **macOS or Linux**
- [Docker](https://docs.docker.com/get-docker/) — on Mac, [Colima](https://github.com/abiosoft/colima) is recommended
- **Python 3.11** and [uv](https://docs.astral.sh/uv/)

```bash
brew install docker docker-compose colima   # Mac
colima start --cpu 4 --memory 8 --disk 60
uv python install 3.11
```

### 2. Clone and install

```bash
git clone https://github.com/Prateek-Agarwal2006/Mongo-Debugger.git mongo-debugger
cd mongo-debugger
uv sync --extra dev --extra llm
cp .env.example .env   # optional: set CURSOR_API_KEY for live Phase 2
```

### 3. Simagix toolchain (Docker pipeline)

```bash
./scripts/setup-simagix-repos.sh
cd simagix-workspace/repos/mongo-ftdc && ./build.sh docker && cd -
```

This builds the `simagix/ftdc` image used by the upload pipeline.

### 4. Run the app

```bash
colima start --cpu 4 --memory 8   # if not already running
uv run uvicorn backend.app.main:app --reload --port 8000
```

Open **http://localhost:8000** → **Upload** or browse the included test run `phase1test20260609T133314Z`.

### 5. Tests and demo

```bash
uv run pytest backend/tests -q
./scripts/demo.sh   # requires server on :8000
```

**Mock RCA** (no API key): enable “Force mock” on the run page, or pass `"force_mock": true` to Phase 2 APIs.

---

## Architecture (30 seconds)

| Layer | Role |
|-------|------|
| **mongo-ftdc** (Docker) | Decode FTDC, score, diagnose, export tiered bundle |
| **FastAPI backend** | Upload jobs, REST/MCP evidence access, web UI |
| **Cursor SDK** | Agent runtime — tool loop (ReAct); we implement MCP **servers** only |
| **Phase 2** | 3-step RCA: investigate → ask operator once → final report |

Deep dive: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Design rationale: [docs/DESIGN_NOTES.md](docs/DESIGN_NOTES.md) (§13 theory Q&A)

---

## Repository layout

```text
backend/app/              FastAPI, web UI, Phase 2 LLM, Grafana integration
docs/                     Full documentation index
scripts/                  demo.sh, setup-simagix-repos.sh
simagix-workspace/
  exports/mongo-ftdc/     Tiered evidence bundles (test fixture committed)
  scripts/                Docker pipeline wrappers
  repos/                  Cloned simagix tools (gitignored — run setup script)
```

---

## Configuration

| Variable | Purpose |
|----------|---------|
| `CURSOR_API_KEY` | Live Phase 2 agent (Cursor SDK) |
| `CURSOR_MODEL` | Default `composer-2.5` |
| `PHASE2_*_MAX_TOOL_CALLS` | MCP retrieval budget per phase |
| `GRAYLOG_*` | Optional log search in investigation |

See [.env.example](.env.example) and [docs/OPERATIONS.md](docs/OPERATIONS.md).

---

## Documentation

| Doc | Description |
|-----|-------------|
| [**docs/README.md**](docs/README.md) | **Documentation hub** — start here |
| [OPERATIONS.md](docs/OPERATIONS.md) | Colima, upload, pipeline, Grafana, troubleshooting |
| [PHASE2_LLM.md](docs/PHASE2_LLM.md) | Cursor agent, MCP tools, 3-phase flow |
| [RCA_BACKEND.md](docs/RCA_BACKEND.md) | REST API reference |
| [export_contract.md](docs/export_contract.md) | Evidence bundle schema |

**Contributors / agents:** [AGENTS.md](AGENTS.md) · [docs/DOC_MAINTENANCE.md](docs/DOC_MAINTENANCE.md)

---

## License

Intern project — see repository owner for licensing. Upstream Simagix tools have their own licenses in `simagix-workspace/repos/`.
