from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.job_types import DEFAULT_JOB_TYPE, normalize_job_type
from backend.app.jobs.store import JobStatus


@dataclass(frozen=True)
class QueuedPipelineJob:
    job_id: str
    run_id: str
    input_path: str
    job_type: str = DEFAULT_JOB_TYPE


class FileJobQueue:
    """Per-upload Phase 1 queue under uploads/{run_id}/phase1/queue/ (Option A layout)."""

    def __init__(self, workspace: RunWorkspace) -> None:
        self.workspace = workspace

    def enqueue(self, job: JobStatus, input_dir: Path) -> None:
        pending_dir = self.workspace.job_queue_pending_dir(job.run_id)
        pending_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": job.job_id,
            "run_id": job.run_id,
            "input_path": str(input_dir.relative_to(self.workspace.root)),
            "job_type": normalize_job_type(job.job_type),
        }
        self.workspace.job_queue_pending_path(job.run_id, job.job_id).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def requeue_stale_processing(self) -> int:
        """Move processing/ back to pending/ — crash recovery when a worker died mid-run."""
        count = 0
        for path in self.workspace.iter_phase1_queue_processing_paths():
            pending_dir = path.parent.parent / "pending"
            pending_dir.mkdir(parents=True, exist_ok=True)
            dest = pending_dir / path.name
            try:
                path.replace(dest)
            except OSError:
                continue
            count += 1
        return count

    def claim_next(self) -> QueuedPipelineJob | None:
        pending_paths = self.workspace.iter_phase1_queue_pending_paths()
        if not pending_paths:
            return None
        for path in sorted(pending_paths, key=lambda item: item.stat().st_mtime):
            job_id = path.stem
            processing_dir = path.parent.parent / "processing"
            processing = processing_dir / path.name
            processing_dir.mkdir(parents=True, exist_ok=True)
            try:
                path.replace(processing)
            except OSError:
                continue
            payload = json.loads(processing.read_text(encoding="utf-8"))
            return QueuedPipelineJob(
                job_id=payload["job_id"],
                run_id=payload["run_id"],
                input_path=payload["input_path"],
                job_type=normalize_job_type(payload.get("job_type")),
            )
        return None

    def complete(self, run_id: str, job_id: str) -> None:
        processing = self.workspace.job_queue_processing_path(run_id, job_id)
        if processing.exists():
            processing.unlink() ## unlink is used to delete the file....
            return
        legacy = self.workspace.legacy_job_queue_processing_path(job_id)
        if legacy.exists():
            legacy.unlink()

    def has_active_job_for_run(self, run_id: str) -> bool:
        """True if this upload's pending/ or processing/ has a queue entry."""
        for directory in (
            self.workspace.job_queue_pending_dir(run_id),
            self.workspace.job_queue_processing_dir(run_id),
        ):
            if directory.exists() and any(directory.glob("*.json")):
                return True
        for directory in (
            self.workspace.legacy_job_queue_pending_dir(),
            self.workspace.legacy_job_queue_processing_dir(),
        ):
            if not directory.exists():
                continue
            for path in directory.glob("*.json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                if payload.get("run_id") == run_id:
                    return True
        return False

    def job_is_queued(self, run_id: str, job_id: str) -> bool:
        if self.workspace.job_queue_pending_path(run_id, job_id).exists():
            return True
        if self.workspace.legacy_job_queue_pending_path(job_id).exists():
            return True
        return False

    def job_is_processing(self, run_id: str, job_id: str) -> bool:
        if self.workspace.job_queue_processing_path(run_id, job_id).exists():
            return True
        if self.workspace.legacy_job_queue_processing_path(job_id).exists():
            return True
        return False
