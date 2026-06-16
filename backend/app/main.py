from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.grafana_routes import router as grafana_router
from backend.app.api.phase2 import router as phase2_router
from backend.app.api.simagix_runs import router as simagix_runs_router
from backend.app.api.upload import router as upload_router
from backend.app.web.api_docs import router as api_docs_router
from backend.app.web.routes import router as web_router

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND_STATIC = _REPO_ROOT / "frontend" / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="MongoDB FTDC Analyzer",
        version="0.2.0",
        description="AI-powered FTDC analysis: deterministic evidence pipeline + agentic RCA.",
        docs_url=None,
        redoc_url=None,
    )
    app.include_router(simagix_runs_router)
    app.include_router(phase2_router)
    app.include_router(upload_router)
    app.include_router(grafana_router)
    app.include_router(web_router)
    app.include_router(api_docs_router)

    if _FRONTEND_STATIC.is_dir():
        app.mount("/static", StaticFiles(directory=str(_FRONTEND_STATIC)), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
