from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class EvidenceCitation(BaseModel):
    source_type: Literal[
        "finding",
        "anomaly",
        "assessment",
        "metric_slice",
        "raw_path",
        "log",
        "operator",
        "web",
    ]
    reference: str
    summary: str
    values: dict[str, Any] = Field(default_factory=dict)


class FindingAnalysis(BaseModel):
    """Per-finding deep dive: what was observed and why (mechanism), not symptoms alone."""

    finding_name: str
    what_observed: str
    why_it_happened: str
    contributing_factors: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    time_window: str | None = None


class TimelineEvent(BaseModel):
    """Chronological incident narrative with observation and mechanism."""

    time_window: str
    observation: str
    mechanism: str
    metrics_involved: list[str] = Field(default_factory=list)


class RCAReportDraft(BaseModel):
    run_id: str
    summary: str
    root_cause: str
    mechanism_summary: str = ""
    finding_analyses: list[FindingAnalysis] = Field(default_factory=list)
    incident_timeline: list[TimelineEvent] = Field(default_factory=list)
    causal_chain: list[str] = Field(default_factory=list)
    ruled_out_hypotheses: list[str] = Field(default_factory=list)
    evidence_citations: list[EvidenceCitation] = Field(default_factory=list)
    safe_fixes: list[str] = Field(default_factory=list)
    findings_used: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ClarifyingQuestion(BaseModel):
    id: str
    question: str
    rationale: str


class ClarifyingQuestionsBlock(BaseModel):
    run_id: str
    questions: list[ClarifyingQuestion]
    context_summary: str


class ClarifyingAnswers(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)


class InvestigationSummary(BaseModel):
    run_id: str
    summary: str
    findings_reviewed: list[str] = Field(default_factory=list)
    finding_analyses: list[FindingAnalysis] = Field(default_factory=list)
    incident_timeline: list[TimelineEvent] = Field(default_factory=list)
    mechanism_hypotheses: list[str] = Field(default_factory=list)
    tool_calls_made: list[str] = Field(default_factory=list)
    metric_insights: list[str] = Field(default_factory=list)
    log_insights: list[str] = Field(default_factory=list)
    web_insights: list[str] = Field(default_factory=list)
    open_questions_for_operator: list[str] = Field(default_factory=list)
