from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.queue import FileJobQueue
from backend.app.jobs.store import JobState, JobStatus
from backend.app.simagix.llm.llm_paths import list_llm_sessions

Phase1DisplayStatus = Literal["queued", "processing", "finished", "failed", "stale"]
Phase2DisplayStatus = Literal["not_ready", "not_started", "in_progress", "completed"]

# Backward-compatible alias used in tests and older callers.
PipelineDisplayStatus = Phase1DisplayStatus


@dataclass(frozen=True)
class RunCatalogEntry:
    run_id: str
    phase1_status: Phase1DisplayStatus
    phase2_status: Phase2DisplayStatus
    job_id: str | None
    message: str
    error: str | None
    has_export: bool
    updated_at: float
    upload_time_utc: str | None
    phase1_attempt_count: int

    @property
    def pipeline_status(self) -> Phase1DisplayStatus:
        return self.phase1_status

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "phase1_status": self.phase1_status,
            "phase2_status": self.phase2_status,
            "pipeline_status": self.phase1_status,
            "job_id": self.job_id,
            "message": self.message,
            "error": self.error,
            "has_export": self.has_export,
            "updated_at": self.updated_at,
            "upload_time_utc": self.upload_time_utc,
            "phase1_attempt_count": self.phase1_attempt_count,
        }


def upload_time_utc_from_run_id(run_id: str) -> str | None:
    """Human UTC time from upload run_id (uploadYYYYMMDDTHHMMSSZ)."""
    if not run_id.startswith("upload") or len(run_id) < 22 or run_id[14] != "T":
        return None
    try:
        dt = datetime.strptime(run_id[6:21], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return None


def _read_all_jobs(workspace: RunWorkspace) -> list[JobStatus]:
    jobs: list[JobStatus] = []
    seen_job_ids: set[str] = set()
    for run_dir in workspace.iter_upload_run_dirs():
        jobs_dir = run_dir / "phase1" / "jobs"
        if not jobs_dir.is_dir():
            continue
        for path in jobs_dir.glob("*.json"):
            if path.stem in seen_job_ids:
                continue
            seen_job_ids.add(path.stem)
            jobs.append(JobStatus.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    legacy = workspace.legacy_jobs_root()
    if legacy.is_dir():
        for path in legacy.glob("*.json"):
            if path.stem in seen_job_ids:
                continue
            seen_job_ids.add(path.stem)
            jobs.append(JobStatus.from_dict(json.loads(path.read_text(encoding="utf-8"))))
    return jobs


def _read_jobs(workspace: RunWorkspace) -> dict[str, JobStatus]:
    latest_by_run: dict[str, JobStatus] = {}
    for job in _read_all_jobs(workspace):
        prev = latest_by_run.get(job.run_id)
        if prev is None or job.updated_at >= prev.updated_at:
            latest_by_run[job.run_id] = job
    return latest_by_run


def count_phase1_attempts(workspace: RunWorkspace, run_id: str) -> int:
    return sum(1 for job in _read_all_jobs(workspace) if job.run_id == run_id)


def list_phase1_attempts(workspace_root: Path, run_id: str) -> list[JobStatus]:
    workspace = RunWorkspace(workspace_root)
    attempts = [job for job in _read_all_jobs(workspace) if job.run_id == run_id]
    attempts.sort(key=lambda item: item.created_at)
    return attempts


def phase2_display_status(
    workspace_root: Path,
    run_id: str,
    *,
    has_export: bool,
) -> Phase2DisplayStatus:
    if not has_export:
        return "not_ready"
    sessions = list_llm_sessions(workspace_root, run_id)
    if not sessions:
        return "not_started"
    if any(session.get("has_report") for session in sessions):
        return "completed"
    if any(session.get("status") == "completed" for session in sessions):
        return "completed"
    if any(session.get("status") not in {None, "not_started"} for session in sessions):
        return "in_progress"
    return "not_started"


def pipeline_display_status(workspace: RunWorkspace, job: JobStatus) -> Phase1DisplayStatus:
    queue = FileJobQueue(workspace)
    if queue.job_is_processing(job.run_id, job.job_id):
        return "processing"
    if job.state == JobState.RUNNING:
        return "processing"
    if job.state == JobState.FAILED:
        return "failed"
    if job.state == JobState.SUCCEEDED:
        has_export = (workspace.resolve_exports_dir(job.run_id) / "manifest.json").exists()
        return "finished" if has_export else "processing"
    if queue.job_is_queued(job.run_id, job.job_id):
        return "queued"
    if job.state == JobState.PENDING:
        return "stale"
    return "stale"


def list_run_catalog(workspace_root: Path) -> list[RunCatalogEntry]:
    workspace = RunWorkspace(workspace_root)
    latest_jobs = _read_jobs(workspace)
    run_ids = set(latest_jobs) | set(workspace.list_run_ids())

    entries: list[RunCatalogEntry] = []
    for run_id in run_ids:
        has_export = (workspace.resolve_exports_dir(run_id) / "manifest.json").exists()
        job = latest_jobs.get(run_id)
        if job is None:
            entries.append(
                RunCatalogEntry(
                    run_id=run_id,
                    phase1_status="finished",
                    phase2_status=phase2_display_status(workspace_root, run_id, has_export=has_export),
                    job_id=None,
                    message="Export bundle ready",
                    error=None,
                    has_export=has_export,
                    updated_at=0.0,
                    upload_time_utc=upload_time_utc_from_run_id(run_id),
                    phase1_attempt_count=count_phase1_attempts(workspace, run_id),
                )
            )
            continue
        phase1 = pipeline_display_status(workspace, job)
        entries.append(
            RunCatalogEntry(
                run_id=run_id,
                phase1_status=phase1,
                phase2_status=phase2_display_status(workspace_root, run_id, has_export=has_export),
                job_id=job.job_id,
                message=job.message,
                error=job.error,
                has_export=has_export,
                updated_at=job.updated_at,
                upload_time_utc=upload_time_utc_from_run_id(run_id),
                phase1_attempt_count=count_phase1_attempts(workspace, run_id),
            )
        )

    return sorted(entries, key=lambda item: item.updated_at, reverse=True)


def latest_job_for_run(workspace_root: Path, run_id: str) -> JobStatus | None:
    return _read_jobs(RunWorkspace(workspace_root)).get(run_id)
