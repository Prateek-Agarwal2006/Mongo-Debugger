from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.ingest import ingest_hatchet_run
from backend.app.jobs.store import JobState, job_store


def _materialise_logs_from_pg(workspace_root: Path, run_id: str) -> None:
    """Reassemble MongoDB log files from raw_files table onto the worker's local disk.

    In K8s, the API pod saves log files to its emptyDir at upload time and also
    stores them in PG.  The worker pod has a separate emptyDir; this function
    pulls the bytes back before Hatchet runs.  No-op when files already exist
    or DATABASE_URL is not configured.
    """
    from backend.app.core.config import get_settings
    if not get_settings().database_url:
        return

    workspace = RunWorkspace(workspace_root)
    log_dir = workspace.mongodb_logs_dir(run_id)
    if log_dir.is_dir() and any(log_dir.iterdir()):
        return  # already on disk

    from backend.app.db.connection import db_conn
    from backend.app.db.raw_files import list_raw_filenames, reassemble_raw_file

    with db_conn() as conn:
        filenames = list_raw_filenames(conn, run_id, "logs")
        if not filenames:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        for fname in filenames:
            reassemble_raw_file(conn, run_id, "logs", fname, log_dir / fname)


def _source_file_entries(workspace: RunWorkspace, run_id: str) -> list[dict[str, object]]:
    return [
        {"marker": i, "name": p.name, "path": str(p.relative_to(workspace.root))}
        for i, p in enumerate(workspace.list_mongodb_log_files(run_id), start=1)
    ]


def run_hatchet_job(workspace_root: Path, job_id: str, run_id: str, log_dir: Path) -> None:
    workspace = RunWorkspace(workspace_root)
    script = workspace.hatchet_script()
    _materialise_logs_from_pg(workspace_root, run_id)
    log_files = workspace.list_mongodb_log_files(run_id)
    if not log_files:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error="No MongoDB log files found under inputs/mongodb-logs/",
            message="Hatchet failed",
        )
        return

    job = job_store.update(
        job_id,
        workspace_root=workspace_root,
        state=JobState.RUNNING,
        message="Running Hatchet log analysis",
    )
    if job is None:
        return

    rel_log_dir = log_dir.relative_to(workspace.root)
    env = {**dict(os.environ), "HATCHET_RUN_ID": run_id}
    try:
        result = subprocess.run(
            ["bash", str(script), run_id, str(rel_log_dir)],
            cwd=workspace.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=7200,
        )
        if job_store.get(job_id, workspace_root=workspace_root) is None:
            return
        if result.returncode != 0:
            job_store.update(
                job_id,
                workspace_root=workspace_root,
                state=JobState.FAILED,
                error=result.stderr or result.stdout or "Hatchet failed",
                message="Hatchet failed",
            )
            return

        db_path = workspace.hatchet_db_path(run_id)
        if not db_path.is_file():
            job_store.update(
                job_id,
                workspace_root=workspace_root,
                state=JobState.FAILED,
                error=f"Hatchet database missing: {db_path}",
                message="Hatchet export failed",
            )
            return

        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.RUNNING,
            message="Ingesting Hatchet evidence into Postgres…",
            error=None,
        )
        ingest_hatchet_run(workspace_root, run_id)
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.SUCCEEDED,
            message="Hatchet complete; evidence ready",
            error=None,
        )
    except subprocess.TimeoutExpired:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error="Hatchet timed out after 7200s",
            message="Hatchet timed out",
        )
    except Exception as exc:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error=str(exc),
            message="Hatchet error",
        )
