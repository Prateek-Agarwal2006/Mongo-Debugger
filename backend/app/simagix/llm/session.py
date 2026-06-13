from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.orchestrator import SimagixRCAOrchestrator
from backend.app.simagix.output_schema import InvestigationSummary, RCAReportDraft


def phase2_session_dir(workspace_root: Path, run_id: str) -> Path:
    return workspace_root / "simagix-workspace/runs" / run_id / "phase2"


@dataclass
class Phase2Session:
    run_id: str
    workspace_root: Path
    orchestrator: SimagixRCAOrchestrator
    session_dir: Path
    agent_id: str | None = None
    latest_report: RCAReportDraft | None = None
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None

    @classmethod
    def create(
        cls,
        workspace_root: Path,
        run_id: str,
        *,
        max_tool_calls: int = 12,
    ) -> Phase2Session:
        session_dir = phase2_session_dir(workspace_root, run_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        budget_path = session_dir / "budget_state.json"
        budget = RetrievalBudget(max_tool_calls=max_tool_calls, sync_path=budget_path)
        budget.sync_load()
        if not budget_path.exists():
            budget.sync_save()
        orchestrator = SimagixRCAOrchestrator(
            workspace_root,
            run_id,
            budget=budget,
            max_tool_calls=max_tool_calls,
        )
        return cls(
            run_id=run_id,
            workspace_root=workspace_root.resolve(),
            orchestrator=orchestrator,
            session_dir=session_dir,
        )

    @property
    def budget_state_path(self) -> Path:
        return self.session_dir / "budget_state.json"

    @property
    def report_path(self) -> Path:
        return self.session_dir / "latest_report.json"

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / "session_metadata.json"

    @property
    def investigation_path(self) -> Path:
        return self.session_dir / "investigation.json"

    @property
    def tool_trace_path(self) -> Path:
        return self.session_dir / "tool_trace.json"

    def configure_budget(self, max_tool_calls: int, *, reset: bool = False) -> None:
        if reset:
            self.orchestrator.budget.tool_calls_used = 0
            self.orchestrator.budget.tool_call_history = []
        self.orchestrator.budget.max_tool_calls = max_tool_calls
        self.orchestrator.budget.sync_save()

    def persist_investigation(self, investigation: InvestigationSummary) -> None:
        self.investigation_path.write_text(investigation.model_dump_json(indent=2), encoding="utf-8")

    def load_investigation(self) -> InvestigationSummary | None:
        if not self.investigation_path.exists():
            return None
        return InvestigationSummary.model_validate_json(
            self.investigation_path.read_text(encoding="utf-8")
        )

    def mcp_server_env(self) -> dict[str, str]:
        return {
            "SIMAGIX_RUN_ID": self.run_id,
            "SIMAGIX_WORKSPACE_ROOT": str(self.workspace_root),
            "SIMAGIX_BUDGET_STATE_PATH": str(self.budget_state_path),
            "SIMAGIX_MAX_TOOL_CALLS": str(self.orchestrator.budget.max_tool_calls),
        }

    def refresh_budget(self) -> None:
        self.orchestrator.budget.sync_load()

    def budget_status(self) -> dict[str, Any]:
        self.refresh_budget()
        return self.orchestrator.get_budget_status()

    def persist_report(self, report: RCAReportDraft, *, agent_id: str | None = None, provider: str | None = None) -> None:
        from backend.app.simagix.tool_usage import tool_usage_summary

        self.latest_report = report
        self.report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        if agent_id:
            self.agent_id = agent_id
        metadata = {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "provider": provider,
            "last_run_at": time.time(),
            "budget": self.budget_status(),
            "tool_usage": tool_usage_summary(self),
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")

    def load_persisted_report(self) -> RCAReportDraft | None:
        if self.latest_report is not None:
            return self.latest_report
        if not self.report_path.exists():
            return None
        self.latest_report = RCAReportDraft.model_validate_json(self.report_path.read_text(encoding="utf-8"))
        if self.metadata_path.exists():
            meta = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            self.agent_id = meta.get("agent_id")
            self.last_run_at = meta.get("last_run_at")
        return self.latest_report


class Phase2SessionStore:
    """Session store keyed by run_id; reports persist under simagix-workspace/runs/<run_id>/phase2/."""

    def __init__(self) -> None:
        self._sessions: dict[str, Phase2Session] = {}

    def get_or_create(
        self,
        run_id: str,
        workspace_root: Path,
        *,
        max_tool_calls: int = 12,
    ) -> Phase2Session:
        session = self._sessions.get(run_id)
        if session is None:
            session = Phase2Session.create(workspace_root, run_id, max_tool_calls=max_tool_calls)
            session.load_persisted_report()
            self._sessions[run_id] = session
        return session

    def get(self, run_id: str) -> Phase2Session | None:
        return self._sessions.get(run_id)

    def get_or_load(self, run_id: str, workspace_root: Path) -> Phase2Session | None:
        session = self.get(run_id)
        if session is not None:
            return session
        report_path = phase2_session_dir(workspace_root, run_id) / "latest_report.json"
        if not report_path.exists():
            return None
        session = Phase2Session.create(workspace_root, run_id)
        session.load_persisted_report()
        self._sessions[run_id] = session
        return session

    def reset(self, run_id: str) -> None:
        self._sessions.pop(run_id, None)


phase2_session_store = Phase2SessionStore()
