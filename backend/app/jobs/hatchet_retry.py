from __future__ import annotations

from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.job_types import JOB_TYPE_HATCHET
from backend.app.jobs.queue import FileJobQueue
from backend.app.jobs.store import JobStatus, job_store


class HatchetRetryError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def retry_hatchet_for_run(workspace_root: Path, run_id: str) -> JobStatus:
    workspace = RunWorkspace(workspace_root)
    if not workspace.has_mongodb_log_inputs(run_id):
        raise HatchetRetryError(
            f"No MongoDB logs uploaded for run: {run_id}",
            status_code=404,
        )

    queue = FileJobQueue(workspace)
    if queue.has_active_job_for_run(run_id):
        raise HatchetRetryError(
            f"Hatchet already queued or running for run: {run_id}",
            status_code=409,
        )

    log_dir = workspace.mongodb_logs_dir(run_id)
    if not log_dir.is_dir():
        raise HatchetRetryError(f"Log directory missing for run: {run_id}", status_code=404)

    workspace.clear_hatchet_artifacts(run_id)

    input_path = str(log_dir.relative_to(workspace.root))
    job = job_store.create(
        run_id,
        input_path=input_path,
        job_type=JOB_TYPE_HATCHET,
        workspace_root=workspace_root,
    )
    queue.enqueue(job, log_dir)
    return job
