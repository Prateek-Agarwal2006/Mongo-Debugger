from __future__ import annotations

from typing import Any

from backend.app.simagix.output_schema import EvidenceCitation, FindingAnalysis, RCAReportDraft, TimelineEvent


def format_tool_usage_footer(tool_usage: dict[str, Any] | None) -> str:
    if not tool_usage:
        return "Tools used: 0"
    by_cat = tool_usage.get("by_category", {})
    mcp = int(tool_usage.get("mcp_evidence_calls", 0))
    mcp_max = int(tool_usage.get("mcp_budget_max", 0))
    total = int(tool_usage.get("total_sdk_calls", 0))
    parts = [f"Evidence MCP tools: {mcp}/{mcp_max}" if mcp_max else f"Evidence MCP tools: {mcp}"]
    if total:
        cat_bits = ", ".join(
            f"{key}={by_cat[key]}"
            for key in ("mcp", "web", "local", "shell", "other")
            if by_cat.get(key)
        )
        parts.append(f"SDK tools (trace): {total}" + (f" ({cat_bits})" if cat_bits else ""))
    return " | ".join(parts)


def format_rca_report_pretty(
    report: RCAReportDraft,
    *,
    run_id: str,
    agent_id: str | None = None,
    provider: str | None = None,
    tool_usage: dict[str, Any] | None = None,
    tool_calls_used: int | None = None,
    tool_call_history: list[str] | None = None,
    duration_seconds: float | None = None,
) -> str:
    """Render an RCA report and run metadata as human-readable plain text."""
    width = 62
    divider = "=" * width

    meta_parts: list[str] = []
    if provider:
        meta_parts.append(f"Provider: {provider}")
    if agent_id:
        meta_parts.append(f"Agent: {agent_id}")
    if tool_usage is not None:
        meta_parts.append(format_tool_usage_footer(tool_usage))
    elif tool_calls_used is not None:
        meta_parts.append(f"Tools used: {tool_calls_used}")
    else:
        meta_parts.append("Tools used: 0")
    if duration_seconds is not None:
        meta_parts.append(f"Duration: {duration_seconds:.1f}s")

    lines: list[str] = [
        divider,
        f"  RCA REPORT — {run_id}",
        f"  {'  |  '.join(meta_parts)}",
    ]
    history = tool_call_history or (tool_usage or {}).get("tool_call_history") or []
    if history:
        lines.append(f"  MCP calls: {', '.join(history)}")
    lines.append(divider)
    lines.append("")

    lines.append("SUMMARY")
    lines.append(report.summary)
    lines.append("")

    lines.append("ROOT CAUSE")
    lines.append(report.root_cause)
    lines.append("")

    if report.mechanism_summary:
        lines.append("MECHANISM (WHY)")
        lines.append(report.mechanism_summary)
        lines.append("")

    if report.incident_timeline:
        lines.append("INCIDENT TIMELINE")
        for event in report.incident_timeline:
            lines.extend(_format_timeline_event(event))
        lines.append("")

    if report.finding_analyses:
        lines.append("FINDING ANALYSES (WHAT → WHY)")
        for analysis in report.finding_analyses:
            lines.extend(_format_finding_analysis(analysis))
        lines.append("")

    if report.causal_chain:
        lines.append("CAUSAL CHAIN")
        for index, step in enumerate(report.causal_chain, start=1):
            lines.append(f"  {index}. {step}")
        lines.append("")

    if report.ruled_out_hypotheses:
        lines.append("RULED OUT")
        for hypothesis in report.ruled_out_hypotheses:
            lines.append(f"  • {hypothesis}")
        lines.append("")

    if report.evidence_citations:
        lines.append("EVIDENCE")
        for citation in report.evidence_citations:
            lines.extend(_format_citation(citation))
        lines.append("")

    if report.safe_fixes:
        lines.append("SAFE FIXES")
        for fix in report.safe_fixes:
            lines.append(f"  • {fix}")
        lines.append("")

    if report.reference_urls:
        lines.append("REFERENCES (WEB)")
        for url in report.reference_urls:
            lines.append(f"  • {url}")
        lines.append("")

    if report.findings_used:
        lines.append(f"FINDINGS USED: {', '.join(report.findings_used)}")
        lines.append("")

    if report.confidence is not None:
        lines.append(f"CONFIDENCE: {report.confidence * 100:.0f}%")

    return "\n".join(lines).rstrip() + "\n"


def _format_citation(citation: EvidenceCitation) -> list[str]:
    lines = [f"  • [{citation.source_type}] {citation.reference}"]
    lines.append(f"    {citation.summary}")
    if citation.values:
        for key, value in citation.values.items():
            lines.append(f"    {key}: {value}")
    return lines


def _format_finding_analysis(analysis: FindingAnalysis) -> list[str]:
    lines = [f"  ▶ {analysis.finding_name}"]
    if analysis.time_window:
        lines.append(f"    Window: {analysis.time_window}")
    lines.append(f"    What: {analysis.what_observed}")
    lines.append(f"    Why:  {analysis.why_it_happened}")
    if analysis.contributing_factors:
        lines.append("    Contributing factors:")
        for factor in analysis.contributing_factors:
            lines.append(f"      - {factor}")
    if analysis.related_metrics:
        lines.append(f"    Metrics: {', '.join(analysis.related_metrics)}")
    return lines


def _format_timeline_event(event: TimelineEvent) -> list[str]:
    return [
        f"  • {event.time_window}",
        f"    Observed: {event.observation}",
        f"    Mechanism: {event.mechanism}",
        f"    Metrics: {', '.join(event.metrics_involved) if event.metrics_involved else 'n/a'}",
    ]
