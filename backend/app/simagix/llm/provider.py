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


class LLMProvider(ABC):
    """Provider seam for Phase 2 agentic RCA."""

    @abstractmethod
    def run(self, session: Phase2Session, user_message: str) -> Phase2RunResult:
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def run_investigation(self, session: Phase2Session, user_message: str) -> InvestigationSummary:
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
