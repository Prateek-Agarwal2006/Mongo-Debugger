from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.hatchet import run_hatchet_job
from backend.app.jobs.hatchet_retry import HatchetRetryError, retry_hatchet_for_run
from backend.app.jobs.job_types import JOB_TYPE_HATCHET, JOB_TYPE_MONGO_FTDC
from backend.app.jobs.queue import FileJobQueue
from backend.app.jobs.store import JobState, JobStore
from backend.app.jobs.worker import PipelineWorker
from backend.app.simagix.hatchet_readiness import HatchetNotReadyError, assert_hatchet_ready_for_phase2

RUN_ID = "upload20260618T120000Z"


def test_queue_persists_job_type(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    queue = FileJobQueue(workspace)
    log_dir = workspace.mongodb_logs_dir(RUN_ID)
    log_dir.mkdir(parents=True)
    job = JobStore().create(
        RUN_ID,
        input_path=str(log_dir.relative_to(tmp_path)),
        job_type=JOB_TYPE_HATCHET,
        workspace_root=tmp_path,
    )

    queue.enqueue(job, log_dir)

    payload = json.loads(workspace.job_queue_pending_path(RUN_ID, job.job_id).read_text(encoding="utf-8"))
    assert payload["job_type"] == JOB_TYPE_HATCHET


def test_worker_dispatches_hatchet_job(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    log_dir = workspace.mongodb_logs_dir(RUN_ID)
    log_dir.mkdir(parents=True)
    (log_dir / "mongod.log").write_text('{"t":{"$date":"2020-01-01T00:00:00Z"},"s":"I","msg":"hi"}\n', encoding="utf-8")

    store = JobStore()
    job = store.create(
        RUN_ID,
        input_path=str(log_dir.relative_to(tmp_path)),
        job_type=JOB_TYPE_HATCHET,
        workspace_root=tmp_path,
    )
    FileJobQueue(workspace).enqueue(job, log_dir)

    worker = PipelineWorker(tmp_path)
    with patch("backend.app.jobs.worker.run_hatchet_job") as mock_run:
        assert worker.process_one() is True
        mock_run.assert_called_once()
        assert mock_run.call_args.args[1] == job.job_id


def test_hatchet_readiness_blocks_when_logs_without_summary(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    log_dir = workspace.mongodb_logs_dir(RUN_ID)
    log_dir.mkdir(parents=True)
    (log_dir / "mongod.log").write_text("log", encoding="utf-8")

    with patch("backend.app.simagix.hatchet_readiness.hatchet_blocks_phase2", return_value=True):
        with patch(
            "backend.app.simagix.hatchet_readiness.hatchet_block_message",
            return_value="waiting",
        ):
            try:
                assert_hatchet_ready_for_phase2(tmp_path, RUN_ID)
            except HatchetNotReadyError as exc:
                assert exc.detail == "waiting"
            else:
                raise AssertionError("expected HatchetNotReadyError")


def test_hatchet_readiness_allows_ftdc_only_run(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    assert not workspace.has_mongodb_log_inputs(RUN_ID)
    assert_hatchet_ready_for_phase2(tmp_path, RUN_ID)


def test_retry_hatchet_requires_logs(tmp_path: Path) -> None:
    with patch("backend.app.jobs.hatchet_retry.RunWorkspace") as mock_cls:
        mock_cls.return_value.has_mongodb_log_inputs.return_value = False
        try:
            retry_hatchet_for_run(tmp_path, RUN_ID)
        except HatchetRetryError as exc:
            assert exc.status_code == 404
        else:
            raise AssertionError("expected HatchetRetryError")


def test_retry_hatchet_clears_partial_db(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    log_dir = workspace.mongodb_logs_dir(RUN_ID)
    log_dir.mkdir(parents=True)
    (log_dir / "mongod.log").write_text("log", encoding="utf-8")
    hatchet_dir = workspace.hatchet_dir(RUN_ID)
    hatchet_dir.mkdir(parents=True)
    workspace.hatchet_db_path(RUN_ID).write_bytes(b"partial")
    (hatchet_dir / "hatchet.db-wal").write_bytes(b"wal")
    workspace.hatchet_summary_path(RUN_ID).write_text("{}", encoding="utf-8")

    with patch("backend.app.jobs.hatchet_retry.FileJobQueue") as mock_queue_cls:
        mock_queue_cls.return_value.has_active_job_for_run.return_value = False
        retry_hatchet_for_run(tmp_path, RUN_ID)

    assert not workspace.hatchet_db_path(RUN_ID).exists()
    assert not (hatchet_dir / "hatchet.db-wal").exists()
    assert not workspace.hatchet_summary_path(RUN_ID).exists()


def test_job_store_defaults_mongo_ftdc_job_type(tmp_path: Path) -> None:
    job = JobStore().create(RUN_ID, workspace_root=tmp_path)
    assert job.job_type == JOB_TYPE_MONGO_FTDC


def test_run_hatchet_job_invokes_bash(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    simagix = workspace.simagix_root
    scripts_dir = simagix / "scripts"
    scripts_dir.mkdir(parents=True)
    script = scripts_dir / "run-hatchet-job.sh"
    script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")

    log_dir = workspace.mongodb_logs_dir(RUN_ID)
    log_dir.mkdir(parents=True)
    (log_dir / "mongod.log").write_text("log", encoding="utf-8")
    hatchet_dir = workspace.hatchet_dir(RUN_ID)
    hatchet_dir.mkdir(parents=True)
    workspace.hatchet_db_path(RUN_ID).write_bytes(b"sqlite")

    store = JobStore()
    job = store.create(
        RUN_ID,
        input_path=str(log_dir.relative_to(tmp_path)),
        job_type=JOB_TYPE_HATCHET,
        workspace_root=tmp_path,
    )

    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with patch("backend.app.jobs.hatchet.subprocess.run", return_value=completed) as mock_run:
        with patch("backend.app.jobs.hatchet.write_hatchet_artifacts"):
            run_hatchet_job(tmp_path, job.job_id, RUN_ID, log_dir)

    command = mock_run.call_args.args[0]
    assert command[0] == "bash"
    assert command[1] == str(script)
