from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from backend.app.api.grafana_routes import router as grafana_router
from backend.app.api.mcp_connectors import router as mcp_connectors_router
from backend.app.api.skill_workarea import router as skill_workarea_router
from backend.app.api.phase2 import router as phase2_router
from backend.app.api.simagix_runs import router as simagix_runs_router
from backend.app.api.upload import router as upload_router
from backend.app.web.api_docs import router as api_docs_router
from backend.app.web.routes import router as web_router

from backend.app.core.run_workspace import repo_root

_REPO_ROOT = repo_root()
_FRONTEND_STATIC = _REPO_ROOT / "frontend" / "static"


def _static_should_disable_cache(path: str) -> bool:
    """Stitch iframes and Modern bundle — avoid stale nav/UI during local dev."""
    if path.endswith(".html"):
        return True
    if path.startswith("stitch/"):
        return True
    if path.startswith("modern/"):
        return True
    if path in (
        "js/stitch-nav.js",
        "css/stitch-nav.css",
        "js/app-theme.js",
        "css/phase-rail.css",
        "js/phase-rail.js",
        "css/tool-trace.css",
        "js/rca.js",
        "css/agent-chat-stitch.css",
    ):
        return True
    return False


class FrontendStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if _static_should_disable_cache(path):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response


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
    app.include_router(mcp_connectors_router)
    app.include_router(skill_workarea_router)
    app.include_router(upload_router)
    app.include_router(grafana_router)
    app.include_router(web_router)
    app.include_router(api_docs_router)

    if _FRONTEND_STATIC.is_dir():
        app.mount(
            "/static",
            FrontendStaticFiles(directory=str(_FRONTEND_STATIC)),
            name="static",
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> FileResponse:
        return FileResponse(_FRONTEND_STATIC / "unnamed.png", media_type="image/png")

    return app


app = create_app()
