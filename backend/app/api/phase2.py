from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.llm.service import (
    load_iterative_state,
    prepare_phase2_run,
    start_phase2_run,
    submit_clarifications_and_run,
)
from backend.app.simagix.llm.session import phase2_session_store
from backend.app.simagix.llm.tool_trace import load_tool_trace
from backend.app.simagix.output_schema import ClarifyingAnswers
from backend.app.simagix.profiler import load_profiler_data, save_profiler_data
from backend.app.simagix.report_html import render_report_html
from backend.app.simagix.tool_usage import resolve_tool_usage
from backend.app.simagix.anomaly_correlation import build_correlation_package

ReportFormat = Literal["json", "pretty"]

router = APIRouter(prefix="/simagix/runs", tags=["simagix-phase2"])


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


class Phase2RunRequest(BaseModel):
    force_mock: bool = Field(default=False, description="Use mock provider (tests/dev without API key)")


@router.post("/{run_id}/phase2/run")
def run_phase2_start(run_id: str, body: Phase2RunRequest | None = None) -> dict[str, object]:
    force_mock = body.force_mock if body else False
    try:
        return start_phase2_run(_workspace_root(), run_id, force_mock=force_mock)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _tool_trace_payload(session) -> dict[str, object]:
    trace = load_tool_trace(session.tool_trace_path)
    return {
        "agent_id": trace.get("agent_id") or session.agent_id,
        "entries": trace.get("entries", []),
        "summary": trace.get("summary", {}),
    }


@router.get("/{run_id}/phase2/status")
def get_phase2_status(run_id: str) -> dict[str, object]:
    session = phase2_session_store.get_or_load(run_id, _workspace_root())
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 session for run: {run_id}")
    state = load_iterative_state(session)
    tool_trace_summary = _tool_trace_payload(session)
    if state is None:
        return {
            "run_id": run_id,
            "status": "not_started",
            "tool_trace_summary": tool_trace_summary.get("summary", {}),
        }
    return {
        "run_id": run_id,
        **state,
        "tool_trace_summary": tool_trace_summary.get("summary", {}),
    }


@router.get("/{run_id}/phase2/tool-trace")
def get_phase2_tool_trace(run_id: str) -> dict[str, object]:
    session = phase2_session_store.get_or_load(run_id, _workspace_root())
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 session for run: {run_id}")
    trace = _tool_trace_payload(session)
    return {"run_id": run_id, **trace}


@router.post("/{run_id}/phase2/clarify")
def run_phase2_clarify(
    run_id: str,
    body: ClarifyingAnswers,
    force_mock: Annotated[bool, Query(description="Use mock provider")] = False,
) -> dict[str, object]:
    try:
        return submit_clarifications_and_run(_workspace_root(), run_id, body, force_mock=force_mock)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{run_id}/phase2/reports/latest")
def get_latest_phase2_report(
    run_id: str,
    format: Annotated[ReportFormat, Query(description="json (default) or pretty plain-text report")] = "json",
):
    session = phase2_session_store.get_or_load(run_id, _workspace_root())
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 session for run: {run_id}")
    report = session.load_persisted_report()
    if report is None:
        raise HTTPException(status_code=404, detail=f"No persisted Phase 2 report for run: {run_id}")

    tool_usage = resolve_tool_usage(session)
    metadata = {}
    if session.metadata_path.exists():
        metadata = json.loads(session.metadata_path.read_text(encoding="utf-8"))
    report_text = format_rca_report_pretty(
        report,
        run_id=run_id,
        agent_id=session.agent_id,
        provider=metadata.get("provider"),
        tool_usage=tool_usage,
    )

    if format == "pretty":
        return PlainTextResponse(report_text, media_type="text/plain; charset=utf-8")

    return {
        "run_id": run_id,
        "agent_id": session.agent_id,
        "report": report.model_dump(),
        "report_text": report_text,
        "budget": session.budget_status(),
        "tool_usage": tool_usage,
        "provider_configured": bool(get_settings().cursor_api_key),
    }


@router.get("/{run_id}/phase2/anomaly-correlation")
def get_anomaly_correlation(run_id: str) -> dict[str, object]:
    try:
        session, _ = prepare_phase2_run(_workspace_root(), run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tier1 = session.orchestrator.load_tier1()
    return build_correlation_package(tier1.executive_context)


@router.post("/{run_id}/phase2/profiler")
def upload_profiler_data(run_id: str, body: list[dict[str, object]]) -> dict[str, object]:
    path = save_profiler_data(_workspace_root(), run_id, body)
    return {"run_id": run_id, "path": str(path), "sample_count": len(body)}


@router.get("/{run_id}/phase2/profiler")
def get_profiler_data(run_id: str, limit: int = 50) -> dict[str, object]:
    return load_profiler_data(_workspace_root(), run_id, limit=limit)


@router.get("/{run_id}/phase2/reports/latest/view", response_class=HTMLResponse)
def view_latest_phase2_report_html(run_id: str) -> HTMLResponse:
    session = phase2_session_store.get_or_load(run_id, _workspace_root())
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 report for run: {run_id}")
    report = session.load_persisted_report()
    if report is None:
        raise HTTPException(status_code=404, detail=f"No persisted Phase 2 report for run: {run_id}")

    tool_usage = resolve_tool_usage(session)
    correlation: dict[str, object] = {}
    try:
        tier1 = session.orchestrator.load_tier1()
        correlation = build_correlation_package(tier1.executive_context)
    except Exception:
        pass

    html = render_report_html(
        report,
        run_id=run_id,
        agent_id=session.agent_id,
        tool_usage=tool_usage,
        correlation=correlation,
    )
    return HTMLResponse(html)
