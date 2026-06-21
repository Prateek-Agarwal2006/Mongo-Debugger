from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.catalog import (
    list_run_catalog,
    phase2_display_status,
    pipeline_display_status,
    upload_time_utc_from_run_id,
)
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

    entries = list_run_catalog(tmp_path)
    assert len(entries) == 1
    assert entries[0].run_id == run_id
    assert entries[0].phase1_status == "failed"
    assert entries[0].has_export is False


def test_pipeline_display_status_queued_when_pending_file_exists(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    job = JobStatus(job_id="j1", run_id="upload20260618T120000Z", state=JobState.PENDING)
    pending = workspace.job_queue_pending_path("upload20260618T120000Z", "j1")
    pending.parent.mkdir(parents=True)
    pending.write_text("{}", encoding="utf-8")
    assert pipeline_display_status(workspace, job) == "queued"


def test_pipeline_display_status_stale_when_pending_without_queue(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    job = JobStatus(job_id="j1", run_id="upload20260618T120000Z", state=JobState.PENDING)
    assert pipeline_display_status(workspace, job) == "stale"


def test_upload_time_utc_from_run_id() -> None:
    assert upload_time_utc_from_run_id("upload20260618T120254Z") == "2026-06-18 12:02 UTC"
    assert upload_time_utc_from_run_id("phase1test20260609T133314Z") is None


def test_phase2_display_status_not_ready_without_export(tmp_path: Path) -> None:
    run_id = "upload20260618T120000Z"
    assert phase2_display_status(tmp_path, run_id, has_export=False) == "not_ready"


def test_phase2_display_status_completed_with_report(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "phase1test20260609T133314Z"
    llm_dir = workspace.llm_session_dir(run_id, "mock")
    llm_dir.mkdir(parents=True)
    (llm_dir / "latest_report.json").write_text("{}", encoding="utf-8")
    assert phase2_display_status(tmp_path, run_id, has_export=True) == "completed"


def test_list_run_catalog_includes_finished_export(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    run_id = "phase1test20260609T133314Z"
    bundle = workspace.exports_dir(run_id)
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text("{}", encoding="utf-8")

    entries = list_run_catalog(tmp_path)
    assert len(entries) == 1
    assert entries[0].phase1_status == "finished"
    assert entries[0].phase2_status == "not_started"
    assert entries[0].has_export is True
