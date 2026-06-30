from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.evidence_service import SimagixEvidenceService
from backend.app.simagix.llm.llm_paths import (
    LLM_FOLDER_NAMES,
    llm_has_artifacts,
    llm_session_dir,
    phase2_root_dir,
)
from backend.app.simagix.llm.parse_output import load_persisted_rca_report
from backend.app.simagix.output_schema import InvestigationSummary, RCAReportDraft


def phase2_session_dir(workspace_root: Path, run_id: str) -> Path:
    """Phase 2 root for a run (contains llm/ subfolders)."""
    return phase2_root_dir(workspace_root, run_id)


@dataclass
class Phase2Session:
    run_id: str
    llm: str
    workspace_root: Path
    evidence: SimagixEvidenceService
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
        llm: str,
        *,
        max_tool_calls: int = 12,
    ) -> Phase2Session:
        if llm not in LLM_FOLDER_NAMES:
            raise ValueError(f"Unknown llm folder: {llm}")
        session_dir = llm_session_dir(workspace_root, run_id, llm)
        session_dir.mkdir(parents=True, exist_ok=True)
        scratch_dir = session_dir / "chatbot_scratch"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        budget_path = session_dir / "budget_state.json"
        budget = RetrievalBudget(max_tool_calls=max_tool_calls, sync_path=budget_path)
        budget.sync_load()
        if not budget_path.exists():
            budget.sync_save()
        evidence = SimagixEvidenceService(
            workspace_root,
            run_id,
            budget=budget,
            max_tool_calls=max_tool_calls,
        )
        return cls(
            run_id=run_id,
            llm=llm,
            workspace_root=workspace_root.resolve(),
            evidence=evidence,
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

    @property
    def chatbot_scratch_dir(self) -> Path:
        return self.session_dir / "chatbot_scratch"

    @property
    def chatbot_chat_path(self) -> Path:
        return self.session_dir / "chatbot_chat.json"

    def ensure_chatbot_scratch_dir(self) -> Path:
        self.chatbot_scratch_dir.mkdir(parents=True, exist_ok=True)
        return self.chatbot_scratch_dir

    def configure_budget(self, max_tool_calls: int, *, reset: bool = False) -> None:
        if reset:
            self.evidence.budget.tool_calls_used = 0
            self.evidence.budget.tool_call_history = []
        self.evidence.budget.max_tool_calls = max_tool_calls
        self.evidence.budget.sync_save()

    def persist_investigation(self, investigation: InvestigationSummary) -> None:
        self.investigation_path.write_text(investigation.model_dump_json(indent=2), encoding="utf-8")

    def load_investigation(self) -> InvestigationSummary | None:
        if not self.investigation_path.exists():
            return None
        return InvestigationSummary.model_validate_json(
            self.investigation_path.read_text(encoding="utf-8")
        )

    def mcp_server_env(self) -> dict[str, str]:
        workspace = str(self.workspace_root)
        pythonpath = workspace
        existing = os.environ.get("PYTHONPATH", "")
        if existing:
            pythonpath = f"{workspace}{os.pathsep}{existing}"
        return {
            "SIMAGIX_RUN_ID": self.run_id,
            "SIMAGIX_WORKSPACE_ROOT": workspace,
            "SIMAGIX_BUDGET_STATE_PATH": str(self.budget_state_path),
            "SIMAGIX_MAX_TOOL_CALLS": str(self.evidence.budget.max_tool_calls),
            "PYTHONPATH": pythonpath,
        }

    def refresh_budget(self) -> None:
        self.evidence.budget.sync_load()

    def budget_status(self) -> dict[str, Any]:
        self.refresh_budget()
        return self.evidence.get_budget_status()

    def persist_report(self, report: RCAReportDraft, *, agent_id: str | None = None, provider: str | None = None) -> None:
        from backend.app.simagix.tool_usage import tool_usage_summary

        self.latest_report = report
        self.report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        if agent_id:
            self.agent_id = agent_id
        metadata = {
            "run_id": self.run_id,
            "llm": self.llm,
            "agent_id": self.agent_id,
            "provider": provider,
            "last_run_at": time.time(),
            "budget": self.budget_status(),
            "tool_usage": tool_usage_summary(self),
        }
        self.metadata_path.write_text(json.dumps(metadata, indent=2, default=str), encoding="utf-8")
        self.last_run_at = metadata["last_run_at"]

    def load_persisted_report(self) -> RCAReportDraft | None:
        if self.latest_report is not None:
            return self.latest_report
        if not self.report_path.exists():
            return None
        self.latest_report = load_persisted_rca_report(
            self.report_path.read_text(encoding="utf-8"),
            self.run_id,
        )
        if self.metadata_path.exists():
            meta = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            self.agent_id = meta.get("agent_id")
            self.last_run_at = meta.get("last_run_at")
        return self.latest_report


class Phase2SessionStore:
    """Session store keyed by (run_id, llm); artifacts under phase2/llm/<llm>/."""

    def __init__(self) -> None:
        self._sessions: dict[str, Phase2Session] = {}

    @staticmethod
    def _cache_key(run_id: str, llm: str) -> str:
        return f"{run_id}:{llm}"

    def get_or_create(
        self,
        run_id: str,
        workspace_root: Path,
        *,
        llm: str,
        max_tool_calls: int = 12,
    ) -> Phase2Session:
        key = self._cache_key(run_id, llm)
        session = self._sessions.get(key)
        if session is None:
            session = Phase2Session.create(workspace_root, run_id, llm, max_tool_calls=max_tool_calls)
            session.load_persisted_report()
            self._sessions[key] = session
        return session

    def get(self, run_id: str, llm: str) -> Phase2Session | None:
        return self._sessions.get(self._cache_key(run_id, llm))

    def get_or_load(self, run_id: str, workspace_root: Path, llm: str) -> Phase2Session | None:
        session = self.get(run_id, llm)
        if session is not None:
            return session
        if not llm_has_artifacts(workspace_root, run_id, llm):
            return None
        session = Phase2Session.create(workspace_root, run_id, llm)
        session.load_persisted_report()
        self._sessions[self._cache_key(run_id, llm)] = session
        return session

    def reset(self, run_id: str, llm: str) -> None:
        self._sessions.pop(self._cache_key(run_id, llm), None)


phase2_session_store = Phase2SessionStore()
