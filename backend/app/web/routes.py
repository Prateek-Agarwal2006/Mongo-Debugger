from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from backend.app.jobs.store import job_store
from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.llm.session import phase2_session_store
from backend.app.simagix.tool_usage import resolve_tool_usage

router = APIRouter(tags=["web-ui"])

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _list_run_ids() -> list[str]:
    exports_dir = _workspace_root() / "simagix-workspace/exports/mongo-ftdc"
    if not exports_dir.exists():
        return []
    return sorted(
        [
            item.name
            for item in exports_dir.iterdir()
            if item.is_dir() and (item / "manifest.json").exists()
        ],
        reverse=True,
    )


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
def run_detail(request: Request, run_id: str) -> HTMLResponse:
    workspace = _workspace_root()
    exports = workspace / "simagix-workspace/exports/mongo-ftdc" / run_id
    if not (exports / "manifest.json").exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    report_text = None
    has_report = False
    session = phase2_session_store.get_or_load(run_id, workspace)
    if session is not None:
        report = session.load_persisted_report()
        if report is not None:
            has_report = True
            tool_usage = resolve_tool_usage(session)
            report_text = format_rca_report_pretty(
                report,
                run_id=run_id,
                agent_id=session.agent_id,
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
        },
    )


@router.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "upload.html", {})
