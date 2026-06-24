from __future__ import annotations

from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import latest_job_for_run
from backend.app.jobs.job_types import JOB_TYPE_MONGO_FTDC
from backend.app.jobs.queue import FileJobQueue
from backend.app.jobs.store import JobStatus, job_store


class PipelineRetryError(Exception):
    def __init__(self, detail: str, *, status_code: int = 400) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def retry_pipeline_for_run(workspace_root: Path, run_id: str) -> JobStatus:
    workspace = RunWorkspace(workspace_root)
    if (workspace.resolve_exports_dir(run_id) / "manifest.json").exists():
        raise PipelineRetryError(
            f"Run already has an export bundle: {run_id}",
            status_code=409,
        )

    queue = FileJobQueue(workspace)
    if queue.has_active_job_for_run(run_id):
        raise PipelineRetryError(
            f"Pipeline already queued or running for run: {run_id}",
            status_code=409,
        )

    latest = latest_job_for_run(workspace_root, run_id)
    input_path = latest.input_path if latest and latest.input_path else None
    if input_path is None:
        input_dir = workspace.resolve_upload_diagnostic_dir(run_id)
        if not input_dir.is_dir():
            raise PipelineRetryError(f"Upload not found for run: {run_id}", status_code=404)
        input_path = str(input_dir.relative_to(workspace.root))
    else:
        input_dir = workspace.root / input_path
        if not input_dir.is_dir():
            raise PipelineRetryError(
                f"Upload path missing for run: {run_id} ({input_path})",
                status_code=404,
            )

    job = job_store.create(
        run_id,
        input_path=input_path,
        job_type=JOB_TYPE_MONGO_FTDC,
        workspace_root=workspace_root,
    )
    queue.enqueue(job, input_dir)
    return job
