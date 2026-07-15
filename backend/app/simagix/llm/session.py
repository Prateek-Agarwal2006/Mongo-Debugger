from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import RunWorkspace, repo_root
from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.rca_service import SimagixEvidenceService
from backend.app.simagix.llm.parse_output import load_persisted_rca_report
from backend.app.simagix.llm.state import (
    LLM_FOLDER_NAMES,
    llm_has_artifacts,
    load_state,
    save_state,
)
from backend.app.simagix.output_schema import InvestigationSummary, RCAReportDraft


@dataclass
class Phase2Session:
    run_id: str
    llm: str
    workspace_root: Path
    evidence: SimagixEvidenceService
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
        budget = RetrievalBudget(max_tool_calls=max_tool_calls, run_id=run_id, llm=llm)
        budget.sync_load()
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
        )

    # ------------------------------------------------------------------
    # Local scratch (per-pod cache; source of truth for attachments is PG)
    # ------------------------------------------------------------------

    @property
    def chatbot_scratch_dir(self) -> Path:
        session_dir = RunWorkspace(self.workspace_root).llm_session_dir(self.run_id, self.llm)
        return session_dir / "chatbot_scratch"

    def ensure_chatbot_scratch_dir(self) -> Path:
        self.chatbot_scratch_dir.mkdir(parents=True, exist_ok=True)
        return self.chatbot_scratch_dir

    # ------------------------------------------------------------------
    # Postgres-backed state
    # ------------------------------------------------------------------

    def configure_budget(self, max_tool_calls: int, *, reset: bool = False) -> None:
        if reset:
            self.evidence.budget.tool_calls_used = 0
            self.evidence.budget.tool_call_history = []
        self.evidence.budget.max_tool_calls = max_tool_calls
        self.evidence.budget.sync_save()

    def persist_investigation(self, investigation: InvestigationSummary) -> None:
        save_state(self.run_id, self.llm, "investigation", investigation.model_dump())

    def load_investigation(self) -> InvestigationSummary | None:
        payload = load_state(self.run_id, self.llm, "investigation")
        if payload is None:
            return None
        return InvestigationSummary.model_validate(payload)

    def mcp_server_env(self) -> dict[str, str]:
        # Inherit the full process environment so MCP subprocess gets PATH, HOME,
        # SSL_CERT_FILE, and any other system vars.  Session-specific vars override.
        env = {k: v for k, v in os.environ.items() if isinstance(v, str)}
        workspace = str(self.workspace_root)
        # Code lives at repo_root (/app in Kind). DATA_ROOT workspace is data only —
        # putting workspace first on PYTHONPATH + cwd=workspace made `python -m backend…`
        # fail with ModuleNotFoundError and Cursor reported simagix-evidence discovery down.
        app_root = str(repo_root())
        parts: list[str] = [app_root]
        if workspace != app_root:
            parts.append(workspace)
        existing = os.environ.get("PYTHONPATH", "")
        if existing:
            for chunk in existing.split(os.pathsep):
                if chunk and chunk not in parts:
                    parts.append(chunk)
        settings = get_settings()
        env.update({
            "SIMAGIX_RUN_ID": self.run_id,
            "SIMAGIX_WORKSPACE_ROOT": workspace,
            "SIMAGIX_LLM": self.llm,
            "SIMAGIX_MAX_TOOL_CALLS": str(self.evidence.budget.max_tool_calls),
            "PYTHONPATH": os.pathsep.join(parts),
        })
        if settings.database_url:
            env["DATABASE_URL"] = settings.database_url
        return env

    def refresh_budget(self) -> None:
        self.evidence.budget.sync_load()

    def budget_status(self) -> dict[str, Any]:
        self.refresh_budget()
        return self.evidence.get_budget_status()

    def load_metadata(self) -> dict[str, Any]:
        return load_state(self.run_id, self.llm, "metadata") or {}

    def persist_report(self, report: RCAReportDraft, *, agent_id: str | None = None, provider: str | None = None) -> None:
        from backend.app.simagix.tool_usage import tool_usage_summary

        self.latest_report = report
        save_state(self.run_id, self.llm, "report", report.model_dump())
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
        save_state(self.run_id, self.llm, "metadata", metadata)
        self.last_run_at = metadata["last_run_at"]

    def load_persisted_report(self) -> RCAReportDraft | None:
        if self.latest_report is not None:
            return self.latest_report
        payload = load_state(self.run_id, self.llm, "report")
        if payload is None:
            return None
        self.latest_report = load_persisted_rca_report(payload, self.run_id)
        meta = load_state(self.run_id, self.llm, "metadata")
        if meta:
            self.agent_id = meta.get("agent_id")
            self.last_run_at = meta.get("last_run_at")
        return self.latest_report


class Phase2SessionStore:
    """Session store keyed by (run_id, llm); all state in the phase2_state table."""

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
        if not llm_has_artifacts(run_id, llm):
            return None
        session = Phase2Session.create(workspace_root, run_id, llm)
        session.load_persisted_report()
        self._sessions[self._cache_key(run_id, llm)] = session
        return session

    def reset(self, run_id: str, llm: str) -> None:
        self._sessions.pop(self._cache_key(run_id, llm), None)


phase2_session_store = Phase2SessionStore()
