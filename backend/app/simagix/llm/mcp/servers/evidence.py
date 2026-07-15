from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.rca_service import SimagixEvidenceService


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _build_evidence_service() -> SimagixEvidenceService:
    run_id = os.environ["SIMAGIX_RUN_ID"]
    workspace_root = Path(os.environ["SIMAGIX_WORKSPACE_ROOT"])
    llm = os.environ["SIMAGIX_LLM"]
    max_tool_calls = int(os.environ.get("SIMAGIX_MAX_TOOL_CALLS", "12"))
    budget = RetrievalBudget(max_tool_calls=max_tool_calls, run_id=run_id, llm=llm)
    budget.sync_load()
    return SimagixEvidenceService(workspace_root, run_id, budget=budget, max_tool_calls=max_tool_calls)


_EVIDENCE_SERVICE: SimagixEvidenceService | None = None


def _evidence_service() -> SimagixEvidenceService:
    global _EVIDENCE_SERVICE
    if _EVIDENCE_SERVICE is None:
        _EVIDENCE_SERVICE = _build_evidence_service()
    return _EVIDENCE_SERVICE


mcp = FastMCP("simagix-evidence")


@mcp.tool()
def get_metric_window(
    metric: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return a time-windowed slice of a normalized fallback metric."""
    return _evidence_service().get_metric_window(
        metric,
        start=_parse_datetime(start),
        end=_parse_datetime(end),
        limit=limit,
    )


@mcp.tool()
def get_normalized_series(
    metrics: list[str],
    start: str | None = None,
    end: str | None = None,
    limit: int = 500,
) -> dict[str, Any]:
    """Return multiple normalized metric windows in one call."""
    return _evidence_service().get_normalized_series(
        metrics,
        start=_parse_datetime(start),
        end=_parse_datetime(end),
        limit=limit,
    )


@mcp.tool()
def list_fallback_metrics(pattern: str | None = None) -> list[str]:
    """List indexed fallback metrics, optionally filtered by substring."""
    return _evidence_service().list_fallback_metrics(pattern)


@mcp.tool()
def list_raw_paths(pattern: str | None = None) -> dict[str, Any]:
    """Return the raw FTDC path taxonomy or filter paths by substring.

    Call with no arguments to see the top-level prefix map (~30 buckets).
    Each key is a top-level FTDC namespace (e.g. "serverStatus", "systemMetrics");
    the value is the list of full paths under that namespace.

    Pass a substring to search for specific paths
    (e.g. pattern="wiredTiger/cache" → all cache-related metrics).

    Use the returned path names verbatim in get_raw_window().
    """
    return _evidence_service().list_raw_paths(pattern)


@mcp.tool()
def get_raw_window(
    paths: list[str],
    start_ts: float,
    end_ts: float,
) -> dict[str, Any]:
    """Return per-second time series for the named raw FTDC paths in [start_ts, end_ts].

    paths: list of exact FTDC path strings from list_raw_paths().
    start_ts / end_ts: epoch seconds (float).

    Returns {"series": {path: [[ts, value], ...]}, "coverage_gaps": [...], "files_processed": N}.
    Uses raw_file_index to read only the files that overlap the window.
    """
    return _evidence_service().get_raw_window(paths, start_ts, end_ts)


@mcp.tool()
def get_budget_status() -> dict[str, Any]:
    """Return remaining retrieval budget for this session."""
    return _evidence_service().get_budget_status()


def main() -> None:
    required = ("SIMAGIX_RUN_ID", "SIMAGIX_WORKSPACE_ROOT", "SIMAGIX_LLM", "DATABASE_URL")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
