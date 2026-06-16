from __future__ import annotations

import time
from typing import Any

from backend.app.simagix.llm.detail_requirements import MOCK_MECHANISM_STUB, MOCK_WHY_STUB
from backend.app.simagix.llm.provider import LLMProvider, ChatbotResult, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.tool_trace import write_mock_tool_trace
from backend.app.simagix.output_schema import (
    ClarifyingQuestion,
    ClarifyingQuestionsBlock,
    EvidenceCitation,
    FindingAnalysis,
    InvestigationSummary,
    RCAReportDraft,
    TimelineEvent,
)
from backend.app.simagix.profiler import load_profiler_data


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _what_observed_from_finding(finding: Any) -> str:
    description = _field(finding, "description", "")
    symptoms = list(_field(finding, "symptoms", []) or [])
    symptom_text = "; ".join(symptoms) if symptoms else ""
    if description and symptom_text:
        return f"{description} Symptoms: {symptom_text}"
    return description or symptom_text or f"Finding: {_field(finding, 'name', 'unknown')}"


def _related_metric_names(windows: list[Any], *, limit: int = 8) -> list[str]:
    names: list[str] = []
    for window in windows[:limit]:
        metric = _field(window, "metric")
        if metric and metric not in names:
            names.append(str(metric))
    return names


def _mock_finding_analyses(findings: list[Any], windows: list[Any]) -> list[FindingAnalysis]:
    related = _related_metric_names(windows)
    analyses: list[FindingAnalysis] = []
    for finding in findings:
        analyses.append(
            FindingAnalysis(
                finding_name=_field(finding, "name", "unknown"),
                what_observed=_what_observed_from_finding(finding),
                why_it_happened=MOCK_WHY_STUB,
                contributing_factors=[],
                related_metrics=related,
                time_window=str(_field(finding, "detected_at")) if _field(finding, "detected_at") else None,
            )
        )
    return analyses


def _mock_incident_timeline(windows: list[Any], *, limit: int = 6) -> list[TimelineEvent]:
    events: list[TimelineEvent] = []
    for window in windows[:limit]:
        metric = _field(window, "metric", "unknown")
        start = _field(window, "from_") or _field(window, "from")
        end = _field(window, "to")
        peak = _field(window, "peak")
        severity = _field(window, "severity", "n/a")
        events.append(
            TimelineEvent(
                time_window=f"{metric} @ {start} → {end}",
                observation=f"{metric} peaked at {peak} (severity: {severity})",
                mechanism=MOCK_MECHANISM_STUB,
                metrics_involved=[str(metric)],
            )
        )
    return events


