"""Claude Agent SDK provider for Phase 2 agentic RCA.

Uses claude-agent-sdk query() — the SDK handles the agentic loop, MCP server
lifecycle, and tool dispatch. Mirrors CursorLLMProvider against the same
LLMProvider seam: run agent → collect assistant text → parse with shared
parse_rca_report / parse_investigation_summary / parse_clarifying_questions.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.mcp.registry import build_mcp_server_specs, to_agent_sdk_servers
from backend.app.simagix.llm.parse_output import (
    parse_clarifying_questions,
    parse_investigation_summary,
    parse_rca_report,
)
from backend.app.simagix.llm.provider import ChatbotResult, LLMProvider, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.skills.registry import copy_all_to_agent_sdk_skills, list_skill_dirs
from backend.app.simagix.llm.tool_trace import ToolTraceCollector, ToolTracePhase
from backend.app.simagix.llm.subagents import available_subagents
from backend.app.simagix.llm.web_fetch import execute_web_fetch
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary

try:
    from claude_agent_sdk import (
        AgentDefinition as ClaudeAgentDefinition,
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        create_sdk_mcp_server,
        query,
        tool as sdk_tool,
    )
except ImportError:  # pragma: no cover - optional dependency
    query = None  # type: ignore[assignment,misc]
    ClaudeAgentOptions = None  # type: ignore[assignment,misc]
    ClaudeAgentDefinition = None  # type: ignore[assignment,misc]
    AssistantMessage = None  # type: ignore[assignment,misc]
    ResultMessage = None  # type: ignore[assignment,misc]
    TextBlock = None  # type: ignore[assignment,misc]
    ToolUseBlock = None  # type: ignore[assignment,misc]
    ToolResultBlock = None  # type: ignore[assignment,misc]
    create_sdk_mcp_server = None  # type: ignore[assignment,misc]
    sdk_tool = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

AgentPhase = ToolTracePhase


class ClaudeLLMProvider(LLMProvider):
    """Claude Agent SDK provider — MCP servers from shared registry, shared text parsers."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if query is None:
            raise RuntimeError(
                "claude-agent-sdk is not installed. Install with: uv sync --extra llm"
            )
        if not self.settings.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not configured. Set it in the environment to run Phase 2 with Claude."
            )

    @property
    def provider_name(self) -> str:
        return "claude"

    def _build_options(
        self,
        session: Phase2Session,
        *,
        include_mcp: bool = True,
        phase: AgentPhase,
        trace: ToolTraceCollector | None = None,
        enabled_mcp_ids: list[str] | None = None,
    ) -> ClaudeAgentOptions:
        scratch_dir = session.ensure_chatbot_scratch_dir()

        mcp_servers: dict[str, Any] = {}
        if include_mcp:
            specs = build_mcp_server_specs(
                session, self.settings, enabled_mcp_ids=enabled_mcp_ids,
            )
            mcp_servers = to_agent_sdk_servers(specs)

        if include_mcp and trace is not None:
            web_server = self._build_web_fetch_sdk_server(trace, phase)
            mcp_servers["web-fetch"] = web_server

        skills: list[str] | None = None
        if include_mcp and list_skill_dirs(session.workspace_root):
            skills = copy_all_to_agent_sdk_skills(session.workspace_root, scratch_dir)

        agents: dict[str, Any] | None = None
        if include_mcp and phase in ("investigation", "final_rca", "chatbot"):
            agents = self._build_subagent_defs(set(mcp_servers.keys()))

        return ClaudeAgentOptions(
            model=self.settings.anthropic_model,
            cwd=str(scratch_dir),
            env={"ANTHROPIC_API_KEY": self.settings.anthropic_api_key},
            mcp_servers=mcp_servers,
            strict_mcp_config=True,
            permission_mode="bypassPermissions",
            tools=["Agent"] if agents else [],
            allowed_tools=["Agent"] if agents else [],
            max_turns=60,
            thinking={"type": "adaptive"},
            skills=skills,
            agents=agents,
        )

    def _build_web_fetch_sdk_server(
        self,
        trace: ToolTraceCollector,
        phase: AgentPhase,
    ) -> Any:
        """Build an in-process SDK MCP server for web_fetch with tracing."""
        from datetime import datetime, timezone

        from backend.app.simagix.llm.tool_trace import ToolTraceEntry

        resolved_settings = self.settings

        @sdk_tool(
            "web_fetch",
            "Fetch trusted HTTPS documentation or engineering sources. "
            "Call before citing a URL in web_insights, evidence_citations, or reference_urls.",
            {"url": str},
        )
        async def web_fetch(args: dict[str, Any]) -> dict[str, Any]:
            url = str(args.get("url") or "").strip()
            result, status, excerpt = execute_web_fetch(url, settings=resolved_settings)
            trace.append_entry(
                ToolTraceEntry(
                    phase=phase,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    tool_name="web_fetch",
                    category="web",
                    status=status,
                    args_summary=f'{{"url": "{url}"}}'[:240],
                    result_summary=(excerpt or "")[:240],
                )
            )
            text = result.get("excerpt") or result.get("error") or ""
            return {"content": [{"type": "text", "text": text}], "is_error": status == "error"}

        return create_sdk_mcp_server("web-fetch", tools=[web_fetch])

    @staticmethod
    def _build_subagent_defs(active_server_ids: set[str]) -> dict[str, Any] | None:
        specs = available_subagents(active_server_ids)
        if not specs:
            return None
        agents: dict[str, Any] = {}
        for spec in specs:
            agents[spec.name] = ClaudeAgentDefinition(
                description=spec.description,
                prompt=spec.prompt,
                mcpServers=[s for s in spec.mcp_server_ids if s in active_server_ids] or None,
                maxTurns=spec.max_turns,
            )
        return agents

    def _run_agent_text(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        include_mcp: bool,
        phase: AgentPhase,
        enabled_mcp_ids: list[str] | None = None,
    ) -> str:
        return asyncio.run(
            self._run_agent_text_async(
                session, user_message,
                include_mcp=include_mcp,
                phase=phase,
                enabled_mcp_ids=enabled_mcp_ids,
            )
        )

    async def _run_agent_text_async(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        include_mcp: bool,
        phase: AgentPhase,
        enabled_mcp_ids: list[str] | None = None,
    ) -> str:
        trace = ToolTraceCollector(session.run_id, session.llm, agent_id=session.agent_id)
        options = self._build_options(
            session,
            include_mcp=include_mcp,
            phase=phase,
            trace=trace,
            enabled_mcp_ids=enabled_mcp_ids,
        )

        assistant_chunks: list[str] = []
        result_text = ""
        session_id: str | None = None

        async for message in query(prompt=user_message, options=options):
            if isinstance(message, AssistantMessage):
                session_id = getattr(message, "session_id", None) or session_id
                self._collect_assistant_text(message, assistant_chunks)
                self._record_tool_uses(message, trace, phase)
            elif isinstance(message, ResultMessage):
                session_id = getattr(message, "session_id", None) or session_id
                result_text = getattr(message, "result", "") or ""
                if message.is_error:
                    errors = getattr(message, "errors", None) or []
                    err_detail = "; ".join(str(e) for e in errors) if errors else result_text
                    raise RuntimeError(f"Claude agent failed: {err_detail}")

        if session_id:
            session.agent_id = f"claude:{session_id}"
            trace.agent_id = session.agent_id

        trace.save()
        return self._best_agent_text(result_text, assistant_chunks)

    # ------------------------------------------------------------------ #
    # LLMProvider interface
    # ------------------------------------------------------------------ #

    def run_investigation(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> InvestigationSummary:
        raw_text = self._run_agent_text(
            session, user_message,
            include_mcp=True,
            phase="investigation",
            enabled_mcp_ids=enabled_mcp_ids,
        )
        session.refresh_budget()
        try:
            return parse_investigation_summary(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                f"Claude agent completed but did not return valid InvestigationSummary JSON.\n"
                f"Raw text (last 500 chars): ...{raw_text[-500:]}"
            ) from exc

    def generate_clarifying_questions(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        max_questions: int,
    ) -> ClarifyingQuestionsBlock:
        raw_text = self._run_agent_text(
            session, user_message, include_mcp=False, phase="clarify",
        )
        try:
            return parse_clarifying_questions(raw_text, session.run_id, max_questions=max_questions)
        except ValueError as exc:
            raise RuntimeError(
                f"Claude agent completed but did not return valid ClarifyingQuestionsBlock JSON.\n"
                f"Raw text (last 500 chars): ...{raw_text[-500:]}"
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
            session, user_message,
            include_mcp=True,
            phase="final_rca",
            enabled_mcp_ids=enabled_mcp_ids,
        )
        session.refresh_budget()
        try:
            report = parse_rca_report(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                f"Claude agent completed but did not return valid RCAReportDraft JSON.\n"
                f"Raw text (last 500 chars): ...{raw_text[-500:]}"
            ) from exc
        return Phase2RunResult(
            report=report,
            agent_id=session.agent_id,
            run_id=session.run_id,
            tool_calls_used=session.budget_status()["tool_calls_used"],
            duration_seconds=time.monotonic() - started,
            raw_assistant_text=raw_text,
        )

    def run_chatbot(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> ChatbotResult:
        session.configure_budget(self.settings.phase2_chatbot_max_tool_calls, reset=True)
        raw_text = self._run_agent_text(
            session, user_message,
            include_mcp=True,
            phase="chatbot",
            enabled_mcp_ids=enabled_mcp_ids,
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
        lines: list[str] = []
        if prior_summary:
            lines.append(f"Prior summary:\n{prior_summary}\n")
        lines.append("Messages to compress:\n")
        for msg in messages_to_fold:
            lines.append(f"{msg.get('role', 'unknown')}: {msg.get('content', '')}")
        prompt = (
            "Compress the chat history below into short factual prose. "
            "Keep topics asked, conclusions, and open questions. "
            "Do not use tools. Reply with plain text only.\n\n"
            + "\n".join(lines)
        )
        return self._run_agent_text(session, prompt, include_mcp=False, phase="clarify")

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _collect_assistant_text(message: Any, chunks: list[str]) -> None:
        for block in getattr(message, "content", None) or []:
            if isinstance(block, TextBlock):
                text = getattr(block, "text", "")
                if text:
                    chunks.append(text)

    @staticmethod
    def _record_tool_uses(
        message: Any,
        trace: ToolTraceCollector,
        phase: AgentPhase,
    ) -> None:
        for block in getattr(message, "content", None) or []:
            if isinstance(block, ToolUseBlock):
                trace.record_sdk_message(
                    {
                        "type": "tool_call",
                        "call_id": block.id,
                        "name": block.name,
                        "args": block.input,
                        "status": "completed",
                    },
                    phase,
                )

    @staticmethod
    def _best_agent_text(result_text: str, assistant_chunks: list[str]) -> str:
        streamed = "".join(assistant_chunks).strip()
        final = (result_text or "").strip()
        if len(streamed) > len(final):
            return streamed
        return final or streamed
