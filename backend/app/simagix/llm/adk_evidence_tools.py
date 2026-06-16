from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.simagix.evidence_service import SimagixEvidenceService
from backend.app.simagix.profiler import load_profiler_data
from backend.app.simagix.llm.web_fetch import execute_web_fetch


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class AdkEvidenceTools:
    """Function tools for Google ADK — same surface as mcp_evidence_server."""

    def __init__(self, evidence: SimagixEvidenceService) -> None:
        self._evidence = evidence

    def get_metric_window(
        self,
        metric: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return a time-windowed slice of a normalized fallback metric."""
        return self._evidence.get_metric_window(
            metric,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            limit=limit,
        )

    def get_normalized_series(
        self,
        metrics: list[str],
        start: str | None = None,
        end: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Return multiple normalized metric windows in one call."""
        return self._evidence.get_normalized_series(
            metrics,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            limit=limit,
        )

    def get_raw_path(
        self,
        path_contains: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Search tier-3 raw metric paths for forensic evidence."""
        return self._evidence.get_raw_path(
            path_contains,
            start=_parse_datetime(start),
            end=_parse_datetime(end),
            limit=limit,
        )

    def list_fallback_metrics(self, pattern: str | None = None) -> list[str]:
        """List indexed fallback metrics, optionally filtered by substring."""
        return self._evidence.list_fallback_metrics(pattern)

    def get_budget_status(self) -> dict[str, Any]:
        """Return remaining retrieval budget for this session."""
        return self._evidence.get_budget_status()

    def get_profiler_samples(self, limit: int = 50) -> dict[str, Any]:
        """Return MongoDB profiler samples uploaded for this run."""
        return load_profiler_data(self._evidence.workspace_root, self._evidence.run_id, limit=limit)

    def web_fetch(self, url: str) -> dict[str, Any]:
        """Fetch trusted HTTPS documentation (same policy as Cursor web_fetch)."""
        result, _status, _excerpt = execute_web_fetch(url)
        return result


def build_adk_evidence_tools(evidence: SimagixEvidenceService) -> list:
    """Return callables wired for ADK Agent(tools=...)."""
    toolkit = AdkEvidenceTools(evidence)
    return [
        toolkit.get_metric_window,
        toolkit.get_normalized_series,
        toolkit.get_raw_path,
        toolkit.list_fallback_metrics,
        toolkit.get_budget_status,
        toolkit.get_profiler_samples,
        toolkit.web_fetch,
    ]


def build_adk_agent_tools(evidence: SimagixEvidenceService) -> list:
    """Evidence function tools plus web_fetch (shared HTTPS policy)."""
    return build_adk_evidence_tools(evidence)
