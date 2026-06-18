from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.store import JobStatus


@dataclass(frozen=True)
class QueuedPipelineJob:
    job_id: str
    run_id: str
    input_path: str


class FileJobQueue:
    """Durable FIFO-ish queue on a shared filesystem (local DATA_ROOT or K8s PVC)."""

    def __init__(self, workspace: RunWorkspace) -> None:
        self.workspace = workspace

    def enqueue(self, job: JobStatus, input_dir: Path) -> None:
        pending_dir = self.workspace.job_queue_pending_dir()
        pending_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "job_id": job.job_id,
            "run_id": job.run_id,
            "input_path": str(input_dir.relative_to(self.workspace.root)),
        }
        self.workspace.job_queue_pending_path(job.job_id).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    def requeue_stale_processing(self) -> int:
        """Move processing/ back to pending/ — crash recovery when a worker died mid-run."""
        processing_dir = self.workspace.job_queue_processing_dir()
        if not processing_dir.exists():
            return 0
        count = 0
        for path in sorted(processing_dir.glob("*.json")):
            dest = self.workspace.job_queue_pending_path(path.stem)
            dest.parent.mkdir(parents=True, exist_ok=True)
            path.replace(dest)# moves the file from processing to pending....so that the worker can claim it again....this is atmoic rename lock mechanism....so that only one worker can claim the job at a time....if multiple workers try to claim the same job at the same time then the first worker to claim the job will win and the other worker will retry later....may have to change this if we want to allow multiple workers to claim the same job at the same time....but for now this is good enough....
            count += 1
        return count

    def claim_next(self) -> QueuedPipelineJob | None:
        pending_dir = self.workspace.job_queue_pending_dir()
        if not pending_dir.exists():
            return None
        for path in sorted(pending_dir.glob("*.json"), key=lambda item: item.stat().st_mtime):
            job_id = path.stem
            processing = self.workspace.job_queue_processing_path(job_id)
            processing.parent.mkdir(parents=True, exist_ok=True)
            try:
                path.replace(processing)
            except OSError:
                continue
            payload = json.loads(processing.read_text(encoding="utf-8"))
            return QueuedPipelineJob(
                job_id=payload["job_id"],
                run_id=payload["run_id"],
                input_path=payload["input_path"],
            )
        return None

    def complete(self, job_id: str) -> None:
        processing = self.workspace.job_queue_processing_path(job_id)
        if processing.exists():
            processing.unlink()
