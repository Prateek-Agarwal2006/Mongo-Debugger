from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from backend.app.grafana.service import warm_grafana_for_run
from backend.app.jobs.store import JobState, JobStatus, job_store


class PipelineJobRunner:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = workspace_root.resolve()
        self.script = self.workspace_root / "simagix-workspace/scripts/run-mongo-ftdc-pipeline.sh"

    def start(self, job: JobStatus, input_path: Path) -> None:
        thread = threading.Thread(
            target=self._run,
            args=(job.job_id, job.run_id, input_path),
            daemon=True,
            name=f"pipeline-{job.run_id}",
        )
        thread.start()

    def _run(self, job_id: str, run_id: str, input_path: Path) -> None:
        job = job_store.update(
            job_id,
            state=JobState.RUNNING,
            message="Running mongo-ftdc pipeline",
        )
        if job is None:
            return

        rel_input = input_path.relative_to(self.workspace_root)
        env = {
            **dict(__import__("os").environ),
            "MONGO_FTDC_RUN_ID": run_id,
        }
        try:
            result = subprocess.run(
                [str(self.script), str(rel_input)],
                cwd=self.workspace_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=3600,
            )
            job = job_store.get(job_id)
            if job is None:
                return
            if result.returncode != 0:
                job_store.update(
                    job_id,
                    state=JobState.FAILED,
                    error=(result.stderr or result.stdout or "Pipeline failed")[-2000:],
                    message="Pipeline failed",
                )
            else:
                job_store.update(
                    job_id,
                    state=JobState.RUNNING,
                    message="Warming Grafana charts (may take ~2 minutes)…",
                    error=None,
                )
                warming_job = job_store.get(job_id)
                if warming_job is not None:
                    job_store.persist(self.workspace_root, warming_job)
                grafana_ready = warm_grafana_for_run(self.workspace_root, run_id)
                message = (
                    "Pipeline complete; Grafana ready"
                    if grafana_ready
                    else "Pipeline complete (Grafana warmup skipped — use Load on run page)"
                )
                job_store.update(
                    job_id,
                    state=JobState.SUCCEEDED,
                    message=message,
                    error=None,
                )
            updated = job_store.get(job_id)
            if updated is not None:
                job_store.persist(self.workspace_root, updated)
        except subprocess.TimeoutExpired:
            job_store.update(
                job_id,
                state=JobState.FAILED,
                error="Pipeline timed out after 3600s",
                message="Pipeline timed out",
            )
        except Exception as exc:
            job_store.update(
                job_id,
                state=JobState.FAILED,
                error=str(exc),
                message="Pipeline error",
            )
