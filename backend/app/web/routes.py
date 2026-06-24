from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import get_run_workspace, repo_root
from backend.app.jobs.catalog import (
    hatchet_display_status,
    list_hatchet_attempts,
    list_phase1_attempts,
    list_run_catalog,
    latest_hatchet_job_for_run,
    latest_job_for_run,
    pipeline_display_status,
    upload_time_utc_from_run_id,
)
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
    workspace = get_run_workspace()
    entries = [entry.to_dict() for entry in list_run_catalog(workspace.root)]
    return templates.TemplateResponse(
        request,
        "home.html",
        {"run_entries": entries[:10]},
    )


@router.get("/runs", response_class=HTMLResponse)
def runs_list(request: Request) -> HTMLResponse:
    workspace = get_run_workspace()
    entries = [entry.to_dict() for entry in list_run_catalog(workspace.root)]
    return templates.TemplateResponse(request, "runs.html", {"run_entries": entries})


@router.get("/runs/{run_id}/pipeline", response_class=HTMLResponse)
def run_pipeline_status(request: Request, run_id: str) -> HTMLResponse:
    workspace = get_run_workspace()
    job = latest_job_for_run(workspace.root, run_id)
    if job is None and not (workspace.resolve_exports_dir(run_id) / "manifest.json").exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    status = "finished"
    if job is not None:
        status = pipeline_display_status(workspace, job)
    elif (workspace.resolve_exports_dir(run_id) / "manifest.json").exists():
        status = "finished"
    return templates.TemplateResponse(
        request,
        "run_pipeline.html",
        {
            "run_id": run_id,
            "pipeline_status": status,
            "phase1_status": status,
            "job": job.to_dict() if job else None,
            "job_id": job.job_id if job else None,
            "phase1_attempts": [attempt.to_dict() for attempt in list_phase1_attempts(workspace.root, run_id)],
            "upload_time_utc": upload_time_utc_from_run_id(run_id),
        },
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str, llm: str | None = None) -> HTMLResponse:
    workspace = get_run_workspace()
    exports = workspace.resolve_exports_dir(run_id)
    if not (exports / "manifest.json").exists():
        job = latest_job_for_run(workspace.root, run_id)
        if job is not None or workspace.upload_exists(run_id):
            return run_pipeline_status(request, run_id)
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
    has_logs = workspace.has_mongodb_log_inputs(run_id)
    has_hatchet_summary = workspace.hatchet_summary_ready(run_id)
    hatchet_job = latest_hatchet_job_for_run(workspace.root, run_id)
    hatchet_status = hatchet_display_status(
        workspace,
        hatchet_job,
        has_summary=has_hatchet_summary,
        has_logs=has_logs,
    )
    log_files = [path.name for path in workspace.list_mongodb_log_files(run_id)]
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
            "hatchet_status": hatchet_status,
            "has_hatchet_summary": has_hatchet_summary,
            "has_mongodb_logs": has_logs,
            "mongodb_log_files": log_files,
            "hatchet_job": hatchet_job.to_dict() if hatchet_job else None,
            "hatchet_attempts": [attempt.to_dict() for attempt in list_hatchet_attempts(workspace.root, run_id)],
            "phase2_hatchet_blocked": has_logs and not has_hatchet_summary,
        },
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})
