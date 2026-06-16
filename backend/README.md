# Backend

FastAPI application for the Mongo Debugger web UI, upload jobs, Grafana integration, and Phase 2/3 agentic RCA.

**UI assets** live in [`../frontend/`](../frontend/) (templates + static). **Documentation:** [docs/README.md](../docs/README.md) — start with [Operations](../docs/OPERATIONS.md) and [RCA Backend API](../docs/RCA_BACKEND.md).

```bash
colima start --cpu 4 --memory 8   # Mac: if using upload pipeline or Grafana
uv sync --extra dev --extra llm
uv run uvicorn backend.app.main:app --reload --port 8000
```
