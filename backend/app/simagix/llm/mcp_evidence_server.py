from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.evidence_service import SimagixEvidenceService
from backend.app.simagix.profiler import load_profiler_data


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _build_evidence_service() -> SimagixEvidenceService:
    run_id = os.environ["SIMAGIX_RUN_ID"]
    workspace_root = Path(os.environ["SIMAGIX_WORKSPACE_ROOT"])
    budget_path = Path(os.environ["SIMAGIX_BUDGET_STATE_PATH"])
    max_tool_calls = int(os.environ.get("SIMAGIX_MAX_TOOL_CALLS", "12"))
    budget = RetrievalBudget(max_tool_calls=max_tool_calls, sync_path=budget_path)
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
def get_raw_path(
    path_contains: str,
    start: str | None = None,
    end: str | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Search tier-3 raw metric paths for forensic evidence."""
    return _evidence_service().get_raw_path(
        path_contains,
        start=_parse_datetime(start),
        end=_parse_datetime(end),
        limit=limit,
    )


@mcp.tool()
def list_fallback_metrics(pattern: str | None = None) -> list[str]:
    """List indexed fallback metrics, optionally filtered by substring."""
    return _evidence_service().list_fallback_metrics(pattern)


@mcp.tool()
def get_budget_status() -> dict[str, Any]:
    """Return remaining retrieval budget for this session."""
    return _evidence_service().get_budget_status()


@mcp.tool()
def get_profiler_samples(limit: int = 50) -> dict[str, Any]:
    """Return MongoDB profiler samples uploaded for this run (db.system.profile JSON)."""
    service = _evidence_service()
    return load_profiler_data(service.workspace_root, service.run_id, limit=limit)


def main() -> None:
    required = ("SIMAGIX_RUN_ID", "SIMAGIX_WORKSPACE_ROOT", "SIMAGIX_BUDGET_STATE_PATH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
