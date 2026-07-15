from __future__ import annotations

from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import (
    list_run_catalog,
    phase1_progress_label,
    phase2_display_status,
    pipeline_display_status,
)
from backend.app.jobs.queue import JobQueue
from backend.app.jobs.store import JobState, JobStatus, JobStore


def test_list_run_catalog_shows_failed_upload_without_export(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260618T120000Z"
    store = JobStore()
    job = store.create(run_id, workspace_root=tmp_path)
    store.update(
        job.job_id,
        workspace_root=tmp_path,
        state=JobState.FAILED,
        message="Pipeline failed",
        error="docker down",
    )
    workspace.upload_diagnostic_dir(run_id).mkdir(parents=True, exist_ok=True)

    entries = [e for e in list_run_catalog(tmp_path) if e.run_id == run_id]
    assert len(entries) == 1
    assert entries[0].phase1_status == "failed"
    assert entries[0].has_export is False


def test_pipeline_display_status_queued_when_job_enqueued(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "upload20260618T120000Z"
    job = JobStatus(job_id="j1", run_id=run_id, state=JobState.PENDING)
    input_dir = workspace.upload_diagnostic_dir(run_id)
    input_dir.mkdir(parents=True)
    JobQueue(workspace).enqueue(job, input_dir)
    assert pipeline_display_status(workspace, job) == "queued"


def test_pipeline_display_status_stale_when_pending_without_queue(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    job = JobStatus(job_id="j1", run_id="upload20260618T120000Z", state=JobState.PENDING)
    assert pipeline_display_status(workspace, job) == "stale"


def test_phase1_progress_label_distinguishes_ingest() -> None:
    assert phase1_progress_label("processing", "Running mongo-ftdc pipeline") == "Decoding"
    assert (
        phase1_progress_label("processing", "Ingesting decoded data into Postgres…")
        == "Loading metrics"
    )
    assert phase1_progress_label("finished", "Pipeline complete") == "Ready"
    assert phase1_progress_label("failed", "Ingest failed") == "Failed"


def test_phase2_display_status_not_ready_without_export(tmp_path: Path) -> None:
    run_id = "upload20260618T120000Z"
    assert phase2_display_status(tmp_path, run_id, has_export=False) == "not_ready"


def test_phase2_display_status_completed_with_report(tmp_path: Path) -> None:
    from backend.app.simagix.llm.state import save_state

    run_id = "upload20260618T990000Z"
    save_state(run_id, "mock", "report", {"run_id": run_id})
    assert phase2_display_status(tmp_path, run_id, has_export=True) == "completed"


def test_list_run_catalog_includes_finished_export(tmp_path: Path) -> None:
    import json

    from backend.app.db.connection import db_conn

    run_id = "phase1test20260609T133314Z"
    with db_conn() as conn:
        conn.execute(
            "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (run_id, "manifest", json.dumps({"run_id": run_id})),
        )

    entries = [e for e in list_run_catalog(tmp_path) if e.run_id == run_id]
    assert len(entries) == 1
    assert entries[0].phase1_status == "finished"
    assert entries[0].phase2_status == "not_started"
    assert entries[0].has_export is True
