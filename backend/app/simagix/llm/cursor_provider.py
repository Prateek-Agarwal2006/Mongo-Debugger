from __future__ import annotations

import sys
import time
from typing import Any, Literal

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.parse_output import (
    parse_clarifying_questions,
    parse_investigation_summary,
    parse_rca_report,
)
from backend.app.simagix.llm.provider import LLMProvider, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.tool_trace import ToolTraceCollector, ToolTracePhase
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary

try:
    from cursor_sdk import (
        Agent,
        AgentOptions,
        CursorAgentError,
        LocalAgentOptions,
        SandboxOptions,
        SendOptions,
        StdioMcpServerConfig,
    )
except ImportError:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment,misc]
    AgentOptions = None  # type: ignore[assignment,misc]
    CursorAgentError = Exception  # type: ignore[assignment,misc]
    LocalAgentOptions = None  # type: ignore[assignment,misc]
    SandboxOptions = None  # type: ignore[assignment,misc]
    SendOptions = None  # type: ignore[assignment,misc]
    StdioMcpServerConfig = None  # type: ignore[assignment,misc]

AgentPhase = Literal["investigation", "clarify", "final_rca"]


class CursorLLMProvider(LLMProvider):
    """Cursor SDK agent with in-process MCP evidence server."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if Agent is None:
            raise RuntimeError(
                "cursor-sdk is not installed. Install with: uv sync --extra llm"
            )
        if not self.settings.cursor_api_key:
            raise RuntimeError(
                "CURSOR_API_KEY is not configured. Set it in the environment to run Phase 2."
            )

    @property
    def provider_name(self) -> str:
        return "cursor"

    def _mcp_config(self, session: Phase2Session) -> dict[str, StdioMcpServerConfig]:
        env = session.mcp_server_env()
        servers: dict[str, StdioMcpServerConfig] = {
            "simagix-evidence": StdioMcpServerConfig(
                command=sys.executable,
                args=["-m", "backend.app.simagix.llm.mcp_evidence_server"],
                env=env,
            )
        }
        if self.settings.graylog_api_url and self.settings.graylog_api_token:
            graylog_env = {
                **env,
                "GRAYLOG_API_URL": self.settings.graylog_api_url,
                "GRAYLOG_API_TOKEN": self.settings.graylog_api_token,
                "GRAYLOG_AUTH_MODE": self.settings.graylog_auth_mode,
                "GRAYLOG_DEFAULT_QUERY": self.settings.graylog_default_query,
                "GRAYLOG_SEARCH_LIMIT": str(self.settings.graylog_search_limit),
            }
            servers["graylog"] = StdioMcpServerConfig(
                command=sys.executable,
                args=["-m", "backend.app.simagix.llm.graylog_mcp_server"],
                env=graylog_env,
            )
        return servers

    def _agent_options(self, session: Phase2Session, *, include_mcp: bool = True) -> AgentOptions:
        bundle_cwd = str(session.orchestrator.bundle_dir)
        return AgentOptions(
            api_key=self.settings.cursor_api_key,
            model=self.settings.cursor_model,
            local=LocalAgentOptions(
                cwd=bundle_cwd,
                setting_sources=[],
                sandbox_options=SandboxOptions(enabled=True),
            ),
            mcp_servers=self._mcp_config(session) if include_mcp else {},
        )

    def _run_agent_text(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        include_mcp: bool,
        phase: AgentPhase,
    ) -> str:
        assistant_chunks: list[str] = []
        trace = ToolTraceCollector(session.tool_trace_path, agent_id=session.agent_id)
        with Agent.create(self._agent_options(session, include_mcp=include_mcp)) as agent:
            session.agent_id = agent.agent_id
            trace.agent_id = agent.agent_id
            run = agent.send(user_message, SendOptions(mode="agent"))
            for message in run.messages():
                trace.record_sdk_message(message, phase)
                self._collect_assistant_text(message, assistant_chunks)
            result = run.wait()
            if result.status == "error":
                raise RuntimeError(f"Cursor agent run failed: {result.id}")
        trace.save()
        return (result.result or "").strip() or "".join(assistant_chunks).strip()

    def run_investigation(self, session: Phase2Session, user_message: str) -> InvestigationSummary:
        raw_text = self._run_agent_text(
            session, user_message, include_mcp=True, phase="investigation"
        )
        session.refresh_budget()
        try:
            return parse_investigation_summary(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                "Cursor agent completed but did not return valid InvestigationSummary JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc

    def generate_clarifying_questions(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        max_questions: int,
    ) -> ClarifyingQuestionsBlock:
        raw_text = self._run_agent_text(
            session, user_message, include_mcp=False, phase="clarify"
        )
        try:
            return parse_clarifying_questions(raw_text, session.run_id, max_questions=max_questions)
        except ValueError as exc:
            raise RuntimeError(
                "Cursor agent completed but did not return valid ClarifyingQuestionsBlock JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc

    def run(self, session: Phase2Session, user_message: str) -> Phase2RunResult:
        started = time.monotonic()
        assistant_chunks: list[str] = []
        agent_id: str | None = None
        trace = ToolTraceCollector(session.tool_trace_path, agent_id=session.agent_id)

        with Agent.create(self._agent_options(session)) as agent:
            agent_id = agent.agent_id
            session.agent_id = agent_id
            trace.agent_id = agent_id
            run = agent.send(user_message, SendOptions(mode="agent"))
            for message in run.messages():
                trace.record_sdk_message(message, "final_rca")
                self._collect_assistant_text(message, assistant_chunks)
            result = run.wait()
            if result.status == "error":
                raise RuntimeError(f"Cursor agent run failed: {result.id}")

        trace.save()
        session.refresh_budget()
        raw_text = (result.result or "").strip() or "".join(assistant_chunks).strip()
        try:
            report = parse_rca_report(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                "Cursor agent completed but did not return valid RCAReportDraft JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc
        return Phase2RunResult(
            report=report,
            agent_id=agent_id,
            run_id=session.run_id,
            tool_calls_used=session.budget_status()["tool_calls_used"],
            duration_seconds=time.monotonic() - started,
            raw_assistant_text=raw_text,
        )

    def _collect_assistant_text(self, message: Any, chunks: list[str]) -> None:
        if getattr(message, "type", None) != "assistant":
            return
        content = getattr(getattr(message, "message", None), "content", ()) or ()
        for block in content:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                if text:
                    chunks.append(text)
