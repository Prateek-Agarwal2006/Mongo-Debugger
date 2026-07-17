from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.evidence.loader import EvidenceLoader
from backend.app.simagix.evidence.ftdc_tools import FtdcTools
from backend.app.simagix.evidence.hatchet_tools import (
    HATCHET_MCP_TOOL_NAMES,
    build_hatchet_evidence_block,
    load_hatchet_summary,
)
from backend.app.simagix.evidence_block import build_phase2_prompt
from backend.app.simagix.grounding import GroundingRules
from backend.app.simagix.output_schema import RCAReportDraft
from backend.app.simagix.schemas import Tier1Context


class RcaService:
    """RCA evidence orchestrator: tier-1 load, budget-gated tier-2 tools."""

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
        self.loader = EvidenceLoader(run_id)
        self.tools = FtdcTools(run_id, workspace_root=workspace_root.resolve())
        self.budget = budget or RetrievalBudget(max_tool_calls=max_tool_calls)

    def load_tier1(self) -> Tier1Context:
        return self.loader.load_tier1()

    def get_prompt_context(self) -> dict[str, Any]:
        return self.loader.assemble_prompt_context()

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

    def list_fallback_metrics(self, pattern: str | None = None) -> list[str]:
        return self.tools.list_fallback_metrics(pattern)

    def list_raw_paths(self, pattern: str | None = None) -> dict[str, Any]:
        self.budget.consume_tool_call("list_raw_paths")
        return self.tools.list_raw_paths(pattern)

    def get_raw_window(
        self,
        paths: list[str],
        start_ts: float,
        end_ts: float,
    ) -> dict[str, Any]:
        self.budget.consume_tool_call("get_raw_window")
        return self.tools.get_raw_window(paths, start_ts, end_ts)

    def execute_plot_script(
        self,
        paths: list[str],
        start_ts: float,
        end_ts: float,
        script: str,
        finding_name: str | None = None,
    ) -> dict[str, Any]:
        # Budget-exempt: the LLM already paid for the discovery calls
        # (list_raw_paths / get_raw_window); the script runs in a Daytona
        # sandbox, never in this process.
        from backend.app.simagix.evidence.sandbox_plot import execute_plot_script
        return execute_plot_script(
            self.run_id,
            self.workspace_root,
            paths,
            start_ts,
            end_ts,
            script,
            finding_name=finding_name,
        )

    def get_budget_status(self) -> dict[str, Any]:
        return self.budget.status()

    def build_phase2_llm_package(self) -> dict[str, Any]:
        context = self.get_prompt_context()
        hatchet_summary = load_hatchet_summary(self.run_id)
        available_tools = [
            "get_metric_window",
            "get_normalized_series",
            "list_fallback_metrics",
            "list_raw_paths",
            "get_raw_window",
            "execute_plot_script",
            "get_budget_status",
        ]
        if hatchet_summary is not None:
            available_tools.extend(sorted(HATCHET_MCP_TOOL_NAMES))
        package: dict[str, Any] = {
            "prompt": build_phase2_prompt(context),
            "context": context,
            "grounding_rules": GroundingRules().as_dict(),
            "retrieval_budget": self.budget.status(),
            "output_schema": RCAReportDraft.model_json_schema(),
            "available_tools": available_tools,
        }
        if hatchet_summary is not None:
            package["hatchet_summary"] = hatchet_summary
            package["hatchet_evidence_block"] = build_hatchet_evidence_block(hatchet_summary)
        return package

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


# Backward-compatible alias so existing callers that import SimagixEvidenceService still work
# until they are updated to RcaService.
SimagixEvidenceService = RcaService
