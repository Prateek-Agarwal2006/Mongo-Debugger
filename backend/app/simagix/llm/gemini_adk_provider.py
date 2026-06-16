from __future__ import annotations

import time

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.adk_runner import run_adk_agent_text
from backend.app.simagix.llm.parse_output import (
    parse_clarifying_questions,
    parse_investigation_summary,
    parse_rca_report,
)
from backend.app.simagix.llm.prompts import build_chatbot_summarize_prompt
from backend.app.simagix.llm.provider import LLMProvider, ChatbotResult, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary


class GeminiAdkLLMProvider(LLMProvider):
    """Google ADK agent with AI Studio API key — ADK runs the tool loop locally."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.google_api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY is not configured. "
                "Get a key from https://aistudio.google.com/apikey and set LLM_PROVIDER=gemini."
            )

    @property
    def provider_name(self) -> str:
        return "gemini-adk"

    def run_investigation(self, session: Phase2Session, user_message: str) -> InvestigationSummary:
        raw_text = run_adk_agent_text(
            session,
            user_message,
            settings=self.settings,
            include_tools=True,
            phase="investigation",
        )
        try:
            return parse_investigation_summary(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                "Gemini ADK agent completed but did not return valid InvestigationSummary JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc

    def generate_clarifying_questions(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        max_questions: int,
    ) -> ClarifyingQuestionsBlock:
        raw_text = run_adk_agent_text(
            session,
            user_message,
            settings=self.settings,
            include_tools=False,
            phase="clarify",
        )
        try:
            return parse_clarifying_questions(raw_text, session.run_id, max_questions=max_questions)
        except ValueError as exc:
            raise RuntimeError(
                "Gemini ADK agent completed but did not return valid ClarifyingQuestionsBlock JSON. "
                f"Preview: {raw_text[:300]!r}"
            ) from exc

    def run(self, session: Phase2Session, user_message: str) -> Phase2RunResult:
        started = time.monotonic()
        raw_text = run_adk_agent_text(
            session,
            user_message,
            settings=self.settings,
            include_tools=True,
            phase="final_rca",
        )
        try:
            report = parse_rca_report(raw_text, session.run_id)
        except ValueError as exc:
            raise RuntimeError(
                "Gemini ADK agent completed but did not return valid RCAReportDraft JSON. "
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
        raw_text = run_adk_agent_text(
            session,
            user_message,
            settings=self.settings,
            include_tools=True,
            phase="chatbot",
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
        prompt = build_chatbot_summarize_prompt(
            messages_to_fold,
            prior_summary=prior_summary,
        )
        return run_adk_agent_text(
            session,
            prompt,
            settings=self.settings,
            include_tools=False,
            phase="clarify",
        )
