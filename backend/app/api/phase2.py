from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import get_run_workspace
from backend.app.simagix.format_report import format_rca_report_pretty
from backend.app.simagix.llm.state import llm_folder_name
from backend.app.simagix.llm.runner import (
    start_phase2_run_async,
    submit_clarifications_async,
)
from backend.app.simagix.llm.service import (
    get_chatbot_history,
    list_run_llm_sessions,
    load_iterative_state,
    llm_provider_options,
    post_chatbot_message,
    prepare_phase2_run,
    upload_chatbot_attachment,
)
from backend.app.simagix.llm.session import phase2_session_store
from backend.app.simagix.llm.tool_trace import load_tool_trace
from backend.app.simagix.output_schema import ClarifyingAnswers
from backend.app.simagix.report_html import render_report_html
from backend.app.simagix.tool_usage import resolve_tool_usage
from backend.app.simagix.anomaly_correlation import build_correlation_package
from backend.app.simagix.evidence.hatchet_tools import HatchetNotReadyError
from backend.app.simagix.llm.providers.adk.gemini_errors import http_exception_for_gemini_api_error

ReportFormat = Literal["json", "pretty"]

router = APIRouter(prefix="/simagix/runs", tags=["simagix-phase2"])


def _require_llm(llm: str | None) -> str:
    if not llm:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'llm' is required (mock, cursor, or gemini)",
        )
    try:
        return llm_folder_name(llm)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class Phase2RunRequest(BaseModel):
    force_mock: bool = Field(default=False, description="Use mock provider (legacy; prefer llm=mock)")
    llm_provider: str | None = Field(
        default=None,
        description="LLM backend: default | cursor | gemini | mock",
    )
    llm: str | None = Field(
        default=None,
        description="LLM folder: mock | cursor | gemini",
    )
    enabled_mcp_ids: list[str] = Field(
        default_factory=list,
        description="User MCP connector ids to enable for Phase A (Cursor only)",
    )


class Phase2ClarifyRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    enabled_mcp_ids: list[str] = Field(
        default_factory=list,
        description="User MCP connector ids to enable for Phase C (Cursor only)",
    )


class ChatbotAttachmentRef(BaseModel):
    name: str = Field(..., min_length=1)
    path: str = Field(..., min_length=1)
    size: int | None = Field(default=None, ge=0)


class ChatbotMessageRequest(BaseModel):
    content: str = Field(default="", description="User message for post-report chatbot")
    attachments: list[ChatbotAttachmentRef] = Field(default_factory=list)
    enabled_mcp_ids: list[str] = Field(
        default_factory=list,
        description="User MCP connector ids for this chatbot message (stateless per message)",
    )


@router.get("/phase2/llm-providers")
def list_llm_providers() -> dict[str, object]:
    settings = get_settings()
    return {
        "default": settings.llm_provider,
        "options": llm_provider_options(settings),
    }


@router.get("/{run_id}/phase2/llm")
def list_run_llm_slots(run_id: str) -> dict[str, object]:
    sessions = list_run_llm_sessions(get_run_workspace().root, run_id)
    return {"run_id": run_id, "llm_sessions": sessions}


