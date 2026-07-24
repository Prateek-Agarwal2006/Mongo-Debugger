"""Provider-neutral sub-agent definitions for Phase 2 agentic RCA.

Each provider (Claude Agent SDK, Cursor SDK, ADK) converts these specs
into its SDK-specific format. The parent agent's prompt instructs it to
delegate to these sub-agents by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SubAgentSpec:
    name: str
    description: str
    prompt: str
    mcp_server_ids: list[str] = field(default_factory=list)
    max_turns: int = 25


FINDING_ANALYZER = SubAgentSpec(
    name="finding-analyzer",
    description=(
        "Deep-dive a single simagix finding using Tier 2 normalized metrics "
        "and Tier 3 raw FTDC paths. Returns finding_analysis JSON with "
        "evidence_citations and optional charts."
    ),
    prompt=(
        "You are investigating ONE specific MongoDB FTDC finding. The parent "
        "will tell you which finding and its time window.\n\n"
        "Steps:\n"
        "1. Call get_metric_window / get_normalized_series for Tier 2 evidence.\n"
        "2. Call list_raw_paths to discover raw FTDC paths related to this finding.\n"
        "3. Call get_raw_window for Tier 3 mechanism proof — this is MANDATORY.\n"
        "4. Optionally call execute_plot_script to create a chart.\n"
        "5. Call get_budget_status to check remaining budget.\n\n"
        "Return a JSON object with keys: finding_name, what_observed, "
        "why_it_happened, contributing_factors, related_metrics, time_window, "
        "evidence_citations (array of {source_type, reference, summary, values}), "
        "charts (array of {chart_id, metric_paths, time_window, caption, finding_name}).\n\n"
        "Do NOT investigate other findings. Focus only on the one assigned to you."
    ),
    mcp_server_ids=["simagix-evidence"],
    max_turns=20,
)

LOG_INVESTIGATOR = SubAgentSpec(
    name="log-investigator",
    description=(
        "Investigate MongoDB logs and slow operations around the incident "
        "time window using Graylog and Hatchet tools. Returns log-based "
        "evidence, timeline events, and ruled-out hypotheses."
    ),
    prompt=(
        "You investigate MongoDB logs and slow operations around the incident.\n\n"
        "Steps:\n"
        "1. Call query_logs_around_window with relevant queries for the incident window.\n"
        "2. Call get_hatchet_slow_ops to find slow operation rollups.\n"
        "3. Call get_hatchet_log_examples for the slowest log line examples.\n"
        "4. Call get_hatchet_audit for exception/namespace/driver rollups.\n"
        "5. Call get_hatchet_connection_timeline for connection patterns.\n\n"
        "Return a JSON object with keys:\n"
        "- log_evidence: array of {source_type: 'log', reference, summary, values}\n"
        "- timeline_events: array of {time_window, observation, mechanism, metrics_involved}\n"
        "- ruled_out_hypotheses: array of strings — what log evidence ruled out\n"
        "- slow_op_summary: string summary of slow operation patterns\n\n"
        "Be thorough — logs are an independent evidence source not biased by simagix findings."
    ),
    mcp_server_ids=["graylog", "hatchet-evidence"],
    max_turns=15,
)

DOC_RESEARCHER = SubAgentSpec(
    name="doc-researcher",
    description=(
        "Look up MongoDB documentation for known issues, recommended fixes, "
        "and best practices related to the incident. Returns safe_fixes and "
        "reference_urls with web evidence citations."
    ),
    prompt=(
        "You research MongoDB documentation for fixes and best practices.\n\n"
        "The parent will describe the incident root cause and mechanism. Your job:\n"
        "1. Use web_fetch to retrieve relevant MongoDB documentation pages.\n"
        "2. Look for known issues, recommended configuration changes, and best practices.\n"
        "3. Prioritize official MongoDB docs (mongodb.com/docs).\n\n"
        "Return a JSON object with keys:\n"
        "- safe_fixes: array of strings — actionable remediation steps with doc links\n"
        "- reference_urls: array of strings — all URLs you consulted\n"
        "- web_evidence: array of {source_type: 'web', reference, summary, values}\n\n"
        "Only cite URLs you actually fetched. Do not hallucinate URLs."
    ),
    mcp_server_ids=["web-fetch"],
    max_turns=10,
)

ALL_SUBAGENTS: list[SubAgentSpec] = [FINDING_ANALYZER, LOG_INVESTIGATOR, DOC_RESEARCHER]


def available_subagents(active_server_ids: set[str]) -> list[SubAgentSpec]:
    """Filter sub-agents to those whose required MCP servers are available."""
    result: list[SubAgentSpec] = []
    for spec in ALL_SUBAGENTS:
        if not spec.mcp_server_ids:
            result.append(spec)
            continue
        if any(sid in active_server_ids for sid in spec.mcp_server_ids):
            result.append(spec)
    return result
