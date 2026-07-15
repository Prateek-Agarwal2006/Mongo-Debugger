from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.ingest import ingest_pipeline_run
from backend.app.jobs.store import JobState, job_store


def _materialise_ftdc_from_pg(workspace_root: Path, run_id: str) -> None:
    """Reassemble FTDC files from raw_files table onto the worker's local disk.

    No-op when files already exist (local dev / shared volume) or when
    DATABASE_URL is not configured.  In K8s, the API pod stores raw bytes at
    upload time; the worker pod has a separate emptyDir and must pull them back
    before running the pipeline.
    """
    from backend.app.core.config import get_settings
    if not get_settings().database_url:
        return

    workspace = RunWorkspace(workspace_root)
    diag_dir = workspace.resolve_upload_diagnostic_dir(run_id)
    if diag_dir.is_dir() and any(diag_dir.glob("metrics.*")):
        return  # files already on this pod's disk

    from backend.app.db.connection import db_conn
    from backend.app.db.raw_files import list_raw_filenames, reassemble_raw_file

    with db_conn() as conn:
        filenames = list_raw_filenames(conn, run_id, "ftdc")
        if not filenames:
            return
        target = workspace.upload_diagnostic_dir(run_id)
        target.mkdir(parents=True, exist_ok=True)
        for fname in filenames:
            reassemble_raw_file(conn, run_id, "ftdc", fname, target / fname)


def run_pipeline_job(workspace_root: Path, job_id: str, run_id: str, input_path: Path) -> None:
    workspace = RunWorkspace(workspace_root)
    script = workspace.pipeline_script()

    job = job_store.update(
        job_id,
        workspace_root=workspace_root,
        state=JobState.RUNNING,
        message="Running mongo-ftdc pipeline",
    )
    if job is None:
        return

    _materialise_ftdc_from_pg(workspace_root, run_id)

    rel_input = input_path.relative_to(workspace.root)
    env = {**dict(os.environ), "MONGO_FTDC_RUN_ID": run_id}
    try:
        result = subprocess.run(
            [str(script), str(rel_input)],
            cwd=workspace.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        # Only llm-export / pipeline script — do not catch ingest ftdc-slice timeouts here
        # (those used to be mislabeled "Pipeline timed out after 3600s" after ~2 minutes).
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error="Pipeline timed out after 3600s",
            message="Pipeline timed out",
        )
        return
    except Exception as exc:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error=str(exc),
            message="Pipeline error",
        )
        return

    if job_store.get(job_id, workspace_root=workspace_root) is None:
        return
    if result.returncode != 0:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error=result.stderr or result.stdout or "Pipeline failed",
            message="Pipeline failed",
        )
        return

    try:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.RUNNING,
            message="Ingesting decoded data into Postgres…",
            error=None,
        )
        ingest_pipeline_run(workspace_root, run_id)
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.SUCCEEDED,
            message="Pipeline complete; evidence ready",
            error=None,
        )
    except Exception as exc:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error=str(exc),
            message="Ingest failed",
        )
