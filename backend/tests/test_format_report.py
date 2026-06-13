from backend.app.simagix.format_report import format_rca_report_pretty, format_tool_usage_footer
from backend.app.simagix.output_schema import EvidenceCitation, RCAReportDraft


def test_format_rca_report_pretty_includes_sections() -> None:
    report = RCAReportDraft(
        run_id="run-1",
        summary="Replication lag caused stale reads.",
        root_cause="Secondary apply lag exceeded tolerance.",
        causal_chain=["Write load rose", "Lag grew", "Reads were stale"],
        ruled_out_hypotheses=["Disk saturation"],
        evidence_citations=[
            EvidenceCitation(
                source_type="finding",
                reference="Replication Lag Issues",
                summary="Critical lag finding",
            )
        ],
        safe_fixes=["Increase oplog retention"],
        findings_used=["Replication Lag Issues"],
        confidence=0.88,
    )

    text = format_rca_report_pretty(
        report,
        run_id="run-1",
        agent_id="agent-abc",
        provider="cursor",
        tool_usage={
            "mcp_evidence_calls": 2,
            "mcp_budget_max": 12,
            "total_sdk_calls": 5,
            "by_category": {"mcp": 2, "web": 1, "local": 2},
            "tool_call_history": ["get_normalized_series", "get_normalized_series"],
        },
        duration_seconds=51.2,
    )

    assert "RCA REPORT — run-1" in text
    assert "Provider: cursor" in text
    assert "Evidence MCP tools: 2/12" in text
    assert "SDK tools (trace): 5" in text
    assert "MCP calls: get_normalized_series, get_normalized_series" in text
    assert "SUMMARY" in text
    assert "Replication lag caused stale reads." in text
    assert "ROOT CAUSE" in text
    assert "1. Write load rose" in text
    assert "[finding] Replication Lag Issues" in text
    assert "SAFE FIXES" in text
    assert "CONFIDENCE: 88%" in text


def test_format_tool_usage_footer_uses_trace_when_budget_zero() -> None:
    footer = format_tool_usage_footer(
        {
            "mcp_evidence_calls": 7,
            "mcp_budget_max": 12,
            "total_sdk_calls": 22,
            "by_category": {"mcp": 7, "web": 2, "local": 11, "shell": 2},
        }
    )
    assert "Evidence MCP tools: 7/12" in footer
    assert "SDK tools (trace): 22" in footer
    assert "mcp=7" in footer
    assert "shell=2" in footer
