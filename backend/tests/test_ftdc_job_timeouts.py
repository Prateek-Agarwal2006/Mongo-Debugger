"""ftdc_job must not mislabel ingest ftdc-slice timeouts as llm-export 3600s timeouts."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.app.jobs.ftdc_job import run_pipeline_job
from backend.app.jobs.store import JobState, job_store


def test_ingest_timeout_is_not_labeled_pipeline_3600(tmp_path: Path) -> None:
    workspace = tmp_path
    (workspace / "simagix-workspace" / "scripts").mkdir(parents=True)
    script = workspace / "simagix-workspace" / "scripts" / "run-mongo-ftdc-pipeline.sh"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    input_dir = workspace / "simagix-workspace" / "uploads" / "to20260715T000000Z" / "inputs" / "diagnostic.data"
    input_dir.mkdir(parents=True)
    (input_dir / "metrics.x").write_bytes(b"x")

    job = job_store.create(
        "to20260715T000000Z",
        input_path=str(input_dir.relative_to(workspace)),
        workspace_root=workspace,
    )

    completed = subprocess.CompletedProcess(
        args=["script"], returncode=0, stdout="", stderr=""
    )
    with (
        patch("backend.app.jobs.ftdc_job._materialise_ftdc_from_pg"),
        patch("backend.app.jobs.ftdc_job.subprocess.run", return_value=completed),
        patch(
            "backend.app.jobs.ftdc_job.ingest_pipeline_run",
            side_effect=subprocess.TimeoutExpired(cmd="ftdc-slice", timeout=120),
        ),
    ):
        run_pipeline_job(workspace, job.job_id, "to20260715T000000Z", input_dir)

    final = job_store.get(job.job_id, workspace_root=workspace)
    assert final is not None
    assert final.state == JobState.FAILED
    assert final.message == "Ingest failed"
    assert "3600" not in (final.error or "")
    assert "timed out" in (final.error or "").lower()


def test_slice_index_timeout_scales_with_file_count() -> None:
    from backend.app.db import raw_files

    paths = [Path(f"/tmp/metrics.{i}") for i in range(20)]
    with patch.object(raw_files.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="ftdc-slice", timeout=1)) as run:
        with patch.object(raw_files.shutil, "which", return_value="ftdc-slice"):
            try:
                raw_files.build_raw_file_index(MagicMock(), "r", "ftdc", paths, "ftdc-slice")
            except TimeoutError as exc:
                assert "20 FTDC" in str(exc)
            else:
                raise AssertionError("expected TimeoutError")
        # 20 files → max(300, 90*20) = 1800
        assert run.call_args.kwargs["timeout"] == 1800
