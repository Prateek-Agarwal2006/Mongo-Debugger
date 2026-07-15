from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.app.core.run_workspace import RunWorkspace
from backend.app.db.connection import db_conn
from backend.app.jobs.ftdc_retry import PipelineRetryError, retry_pipeline_for_run
from backend.app.jobs.queue import JobQueue
from backend.app.jobs.store import JobState, JobStore
from backend.app.jobs.worker import PipelineWorker
from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_queue_has_active_job_for_run(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    queue = JobQueue(workspace)
    input_dir = workspace.upload_diagnostic_dir("upload20260618T120000Z")
    input_dir.mkdir(parents=True)
    store = JobStore()
    job = store.create(
        "upload20260618T120000Z",
        input_path=str(input_dir.relative_to(tmp_path)),
        workspace_root=tmp_path,
    )
    queue.enqueue(job, input_dir)

    assert queue.has_active_job_for_run("upload20260618T120000Z") is True
    assert queue.has_active_job_for_run("other-run") is False


def test_queue_empty_after_pipeline_failure(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    input_dir = workspace.upload_diagnostic_dir("upload20260618T120000Z")
    input_dir.mkdir(parents=True)
    store = JobStore()
    job = store.create(
        "upload20260618T120000Z",
        input_path=str(input_dir.relative_to(tmp_path)),
        workspace_root=tmp_path,
    )
    JobQueue(workspace).enqueue(job, input_dir)

    worker = PipelineWorker(tmp_path)

    def fail_pipeline(*args: object, **kwargs: object) -> None:
        store.update(
            job.job_id,
            workspace_root=tmp_path,
            state=JobState.FAILED,
            message="Pipeline failed",
            error="docker down",
        )

    with patch("backend.app.jobs.worker.run_pipeline_job", side_effect=fail_pipeline):
        assert worker.process_one() is True

    assert not JobQueue(workspace).has_active_job_for_run("upload20260618T120000Z")
    loaded = store.get(job.job_id, workspace_root=tmp_path)
    assert loaded is not None
    assert loaded.state == JobState.FAILED


def test_retry_failed_run_creates_new_job_and_enqueues(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260618T120000Z"
    input_dir = workspace.upload_diagnostic_dir(run_id)
    input_dir.mkdir(parents=True)
    rel_input = str(input_dir.relative_to(tmp_path))
    store = JobStore()
    failed = store.create(run_id, input_path=rel_input, workspace_root=tmp_path)
    store.update(
        failed.job_id,
        workspace_root=tmp_path,
        state=JobState.FAILED,
        message="Pipeline failed",
        error="docker down",
    )

    retried = retry_pipeline_for_run(tmp_path, run_id)

    assert retried.job_id != failed.job_id
    assert retried.run_id == run_id
    assert retried.state == JobState.PENDING
    queue = JobQueue(workspace)
    assert queue.job_is_queued(run_id, retried.job_id)
    assert not queue.job_is_queued(run_id, failed.job_id)


def test_retry_rejects_when_run_already_active_in_queue(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260618T120000Z"
    input_dir = workspace.upload_diagnostic_dir(run_id)
    input_dir.mkdir(parents=True)
    rel_input = str(input_dir.relative_to(tmp_path))
    store = JobStore()
    failed = store.create(run_id, input_path=rel_input, workspace_root=tmp_path)
    store.update(failed.job_id, workspace_root=tmp_path, state=JobState.FAILED, error="x")
    active = store.create(run_id, input_path=rel_input, workspace_root=tmp_path)
    JobQueue(workspace).enqueue(active, input_dir)

    with pytest.raises(PipelineRetryError) as exc:
        retry_pipeline_for_run(tmp_path, run_id)

    assert exc.value.status_code == 409


def test_retry_rejects_when_export_exists(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260618T120000Z"
    input_dir = workspace.upload_diagnostic_dir(run_id)
    input_dir.mkdir(parents=True)

    # Seed evidence table so EvidenceLoader.exists() returns True
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (run_id, "manifest", json.dumps({"run_id": run_id})),
        )

    with pytest.raises(PipelineRetryError) as exc:
        retry_pipeline_for_run(tmp_path, run_id)

    assert exc.value.status_code == 409


def test_retry_api_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workspace = RunWorkspace(tmp_path)
    monkeypatch.setattr("backend.app.api.upload.get_run_workspace", lambda: workspace)
    run_id = "upload20260618T120000Z"
    input_dir = workspace.upload_diagnostic_dir(run_id)
    input_dir.mkdir(parents=True)
    rel_input = str(input_dir.relative_to(tmp_path))
    store = JobStore()
    job = store.create(run_id, input_path=rel_input, workspace_root=tmp_path)
    store.update(job.job_id, workspace_root=tmp_path, state=JobState.FAILED, error="docker down")

    client = TestClient(app)
    response = client.post(f"/simagix/uploads/runs/{run_id}/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run_id
    assert body["job_id"] != job.job_id
    assert body["status"] == "pending"
