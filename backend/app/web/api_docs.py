from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.app.web.routes import templates

router = APIRouter(tags=["web-ui"])


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
def swagger_ui(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "swagger_ui.html", {})


@router.get("/redoc", include_in_schema=False, response_class=HTMLResponse)
def redoc_ui(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "redoc_ui.html", {})
