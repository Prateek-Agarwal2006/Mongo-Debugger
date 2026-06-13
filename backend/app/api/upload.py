from __future__ import annotations

import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.jobs.pipeline import PipelineJobRunner
from backend.app.jobs.store import job_store

router = APIRouter(prefix="/simagix/uploads", tags=["simagix-upload"])


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _new_run_id() -> str:
    return f"upload{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _unpack_archive(archive_path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = archive_path.name.lower()
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(dest_dir)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(dest_dir)
    else:
        raise HTTPException(status_code=400, detail="Unsupported archive format. Use .zip or .tar.gz")

    metrics = list(dest_dir.rglob("metrics.*"))
    if not metrics:
        raise HTTPException(status_code=400, detail="Archive must contain metrics.* FTDC files")

    metrics_parent = metrics[0].parent
    if metrics_parent != dest_dir:
        for item in metrics_parent.iterdir():
            target = dest_dir / item.name
            if item.is_file() and not target.exists():
                shutil.move(str(item), str(target))


@router.post("")
async def upload_diagnostic_data(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    workspace = _workspace_root()
    run_id = _new_run_id()
    input_dir = workspace / "simagix-workspace/data/uploads" / run_id / "diagnostic.data"
    input_dir.mkdir(parents=True, exist_ok=True)

    archive_path = input_dir.parent / file.filename
    content = await file.read()
    archive_path.write_bytes(content)

    filename_lower = file.filename.lower()
    if filename_lower.startswith("metrics."):
        shutil.move(str(archive_path), str(input_dir / file.filename))
    else:
        _unpack_archive(archive_path, input_dir)
        if archive_path.exists():
            archive_path.unlink()

    rel_input = input_dir.relative_to(workspace)
    job = job_store.create(run_id, input_path=str(rel_input))
    runner = PipelineJobRunner(workspace)
    runner.start(job, input_dir)

    return {
        "job_id": job.job_id,
        "run_id": run_id,
        "input_path": str(rel_input),
        "status": job.state.value,
    }


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, object]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()
