from __future__ import annotations

import asyncio
import inspect
import json
import os
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import Settings
from backend.app.simagix.llm.mcp.registry import build_mcp_server_specs, to_adk_mcp_toolsets
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.skills.registry import build_adk_skill_toolset_all
from backend.app.simagix.llm.tool_trace import (
    ToolTraceCollector,
    ToolTraceEntry,
    ToolTracePhase,
    adk_tool_trace_identity,
    record_grounding_metadata,
)
from backend.app.simagix.llm.web_fetch import build_web_fetch_tool

try:
    from google.adk import Agent
    from google.adk.runners import InMemoryRunner
    from google.adk.tools.base_tool import BaseTool
    from google.adk.tools.tool_context import ToolContext
except ImportError:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment,misc]
    InMemoryRunner = None  # type: ignore[assignment,misc]
    BaseTool = Any  # type: ignore[assignment,misc]
    ToolContext = Any  # type: ignore[assignment,misc]

_ADK_APP_NAME = "mongo-debugger-phase2"
_AGENT_NAME = "simagix_rca"


def _require_adk() -> None:
    if Agent is None or InMemoryRunner is None:
        raise RuntimeError(
            "google-adk is not installed. Install with: uv sync --extra llm"
        )


def _apply_google_env(settings: Settings) -> None:
    if settings.google_api_key:
        os.environ["GOOGLE_API_KEY"] = settings.google_api_key
    if settings.google_genai_use_vertexai:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "TRUE"
    else:
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "FALSE"


def _summarize_value(value: Any, *, limit: int = 240) -> str:
    try:
        text = json.dumps(value, default=str)
    except TypeError:
        text = str(value)
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _make_after_tool_callback(
    trace: ToolTraceCollector,
    phase: ToolTracePhase,
):
    def _after_tool(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict,
    ) -> dict | None:
        raw_name = getattr(tool, "name", None) or getattr(tool, "__name__", "tool")
        display_name, category, mcp_server = adk_tool_trace_identity(str(raw_name))
        trace.append_entry(
            ToolTraceEntry(
                phase=phase,
                timestamp=datetime.now(timezone.utc).isoformat(),
                tool_name=display_name,
                category=category,
                status="completed",
                call_id=getattr(tool_context, "invocation_id", None),
                args_summary=_summarize_value(args),
                result_summary=_summarize_value(tool_response),
                mcp_server=mcp_server,
            )
        )
        return None

    return _after_tool


def _extract_assistant_text(events: list[Any]) -> str:
    chunks: list[str] = []
    for event in events:
        if getattr(event, "author", "") == "user":
            continue
        if getattr(event, "partial", False):
            continue
        content = getattr(event, "content", None)
        if content is None or not getattr(content, "parts", None):
            continue
        for part in content.parts:
            text = getattr(part, "text", None)
            if text:
                chunks.append(text)
    return "\n".join(chunks).strip()


async def _close_toolsets(toolsets: list[Any]) -> None:
    for toolset in toolsets:
        close = getattr(toolset, "close", None)
        if not callable(close):
            continue
        result = close()
        if inspect.iscoroutine(result):
            await result


async def _run_adk_async(
    session: Phase2Session,
    user_message: str,
    *,
    settings: Settings,
    include_tools: bool,
    phase: ToolTracePhase,
    enabled_mcp_ids: list[str] | None = None,
) -> str:
    _require_adk()
    _apply_google_env(settings)

    trace = ToolTraceCollector(session.tool_trace_path, agent_id=session.agent_id)
    trace.agent_id = f"gemini-adk:{session.run_id}"

    closable_toolsets: list[Any] = []
    tools: list[Any] = []
    if include_tools:
        specs = build_mcp_server_specs(
            session,
            settings,
            enabled_mcp_ids=enabled_mcp_ids,
        )
        mcp_toolsets = to_adk_mcp_toolsets(specs)
        closable_toolsets.extend(mcp_toolsets)
        tools.extend(mcp_toolsets)
        skill_toolset = build_adk_skill_toolset_all(session.workspace_root)
        if skill_toolset is not None:
            closable_toolsets.append(skill_toolset)
            tools.append(skill_toolset)
        tools.append(build_web_fetch_tool(settings))

    try:
        agent = Agent(
            name=_AGENT_NAME,
            model=settings.google_model,
            instruction=(
                "You are a MongoDB FTDC root-cause analysis agent. "
                "Use simagix evidence tools when you need metric proof. "
                "Use web_fetch for HTTPS documentation when prompts ask to fetch URLs. "
                "Follow the user message format exactly, especially JSON output requirements."
            ),
            tools=tools,
            after_tool_callback=_make_after_tool_callback(trace, phase) if include_tools else None,
        )
        runner = InMemoryRunner(agent=agent, app_name=_ADK_APP_NAME)
        adk_session_id = f"{session.run_id}:{phase}"
        events = await runner.run_debug(
            user_message,
            user_id=session.run_id,
            session_id=adk_session_id,
            quiet=True,
        )
    finally:
        await _close_toolsets(closable_toolsets)

    session.agent_id = trace.agent_id
    if include_tools:
        record_grounding_metadata(trace, phase, events)
        trace.save()
    session.refresh_budget()
    text = _extract_assistant_text(events)
    if not text:
        raise RuntimeError("Gemini ADK agent completed but returned no assistant text")
    return text


def run_adk_agent_text(
    session: Phase2Session,
    user_message: str,
    *,
    settings: Settings,
    include_tools: bool,
    phase: ToolTracePhase,
    enabled_mcp_ids: list[str] | None = None,
) -> str:
    """Sync wrapper for FastAPI — ADK runs the model/tool loop asynchronously."""
    return asyncio.run(
        _run_adk_async(
            session,
            user_message,
            settings=settings,
            include_tools=include_tools,
            phase=phase,
            enabled_mcp_ids=enabled_mcp_ids,
        )
    )
