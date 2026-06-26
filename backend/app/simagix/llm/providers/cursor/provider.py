from __future__ import annotations

import sys
import time
from typing import Any, Literal

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.mcp.registry import build_mcp_server_specs, to_cursor_sdk_servers
from backend.app.simagix.llm.parse_output import (
    parse_clarifying_questions,
    parse_investigation_summary,
    parse_rca_report,
)
from backend.app.simagix.llm.provider import LLMProvider, ChatbotResult, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.tool_trace import ToolTraceCollector, ToolTracePhase
from backend.app.simagix.llm.web_fetch import build_cursor_sdk_web_tools
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary

try:
    from cursor_sdk import (
        Agent,
        AgentOptions,
        LocalAgentOptions,
        SandboxOptions,
        SendOptions,
    )
except ImportError:  # pragma: no cover - optional dependency
    Agent = None  # type: ignore[assignment,misc]
    AgentOptions = None  # type: ignore[assignment,misc]
    LocalAgentOptions = None  # type: ignore[assignment,misc]
    SandboxOptions = None  # type: ignore[assignment,misc]
    SendOptions = None  # type: ignore[assignment,misc]

AgentPhase = Literal["investigation", "clarify", "final_rca", "chatbot"]


class CursorLLMProvider(LLMProvider):
    """Cursor SDK agent — MCP servers from shared registry."""

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

    def _mcp_config(
        self,
        session: Phase2Session,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        specs = build_mcp_server_specs(
            session,
            self.settings,
            enabled_mcp_ids=enabled_mcp_ids,
        )
        return to_cursor_sdk_servers(specs)

    def _agent_options(
        self,
        session: Phase2Session,
        *,
        include_mcp: bool = True,
        trace: ToolTraceCollector | None = None,
        phase: AgentPhase | None = None,
        enabled_mcp_ids: list[str] | None = None,
    ) -> AgentOptions:
        bundle_cwd = str(session.evidence.bundle_dir)
        scratch_cwd = str(session.ensure_chatbot_scratch_dir())
        agent_cwd = scratch_cwd if include_mcp else bundle_cwd
        sandbox = SandboxOptions(enabled=False)
        custom_tools = {}
        if include_mcp and trace is not None and phase is not None:
            custom_tools = build_cursor_sdk_web_tools(trace, phase, settings=self.settings)
        return AgentOptions(
            api_key=self.settings.cursor_api_key,
            model=self.settings.cursor_model,
            local=LocalAgentOptions(
                cwd=agent_cwd,
                setting_sources=[],
                sandbox_options=sandbox,
                custom_tools=custom_tools or None,
            ),
            mcp_servers=self._mcp_config(session, enabled_mcp_ids=enabled_mcp_ids)
            if include_mcp
            else {},
        )

    def _run_agent_text(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        include_mcp: bool,
        phase: AgentPhase,
        enabled_mcp_ids: list[str] | None = None,
    ) -> str:
        assistant_chunks: list[str] = []
        trace = ToolTraceCollector(session.tool_trace_path, agent_id=session.agent_id)
        with Agent.create(
            self._agent_options(
                session,
                include_mcp=include_mcp,
                trace=trace,
                phase=phase,
                enabled_mcp_ids=enabled_mcp_ids,
            )
        ) as agent:
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
        return self._best_agent_text(result, assistant_chunks)

    def run_investigation(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> InvestigationSummary:
        raw_text = self._run_agent_text(
            session,
            user_message,
            include_mcp=True,
            phase="investigation",
            enabled_mcp_ids=enabled_mcp_ids,
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

    def run(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> Phase2RunResult:
        started = time.monotonic()
        raw_text = self._run_agent_text(
            session,
            user_message,
            include_mcp=True,
            phase="final_rca",
            enabled_mcp_ids=enabled_mcp_ids,
        )
        session.refresh_budget()
        try:
            report = parse_rca_report(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                "Cursor agent completed but did not return valid RCAReportDraft JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc
        return Phase2RunResult(
            report=report,
            agent_id=session.agent_id,
            run_id=session.run_id,
            tool_calls_used=session.budget_status()["tool_calls_used"],
            duration_seconds=time.monotonic() - started,
            raw_assistant_text=raw_text,
        )

    def run_chatbot(self, session: Phase2Session, user_message: str) -> ChatbotResult:
        session.configure_budget(self.settings.phase2_chatbot_max_tool_calls, reset=True)
        raw_text = self._run_agent_text(
            session, user_message, include_mcp=True, phase="chatbot"
        )
        return ChatbotResult(
            content=raw_text,
            tool_calls_used=session.budget_status()["tool_calls_used"],
        )

    def summarize_chat_history(
        self,
        session: Phase2Session,
        messages_to_fold: list[dict[str, str]],
        *,
        prior_summary: str | None = None,
    ) -> str:
        lines = []
        if prior_summary:
            lines.append(f"Prior summary:\n{prior_summary}\n")
        lines.append("Messages to compress:\n")
        for msg in messages_to_fold:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        prompt = (
            "Compress the chat history below into short factual prose. "
            "Keep topics asked, conclusions, profiler uploads mentioned, and open questions. "
            "Do not use tools. Reply with plain text only.\n\n"
            + "\n".join(lines)
        )
        return self._run_agent_text(session, prompt, include_mcp=False, phase="clarify")

    @staticmethod
    def _best_agent_text(result: Any, assistant_chunks: list[str]) -> str:
        streamed = "".join(assistant_chunks).strip()
        final = (getattr(result, "result", None) or "").strip()
        if len(streamed) > len(final):
            return streamed
        return final or streamed

    def _collect_assistant_text(self, message: Any, chunks: list[str]) -> None:
        if getattr(message, "type", None) != "assistant":
            return
        content = getattr(getattr(message, "message", None), "content", ()) or ()
        for block in content:
            if getattr(block, "type", None) == "text":
                text = getattr(block, "text", "")
                if text:
                    chunks.append(text)
