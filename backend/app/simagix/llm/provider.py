from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary, RCAReportDraft


@dataclass
class Phase2RunResult:
    report: RCAReportDraft
    agent_id: str | None
    run_id: str
    tool_calls_used: int
    duration_seconds: float
    raw_assistant_text: str = ""


@dataclass
class ChatbotResult:
    content: str
    tool_calls_used: int = 0


class LLMProvider(ABC):
    """Provider seam for Phase 2 agentic RCA."""

    @abstractmethod
    def run(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> Phase2RunResult:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def run_investigation(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        enabled_mcp_ids: list[str] | None = None,
    ) -> InvestigationSummary:
        raise NotImplementedError

    @abstractmethod
    def generate_clarifying_questions(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        max_questions: int,
    ) -> ClarifyingQuestionsBlock:
        raise NotImplementedError

    @abstractmethod
    def run_chatbot(self, session: Phase2Session, user_message: str) -> ChatbotResult:
        raise NotImplementedError

    @abstractmethod
    def summarize_chat_history(
        self,
        session: Phase2Session,
        messages_to_fold: list[dict[str, str]],
        *,
        prior_summary: str | None = None,
    ) -> str:
        raise NotImplementedError
