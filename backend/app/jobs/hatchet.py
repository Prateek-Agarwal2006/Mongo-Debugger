from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.store import JobState, job_store
from backend.app.simagix.hatchet_export import write_hatchet_artifacts


def _source_file_entries(workspace: RunWorkspace, run_id: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for marker, path in enumerate(workspace.list_mongodb_log_files(run_id), start=1):
        entries.append(
            {
                "marker": marker,
                "name": path.name,
                "path": str(path.relative_to(workspace.root)),
            }
        )
    return entries


def run_hatchet_job(workspace_root: Path, job_id: str, run_id: str, log_dir: Path) -> None:
    workspace = RunWorkspace(workspace_root)
    script = workspace.hatchet_script()
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
    env = {
        **dict(os.environ),
        "HATCHET_RUN_ID": run_id,
    }
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
                error=(result.stderr or result.stdout or "Hatchet failed")[-2000:],
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

        source_files = _source_file_entries(workspace, run_id)
        write_hatchet_artifacts(
            db_path,
            workspace.hatchet_dir(run_id),
            source_files=source_files,
            run_id=run_id,
        )
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.SUCCEEDED,
            message="Hatchet complete; summary.json ready",
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
