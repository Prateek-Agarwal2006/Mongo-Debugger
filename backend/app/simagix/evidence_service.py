from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.bundle import SimagixBundleLoader
from backend.app.simagix.fallback_tools import SimagixFallbackTools
from backend.app.simagix.grounding import GroundingRules
from backend.app.simagix.output_schema import RCAReportDraft
from backend.app.simagix.prompt import build_phase2_prompt
from backend.app.simagix.schemas import Tier1Context


class SimagixEvidenceService:
    """Evidence librarian over Simagix analyzed bundles (tier-1 load, gated tier-2 tools, budget)."""

    def __init__(
        self,
        workspace_root: Path,
        run_id: str,
        *,
        budget: RetrievalBudget | None = None,
        max_tool_calls: int = 12,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.run_id = run_id
        ws = RunWorkspace(self.workspace_root)
        self.bundle_dir = ws.exports_dir(run_id)
        self.loader = SimagixBundleLoader(self.bundle_dir)
        self.tools = SimagixFallbackTools(self.bundle_dir)
        self.budget = budget or RetrievalBudget(max_tool_calls=max_tool_calls)

    def load_tier1(self) -> Tier1Context:
        return self.loader.load_tier1(self.run_id)

    def get_prompt_context(self) -> dict[str, Any]:
        return self.loader.assemble_prompt_context(self.run_id)

    def get_metric_window(
        self,
        metric: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        self.budget.consume_tool_call("get_metric_window")
        return self.tools.get_metric_window(metric, start=start, end=end, limit=limit)

    def get_normalized_series(
        self,
        metrics: list[str],
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        self.budget.consume_tool_call("get_normalized_series")
        return self.tools.get_normalized_series(metrics, start=start, end=end, limit=limit)

    def get_raw_path(
        self,
        path_contains: str,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        self.budget.consume_tool_call("get_raw_path")
        return self.tools.get_raw_path(path_contains, start=start, end=end, limit=limit)

    def list_fallback_metrics(self, pattern: str | None = None) -> list[str]:
        return self.tools.list_fallback_metrics(pattern)

    def get_budget_status(self) -> dict[str, Any]:
        return self.budget.status()

    def build_phase2_llm_package(self) -> dict[str, Any]:
        context = self.get_prompt_context()
        return {
            "prompt": build_phase2_prompt(context),
            "context": context,
            "grounding_rules": GroundingRules().as_dict(),
            "retrieval_budget": self.budget.status(),
            "output_schema": RCAReportDraft.model_json_schema(),
            "available_tools": [
                "get_metric_window",
                "get_normalized_series",
                "get_raw_path",
                "list_fallback_metrics",
                "get_budget_status",
                "get_profiler_samples",
            ],
        }

    def create_report_draft_shell(self) -> RCAReportDraft:
        tier1 = self.load_tier1()
        return RCAReportDraft(
            run_id=self.run_id,
            summary="Pending LLM analysis in Phase 2.",
            root_cause="",
            causal_chain=[],
            ruled_out_hypotheses=[],
            evidence_citations=[],
            safe_fixes=[],
            findings_used=[finding.name for finding in tier1.findings],
        )
