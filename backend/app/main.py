from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.grafana_routes import router as grafana_router
from backend.app.api.phase2 import router as phase2_router
from backend.app.api.simagix_runs import router as simagix_runs_router
from backend.app.api.upload import router as upload_router
from backend.app.web.routes import router as web_router

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="MongoDB FTDC Analyzer",
        version="0.2.0",
        description="AI-powered FTDC analysis: deterministic evidence pipeline + agentic RCA.",
    )
    app.include_router(simagix_runs_router)
    app.include_router(phase2_router)
    app.include_router(upload_router)
    app.include_router(grafana_router)
    app.include_router(web_router)

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
