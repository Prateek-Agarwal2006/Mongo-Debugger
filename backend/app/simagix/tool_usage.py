from __future__ import annotations

from typing import Any

from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.tool_trace import load_tool_trace


def tool_usage_summary(session: Phase2Session) -> dict[str, Any]:
    """Aggregate MCP budget and SDK tool trace for report footers."""
    budget = session.budget_status()
    trace = load_tool_trace(session.run_id, session.llm)
    summary = trace.get("summary", {})
    by_category: dict[str, int] = dict(summary.get("by_category", {}))
    mcp_from_trace = int(by_category.get("mcp", 0))
    mcp_from_budget = int(budget.get("tool_calls_used", 0))
    mcp_evidence_calls = max(mcp_from_trace, mcp_from_budget)
    return {
        "mcp_evidence_calls": mcp_evidence_calls,
        "mcp_budget_max": int(budget.get("max_tool_calls", 0)),
        "total_sdk_calls": int(summary.get("total", 0)),
        "by_category": by_category,
        "tool_call_history": list(budget.get("tool_call_history", [])),
    }


def resolve_tool_usage(session: Phase2Session) -> dict[str, Any]:
    """Prefer the snapshot persisted with the report; fall back to live trace + budget."""
    tool_usage = session.load_metadata().get("tool_usage")
    if isinstance(tool_usage, dict):
        return tool_usage
    return tool_usage_summary(session)
