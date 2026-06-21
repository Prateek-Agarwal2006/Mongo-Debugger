from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.queue import FileJobQueue, QueuedPipelineJob
from backend.app.jobs.store import JobState, JobStatus, JobStore
from backend.app.jobs.worker import PipelineWorker

RUN_ID = "upload20260618T120000Z"


def test_job_queue_paths(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    job_id = "abc-123"

    assert workspace.job_record_path(RUN_ID, job_id) == (
        tmp_path / f"simagix-workspace/uploads/{RUN_ID}/phase1/jobs/abc-123.json"
    )
    assert workspace.job_queue_pending_path(RUN_ID, job_id) == (
        tmp_path / f"simagix-workspace/uploads/{RUN_ID}/phase1/queue/pending/abc-123.json"
    )
    assert workspace.job_queue_processing_path(RUN_ID, job_id) == (
        tmp_path / f"simagix-workspace/uploads/{RUN_ID}/phase1/queue/processing/abc-123.json"
    )


def test_file_job_queue_enqueue_and_claim(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    queue = FileJobQueue(workspace)
    input_dir = workspace.upload_diagnostic_dir(RUN_ID)
    input_dir.mkdir(parents=True)
    job = JobStatus(job_id="job-1", run_id=RUN_ID, state=JobState.PENDING)

    queue.enqueue(job, input_dir)

    pending = workspace.job_queue_pending_path(RUN_ID, job.job_id)
    assert pending.exists()
    payload = json.loads(pending.read_text(encoding="utf-8"))
    assert payload["job_id"] == "job-1"
    assert payload["run_id"] == RUN_ID

    claimed = queue.claim_next()
    assert claimed == QueuedPipelineJob(
        job_id="job-1",
        run_id=RUN_ID,
        input_path=str(input_dir.relative_to(workspace.root)),
    )
    assert not pending.exists()
    assert workspace.job_queue_processing_path(RUN_ID, job.job_id).exists()


def test_file_job_queue_requeue_stale_processing(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    queue = FileJobQueue(workspace)
    processing = workspace.job_queue_processing_path(RUN_ID, "stale-job")
    processing.parent.mkdir(parents=True, exist_ok=True)
    processing.write_text(
        json.dumps(
            {
                "job_id": "stale-job",
                "run_id": RUN_ID,
                "input_path": f"simagix-workspace/uploads/{RUN_ID}/raw/diagnostic.data",
            }
        ),
        encoding="utf-8",
    )

    count = queue.requeue_stale_processing()

    assert count == 1
    assert workspace.job_queue_pending_path(RUN_ID, "stale-job").exists()
    assert not processing.exists()


def test_job_store_persists_and_loads_by_job_id(tmp_path: Path) -> None:
    store = JobStore()
    job = store.create(
        RUN_ID,
        input_path=f"simagix-workspace/uploads/{RUN_ID}/raw/diagnostic.data",
        workspace_root=tmp_path,
    )

    other = JobStore()
    loaded = other.load(tmp_path, job.job_id)
    assert loaded is not None
    assert loaded.job_id == job.job_id
    assert loaded.run_id == job.run_id
    assert loaded.state == JobState.PENDING
    assert RunWorkspace(tmp_path).job_record_path(RUN_ID, job.job_id).exists()


def test_job_store_get_falls_back_to_disk(tmp_path: Path) -> None:
    store = JobStore()
    job = store.create(RUN_ID, workspace_root=tmp_path)

    fresh = JobStore()
    loaded = fresh.get(job.job_id, workspace_root=tmp_path)
    assert loaded is not None
    assert loaded.job_id == job.job_id


def test_job_store_get_prefers_newer_disk_status(tmp_path: Path) -> None:
    api_store = JobStore()
    job = api_store.create(
        RUN_ID,
        input_path=f"simagix-workspace/uploads/{RUN_ID}/raw/diagnostic.data",
        workspace_root=tmp_path,
    )
    assert api_store.get(job.job_id, workspace_root=tmp_path) is not None
    assert api_store.get(job.job_id, workspace_root=tmp_path).state == JobState.PENDING

    worker_store = JobStore()
    worker_store.update(
        job.job_id,
        workspace_root=tmp_path,
        state=JobState.FAILED,
        message="Pipeline failed",
        error="docker down",
    )

    polled = api_store.get(job.job_id, workspace_root=tmp_path)
    assert polled is not None
    assert polled.state == JobState.FAILED
    assert polled.error == "docker down"


def test_pipeline_worker_recovers_stale_on_startup(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    processing = workspace.job_queue_processing_path(RUN_ID, "stale-job")
    processing.parent.mkdir(parents=True, exist_ok=True)
    processing.write_text("{}", encoding="utf-8")

    worker = PipelineWorker(tmp_path)
    assert worker.recover_stale_jobs() == 1
    assert workspace.job_queue_pending_path(RUN_ID, "stale-job").exists()


def test_pipeline_worker_processes_claimed_job(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    input_dir = workspace.upload_diagnostic_dir(RUN_ID)
    input_dir.mkdir(parents=True)
    (input_dir / "metrics.fake").write_text("x", encoding="utf-8")

    store = JobStore()
    job = store.create(
        RUN_ID,
        input_path=str(input_dir.relative_to(tmp_path)),
        workspace_root=tmp_path,
    )
    FileJobQueue(workspace).enqueue(job, input_dir)

    worker = PipelineWorker(tmp_path)
    with patch("backend.app.jobs.worker.run_pipeline_job") as mock_run:
        assert worker.process_one() is True
        mock_run.assert_called_once()
        assert mock_run.call_args.args[1] == job.job_id

    assert not workspace.job_queue_processing_path(RUN_ID, job.job_id).exists()


def test_pipeline_worker_returns_false_when_queue_empty(tmp_path: Path) -> None:
    worker = PipelineWorker(tmp_path)
    assert worker.process_one() is False
