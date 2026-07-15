"""JSON run catalog for the Modern SPA (replaces Jinja-filled home/runs pages)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.app.core.run_workspace import get_run_workspace
from backend.app.jobs.catalog import (
    latest_job_for_run,
    list_run_catalog,
    phase1_progress_label,
    pipeline_display_status,
    upload_time_utc_from_run_id,
)
from backend.app.jobs.store import JobState
from backend.app.simagix.evidence.loader import EvidenceLoader

router = APIRouter(prefix="/simagix/catalog", tags=["simagix-catalog"])


@router.get("")
def get_catalog() -> dict[str, object]:
    workspace = get_run_workspace()
    entries = [entry.to_dict() for entry in list_run_catalog(workspace.root)]
    return {"runs": entries}


@router.get("/{run_id}")
def get_catalog_run(run_id: str) -> dict[str, object]:
    """Bootstrap payload for /runs/{id}: pipeline vs RCA gate for the SPA."""
    workspace = get_run_workspace()
    job = latest_job_for_run(workspace.root, run_id)
    has_evidence = EvidenceLoader(run_id).exists()
    upload_exists = workspace.upload_exists(run_id)

    if job is None and not has_evidence and not upload_exists:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # Gate RCA until Phase 1 succeeded (fixtures with no job + evidence still OK).
    if job is not None and job.state != JobState.SUCCEEDED:
        status = pipeline_display_status(workspace, job)
        return {
            "run_id": run_id,
            "view": "pipeline",
            "pipeline_status": status,
            "phase1_label": phase1_progress_label(status, job.message),
            "job_id": job.job_id,
            "job_message": job.message,
            "job_error": job.error,
            "upload_time_utc": upload_time_utc_from_run_id(run_id),
        }

    if not has_evidence:
        if job is not None or upload_exists:
            status = pipeline_display_status(workspace, job) if job else "queued"
            return {
                "run_id": run_id,
                "view": "pipeline",
                "pipeline_status": status,
                "phase1_label": phase1_progress_label(status, job.message if job else None),
                "job_id": job.job_id if job else None,
                "job_message": job.message if job else None,
                "job_error": job.error if job else None,
                "upload_time_utc": upload_time_utc_from_run_id(run_id),
            }
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    return {
        "run_id": run_id,
        "view": "run_workspace",
        "upload_time_utc": upload_time_utc_from_run_id(run_id),
        "selected_llm": "mock",
    }