class MockLLMProvider(LLMProvider):
    """Deterministic provider for unit tests (no Cursor API key required)."""

    _METRICS_TO_SAMPLE = (
        "cache_used",
        "ticket_avail_read",
        "ticket_avail_write",
    )

    def __init__(self, *, delay_seconds: float = 0.0) -> None:
        self.delay_seconds = delay_seconds

    @property
    def provider_name(self) -> str:
        return "mock"

    def _sample_metric_insights(self, session: Phase2Session) -> list[str]:
        insights: list[str] = []
        for metric in self._METRICS_TO_SAMPLE:
            try:
                window = session.evidence.get_metric_window(metric, limit=5)
                points = window.get("points") or []
                if points:
                    last = points[-1]
                    value = last.get("value", last.get("v"))
                    ts = last.get("timestamp", last.get("t", ""))
                    insights.append(f"metric:{metric}@{ts} value={value} (samples={window.get('point_count', 0)})")
                else:
                    insights.append(f"metric:{metric} samples={window.get('point_count', 0)} (no points in slice)")
            except Exception:
                insights.append(f"metric:{metric} unavailable in fixture")
        return insights

    def run_investigation(self, session: Phase2Session, user_message: str) -> InvestigationSummary:
        tier1 = session.evidence.load_tier1()
        exec_ctx = tier1.executive_context
        findings = [finding.name for finding in exec_ctx.findings]
        finding_analyses = _mock_finding_analyses(exec_ctx.findings, exec_ctx.top_anomaly_windows)
        incident_timeline = _mock_incident_timeline(exec_ctx.top_anomaly_windows)
        tool_calls = ["get_metric_window", "get_profiler_samples"]

        metric_insights = self._sample_metric_insights(session)

        profiler_insights: list[str] = []
        profiler = load_profiler_data(session.workspace_root, session.run_id)
        if profiler.get("available"):
            profiler_insights.append(
                f"profiler: {profiler.get('sample_count', 0)} samples uploaded"
            )
        else:
            profiler_insights.append("profiler: not uploaded for this run")

        open_questions: list[str] = [
            "Live agent: call get_metric_window around top anomaly windows before stating mechanism."
        ]

        web_insights = [
            "https://www.mongodb.com/docs/manual/core/wiredtiger/ — schema demo placeholder URL",
        ]

        write_mock_tool_trace(session.tool_trace_path, run_id=session.run_id, phase="investigation")

        return InvestigationSummary(
            run_id=session.run_id,
            summary=(
                f"[mock] Schema placeholder: reviewed {len(findings)} tier-1 findings and "
                f"{exec_ctx.anomaly_event_count} anomaly events on {exec_ctx.host}. "
                "Mechanism fields are stubs — not a concluded RCA."
            ),
            findings_reviewed=findings,
            finding_analyses=finding_analyses,
            incident_timeline=incident_timeline,
            mechanism_hypotheses=[MOCK_WHY_STUB],
            tool_calls_made=tool_calls,
            metric_insights=metric_insights,
            log_insights=["graylog: not queried in mock mode"],
            profiler_insights=profiler_insights,
            web_insights=web_insights,
            open_questions_for_operator=open_questions,
        )

    def generate_clarifying_questions(
        self,
        session: Phase2Session,
        user_message: str,
        *,
        max_questions: int,
    ) -> ClarifyingQuestionsBlock:
        tier1 = session.evidence.load_tier1()
        exec_ctx = tier1.executive_context
        questions: list[ClarifyingQuestion] = []

        investigation = session.load_investigation()
        seed_questions = list(investigation.open_questions_for_operator) if investigation else []

        for idx, seed in enumerate(seed_questions[:max_questions]):
            questions.append(
                ClarifyingQuestion(
                    id=f"open_q_{idx}",
                    question=seed,
                    rationale="Unresolved after tier-2 investigation; requires operator context.",
                )
            )

        for finding in exec_ctx.findings:
            if len(questions) >= max_questions:
                break
            slug = finding.name.lower().replace(" ", "_")[:40]
            questions.append(
                ClarifyingQuestion(
                    id=f"context_{slug}",
                    question=f"Was there any operational change related to '{finding.name}' during the incident window?",
                    rationale=f"Tier-1 flagged '{finding.name}'; operator context can separate workload vs infra causes.",
                )
            )

        if len(questions) < max_questions and exec_ctx.top_anomaly_windows:
            window = exec_ctx.top_anomaly_windows[0]
            questions.append(
                ClarifyingQuestion(
                    id="anomaly_window_context",
                    question=(
                        f"Any deployments or config changes near {window.from_.isoformat()} "
                        f"when {window.metric} peaked?"
                    ),
                    rationale="Top anomaly window may correlate with a release or maintenance event.",
                )
            )

        return ClarifyingQuestionsBlock(
            run_id=session.run_id,
            questions=questions[:max_questions],
            context_summary=(
                f"Mock clarify pass for {len(exec_ctx.findings)} findings "
                f"and {exec_ctx.anomaly_event_count} anomaly events."
            ),
        )

    def run(self, session: Phase2Session, user_message: str) -> Phase2RunResult:
        started = time.monotonic()
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

        tier1 = session.evidence.load_tier1()
        exec_ctx = tier1.executive_context
        findings_used = [finding.name for finding in tier1.findings]
        finding_analyses = _mock_finding_analyses(exec_ctx.findings, exec_ctx.top_anomaly_windows)
        incident_timeline = _mock_incident_timeline(exec_ctx.top_anomaly_windows)

        primary_name = findings_used[0] if findings_used else "unknown"
        primary_analysis = finding_analyses[0] if finding_analyses else None

        reference_urls = [
            "https://www.mongodb.com/docs/manual/core/wiredtiger/",
        ]

        safe_fixes: list[str] = []
        for finding in exec_ctx.findings:
            if finding.suggestion:
                safe_fixes.append(f"[{finding.name}] {finding.suggestion}")
        if not safe_fixes:
            safe_fixes.append("[mock] No tier-1 suggestions available")

        evidence_citations = [
            EvidenceCitation(
                source_type="finding",
                reference=primary_name,
                summary=primary_analysis.what_observed if primary_analysis else "Primary tier-1 finding",
            ),
        ]
        for window in exec_ctx.top_anomaly_windows[:3]:
            evidence_citations.append(
                EvidenceCitation(
                    source_type="anomaly",
                    reference=f"anomaly:{window.metric}",
                    summary=f"Peak {window.peak} from {window.from_} to {window.to}",
                    values={"severity": window.severity, "threshold": window.threshold},
                )
            )

        report = RCAReportDraft(
            run_id=session.run_id,
            summary=(
                f"[mock] Schema placeholder for run on {exec_ctx.host}. "
                f"Tier-1 flagged {len(findings_used)} findings; mechanism fields are stubs, not concluded RCA."
            ),
            root_cause=MOCK_WHY_STUB,
            mechanism_summary=MOCK_MECHANISM_STUB,
            finding_analyses=finding_analyses,
            incident_timeline=incident_timeline,
            causal_chain=[
                f"Tier-1 flagged '{primary_name}': {primary_analysis.what_observed}" if primary_analysis else "[mock] no findings",
                MOCK_WHY_STUB,
            ],
            ruled_out_hypotheses=[
                "[mock] Mechanism hypotheses not evaluated — use live agent with MCP tools",
            ],
            evidence_citations=evidence_citations,
            safe_fixes=safe_fixes,
            findings_used=findings_used,
            reference_urls=reference_urls,
            confidence=None,
        )
        write_mock_tool_trace(session.tool_trace_path, run_id=session.run_id, phase="final_rca")
        session.persist_report(report)

        return Phase2RunResult(
            report=report,
            agent_id="mock-agent-id",
            run_id=session.run_id,
            tool_calls_used=session.budget_status()["tool_calls_used"],
            duration_seconds=time.monotonic() - started,
            raw_assistant_text=report.model_dump_json(indent=2),
        )

    def run_chatbot(self, session: Phase2Session, user_message: str) -> ChatbotResult:
        report = session.load_persisted_report()
        if report is None:
            return ChatbotResult(content="No report available for this run.")
        q = user_message.lower()
        if "root cause" in q or "why" in q:
            reply = f"Root cause: {report.root_cause}"
        elif "fix" in q or "remediation" in q:
            fixes = report.safe_fixes or []
            reply = "Safe fixes:\n• " + "\n• ".join(fixes) if fixes else "No safe fixes listed."
        elif "summary" in q:
            reply = report.summary or "No summary in report."
        else:
            reply = (
                f"[mock chatbot] From report summary: {report.summary}\n"
                "Ask about root cause, fixes, or summary. Live agents use MCP + tools."
            )
        write_mock_tool_trace(session.tool_trace_path, run_id=session.run_id, phase="chatbot")
        return ChatbotResult(content=reply, tool_calls_used=0)

    def summarize_chat_history(
        self,
        session: Phase2Session,
        messages_to_fold: list[dict[str, str]],
        *,
        prior_summary: str | None = None,
    ) -> str:
        bullets: list[str] = []
        if prior_summary:
            bullets.append(prior_summary.strip())
        for msg in messages_to_fold:
            role = msg.get("role", "?")
            content = (msg.get("content") or "").strip()
            preview = content[:120] + ("…" if len(content) > 120 else "")
            bullets.append(f"- {role}: {preview}")
        return "\n".join(bullets)
