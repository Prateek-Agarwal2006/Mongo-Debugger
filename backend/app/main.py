from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.catalog import router as catalog_router
from backend.app.api.grafana_simple import router as grafana_simple_router
from backend.app.api.mcp_connectors import router as mcp_connectors_router
from backend.app.api.phase2 import router as phase2_router
from backend.app.api.simagix_runs import router as simagix_runs_router
from backend.app.api.skill_workarea import router as skill_workarea_router
from backend.app.api.upload import router as upload_router

# ponytail: local Vite proxies /static here; Kind nginx serves its own copy.
_FRONTEND_STATIC = Path(__file__).resolve().parents[2] / "frontend" / "static"


def create_app() -> FastAPI:
    """API-only app — UI is the nginx SPA (Merged Dev LD5)."""
    app = FastAPI(
        title="MongoDB FTDC Analyzer",
        version="0.2.0",
        description="AI-powered FTDC analysis: deterministic evidence pipeline + agentic RCA.",
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(simagix_runs_router)
    app.include_router(catalog_router)
    app.include_router(phase2_router)
    app.include_router(mcp_connectors_router)
    app.include_router(skill_workarea_router)
    app.include_router(upload_router)
    app.include_router(grafana_simple_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if _FRONTEND_STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(_FRONTEND_STATIC)), name="static")

    return app


app = create_app()
