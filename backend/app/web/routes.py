from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import get_run_workspace, repo_root
from backend.app.jobs.store import job_store
from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.llm.llm_paths import LLM_FOLDER_NAMES
from backend.app.simagix.llm.service import list_run_llm_sessions, llm_provider_options
from backend.app.simagix.llm.session import phase2_session_store
from backend.app.simagix.tool_usage import resolve_tool_usage

router = APIRouter(tags=["web-ui"])

_REPO_ROOT = repo_root()
_TEMPLATES_DIR = _REPO_ROOT / "frontend" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_LLM_LABELS = {
    "mock": "Mock",
    "cursor": "Cursor SDK",
    "gemini": "Gemini ADK",
}


def _list_run_ids() -> list[str]:
    return get_run_workspace().list_run_ids()


def _llm_context_options(settings) -> list[dict[str, object]]:
    return [
        {"id": "mock", "label": _LLM_LABELS["mock"], "available": True},
        {
            "id": "cursor",
            "label": _LLM_LABELS["cursor"],
            "available": bool(settings.cursor_api_key),
        },
        {
            "id": "gemini",
            "label": _LLM_LABELS["gemini"],
            "available": bool(settings.google_api_key),
        },
    ]


def _default_selected_llm(sessions: list[dict[str, object]]) -> str:
    for entry in sessions:
        if entry.get("has_report") or entry.get("status") not in {None, "not_started"}:
            llm = entry.get("llm")
            if llm in LLM_FOLDER_NAMES:
                return str(llm)
    return "mock"


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "home.html",
        {"runs": _list_run_ids(), "jobs": [job.to_dict() for job in job_store.list_recent(10)]},
    )


@router.get("/runs", response_class=HTMLResponse)
def runs_list(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "runs.html", {"runs": _list_run_ids()})


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str, llm: str | None = None) -> HTMLResponse:
    workspace = get_run_workspace()
    exports = workspace.exports_dir(run_id)
    if not (exports / "manifest.json").exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    settings = get_settings()
    llm_sessions = list_run_llm_sessions(workspace.root, run_id)
    selected_llm = llm if llm in LLM_FOLDER_NAMES else _default_selected_llm(llm_sessions)

    report_text = None
    has_report = False
    session = phase2_session_store.get_or_load(run_id, workspace.root, selected_llm)
    metadata: dict[str, object] = {}
    if session is not None:
        report = session.load_persisted_report()
        if session.metadata_path.exists():
            metadata = json.loads(session.metadata_path.read_text(encoding="utf-8"))
        if report is not None:
            has_report = True
            tool_usage = resolve_tool_usage(session)
            report_text = format_rca_report_pretty(
                report,
                run_id=run_id,
                agent_id=session.agent_id,
                provider=metadata.get("provider"),
                tool_usage=tool_usage,
            )

    manifest = json.loads((exports / "manifest.json").read_text(encoding="utf-8"))
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run_id": run_id,
            "manifest": manifest,
            "has_report": has_report,
            "report_text": report_text,
            "llm_context_options": _llm_context_options(settings),
            "selected_llm": selected_llm,
            "llm_sessions": llm_sessions,
            "llm_providers": llm_provider_options(settings),
        },
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})