@router.post("/{run_id}/phase2/run", status_code=202)
def run_phase2_start(run_id: str, body: Phase2RunRequest | None = None) -> dict[str, object]:
    """Validate and enqueue the investigation + clarifying-questions stage.

    Returns immediately with the running status; the frontend polls
    GET /phase2/status until awaiting_clarifications | failed.
    """
    force_mock = body.force_mock if body else False
    llm_provider = body.llm_provider if body else None
    llm = body.llm if body else None
    if not llm and not llm_provider and not force_mock:
        raise HTTPException(
            status_code=400,
            detail="Request body must include 'llm' (mock, cursor, gemini) or llm_provider",
        )
    try:
        return start_phase2_run_async(
            get_run_workspace().root,
            run_id,
            force_mock=force_mock,
            llm_provider=llm_provider,
            llm=llm,
            enabled_mcp_ids=body.enabled_mcp_ids if body else None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HatchetNotReadyError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _tool_trace_payload(session) -> dict[str, object]:
    trace = load_tool_trace(session.run_id, session.llm)
    return {
        "agent_id": trace.get("agent_id") or session.agent_id,
        "entries": trace.get("entries", []),
        "summary": trace.get("summary", {}),
    }


@router.get("/{run_id}/phase2/status")
def get_phase2_status(
    run_id: str,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    folder = _require_llm(llm)
    session = phase2_session_store.get_or_load(run_id, get_run_workspace().root, folder)
    if session is None:
        return {
            "run_id": run_id,
            "llm": folder,
            "status": "not_started",
            "tool_trace_summary": {"total": 0, "by_category": {}},
        }
    state = load_iterative_state(session)
    tool_trace_summary = _tool_trace_payload(session)
    if state is None:
        return {
            "run_id": run_id,
            "llm": folder,
            "status": "not_started",
            "tool_trace_summary": tool_trace_summary.get("summary", {}),
        }
    return {
        "run_id": run_id,
        "llm": folder,
        **state,
        "tool_trace_summary": tool_trace_summary.get("summary", {}),
    }


@router.get("/{run_id}/phase2/tool-trace")
def get_phase2_tool_trace(
    run_id: str,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    folder = _require_llm(llm)
    session = phase2_session_store.get_or_load(run_id, get_run_workspace().root, folder)
    if session is None:
        return {
            "run_id": run_id,
            "llm": folder,
            "agent_id": None,
            "entries": [],
            "summary": {"total": 0, "by_category": {}, "by_phase": {}},
        }
    trace = _tool_trace_payload(session)
    return {"run_id": run_id, "llm": folder, **trace}


@router.post("/{run_id}/phase2/clarify", status_code=202)
def run_phase2_clarify(
    run_id: str,
    body: Phase2ClarifyRequest,
    force_mock: Annotated[bool, Query(description="Use mock provider (legacy)")] = False,
    llm_provider: Annotated[str | None, Query(description="LLM backend (legacy)")] = None,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    """Validate and enqueue the final RCA stage; poll GET /phase2/status until completed."""
    if not llm and not llm_provider and not force_mock:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'llm' is required (mock, cursor, or gemini)",
        )
    try:
        return submit_clarifications_async(
            get_run_workspace().root,
            run_id,
            ClarifyingAnswers(answers=body.answers),
            force_mock=force_mock,
            llm_provider=llm_provider,
            llm=llm,
            enabled_mcp_ids=body.enabled_mcp_ids or None,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HatchetNotReadyError as exc:
        raise HTTPException(status_code=409, detail=exc.detail) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{run_id}/phase2/reports/latest")
def get_latest_phase2_report(
    run_id: str,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
    format: Annotated[ReportFormat, Query(description="json (default) or pretty plain-text report")] = "json",
):
    folder = _require_llm(llm)
    session = phase2_session_store.get_or_load(run_id, get_run_workspace().root, folder)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 session for run: {run_id} llm={folder}")
    report = session.load_persisted_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No persisted Phase 2 report for run: {run_id} llm={folder}",
        )

    tool_usage = resolve_tool_usage(session)
    metadata = session.load_metadata()
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
        "llm": folder,
        "agent_id": session.agent_id,
        "provider": metadata.get("provider"),
        "report": report.model_dump(),
        "report_text": report_text,
        "budget": session.budget_status(),
        "tool_usage": tool_usage,
        "llm_providers": llm_provider_options(get_settings()),
        "provider_configured": bool(
            get_settings().cursor_api_key or get_settings().google_api_key
        ),
    }


@router.get("/{run_id}/phase2/anomaly-correlation")
def get_anomaly_correlation(run_id: str) -> dict[str, object]:
    try:
        session, _ = prepare_phase2_run(get_run_workspace().root, run_id, llm="mock")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tier1 = session.evidence.load_tier1()
    return build_correlation_package(tier1.executive_context)


@router.get("/{run_id}/phase2/chatbot")
def get_chatbot(
    run_id: str,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    folder = _require_llm(llm)
    try:
        return get_chatbot_history(get_run_workspace().root, run_id, llm=folder)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{run_id}/phase2/chatbot/attachments")
async def post_chatbot_attachment(
    run_id: str,
    file: Annotated[UploadFile, File(description="Text-friendly attachment for chatbot scratch")],
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    folder = _require_llm(llm)
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    data = await file.read()
    try:
        return upload_chatbot_attachment(
            get_run_workspace().root,
            run_id,
            llm=folder,
            filename=file.filename,
            data=data,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{run_id}/phase2/chatbot/messages")
def post_chatbot(
    run_id: str,
    body: ChatbotMessageRequest,
    force_mock: Annotated[bool, Query(description="Use mock provider (legacy)")] = False,
    llm_provider: Annotated[str | None, Query(description="LLM backend (legacy)")] = None,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> dict[str, object]:
    folder = _require_llm(llm)
    try:
        return post_chatbot_message(
            get_run_workspace().root,
            run_id,
            llm=folder,
            content=body.content,
            attachments=[a.model_dump() for a in body.attachments],
            enabled_mcp_ids=body.enabled_mcp_ids or None,
            force_mock=force_mock,
            llm_provider=llm_provider,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        gemini_exc = http_exception_for_gemini_api_error(exc)
        if gemini_exc:
            raise gemini_exc from exc
        raise


@router.get("/{run_id}/phase2/reports/latest/view", response_class=HTMLResponse)
def view_latest_phase2_report_html(
    run_id: str,
    llm: Annotated[str | None, Query(description="LLM folder: mock, cursor, or gemini")] = None,
) -> HTMLResponse:
    folder = _require_llm(llm)
    session = phase2_session_store.get_or_load(run_id, get_run_workspace().root, folder)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No Phase 2 report for run: {run_id} llm={folder}")
    report = session.load_persisted_report()
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"No persisted Phase 2 report for run: {run_id} llm={folder}",
        )

    tool_usage = resolve_tool_usage(session)
    correlation: dict[str, object] = {}
    try:
        tier1 = session.evidence.load_tier1()
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
