from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.hatchet_tools import HatchetEvidenceTools

mcp = FastMCP("hatchet-evidence")

_SERVICE: HatchetEvidenceTools | None = None


def _build_service() -> HatchetEvidenceTools:
    run_id = os.environ["SIMAGIX_RUN_ID"]
    workspace_root = Path(os.environ["SIMAGIX_WORKSPACE_ROOT"])
    budget_path = Path(os.environ["SIMAGIX_BUDGET_STATE_PATH"])
    max_tool_calls = int(os.environ.get("SIMAGIX_MAX_TOOL_CALLS", "12"))
    budget = RetrievalBudget(max_tool_calls=max_tool_calls, sync_path=budget_path)
    budget.sync_load()
    return HatchetEvidenceTools(workspace_root, run_id, budget=budget)


def _service() -> HatchetEvidenceTools:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _build_service()
    return _SERVICE


@mcp.tool()
def get_hatchet_slow_ops(
    sort_by: str = "avg_ms",
    limit: int = 20,
    collscan_only: bool = False,
) -> dict[str, Any]:
    """Return slow-operation rollups from Hatchet SQLite (tier-2 log evidence)."""
    order: str = "total_ms" if sort_by == "total_ms" else "avg_ms"
    return _service().get_hatchet_slow_ops(sort_by=order, limit=limit, collscan_only=collscan_only)  # type: ignore[arg-type]


@mcp.tool()
def get_hatchet_log_examples(limit: int = 10, min_milli: float = 0) -> dict[str, Any]:
    """Return slowest MongoDB log line examples with capped snippets."""
    return _service().get_hatchet_log_examples(limit=limit, min_milli=min_milli)


@mcp.tool()
def get_hatchet_audit(audit_type: str | None = None, limit: int = 40) -> dict[str, Any]:
    """Return Hatchet audit rollups (exceptions, namespaces, drivers, etc.)."""
    return _service().get_hatchet_audit(audit_type=audit_type, limit=limit)


@mcp.tool()
def get_hatchet_connection_timeline(limit: int = 48) -> dict[str, Any]:
    """Return connection accepted/ended counts per minute bucket."""
    return _service().get_hatchet_connection_timeline(limit=limit)


def main() -> None:
    required = ("SIMAGIX_RUN_ID", "SIMAGIX_WORKSPACE_ROOT", "SIMAGIX_BUDGET_STATE_PATH")
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
