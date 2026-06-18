from __future__ import annotations

import os
import subprocess
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.grafana.service import warm_grafana_for_run
from backend.app.jobs.store import JobState, job_store


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

    rel_input = input_path.relative_to(workspace.root)
    env = {
        **dict(os.environ),
        "MONGO_FTDC_RUN_ID": run_id,
    }
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
        if job_store.get(job_id, workspace_root=workspace_root) is None:
            return
        if result.returncode != 0:
            job_store.update(
                job_id,
                workspace_root=workspace_root,
                state=JobState.FAILED,
                error=(result.stderr or result.stdout or "Pipeline failed")[-2000:],
                message="Pipeline failed",
            )
            return

        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.RUNNING,
            message="Warming Grafana charts (may take ~2 minutes)…",
            error=None,
        )
        grafana_ready = warm_grafana_for_run(workspace.root, run_id)
        message = (
            "Pipeline complete; Grafana ready"
            if grafana_ready
            else "Pipeline complete (Grafana warmup skipped — use Load on run page)"
        )
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.SUCCEEDED,
            message=message,
            error=None,
        )
    except subprocess.TimeoutExpired:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error="Pipeline timed out after 3600s",
            message="Pipeline timed out",
        )
    except Exception as exc:
        job_store.update(
            job_id,
            workspace_root=workspace_root,
            state=JobState.FAILED,
            error=str(exc),
            message="Pipeline error",
        )
