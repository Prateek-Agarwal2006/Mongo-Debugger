from __future__ import annotations

import asyncio
import io
import shutil
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.core.run_workspace import RunWorkspace, get_run_workspace
from backend.app.simagix.evidence.loader import EvidenceLoader
from backend.app.jobs.hatchet_retry import HatchetRetryError, retry_hatchet_for_run
from backend.app.jobs.job_types import JOB_TYPE_HATCHET, JOB_TYPE_MONGO_FTDC
from backend.app.jobs.queue import JobQueue
from backend.app.jobs.ftdc_retry import PipelineRetryError, retry_pipeline_for_run
from backend.app.jobs.store import job_store
from backend.app.core.config import get_settings

router = APIRouter(prefix="/simagix/uploads", tags=["simagix-upload"])

_LOG_SUFFIXES = (".log", ".log.gz", ".txt")
_LOG_ARCHIVE_SUFFIXES = (".zip", ".tar.gz", ".tgz", ".tar")
_READ_CHUNK_BYTES = 1024 * 1024


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


def _store_ftdc_raw_files(run_id: str, diagnostic_dir: Path) -> None:
    """Store raw FTDC bytes in raw_files table (best-effort; skipped if no DATABASE_URL)."""
    if not get_settings().database_url:
        return
    ftdc_files = sorted(
        p for p in diagnostic_dir.iterdir()
        if p.is_file() and p.name.startswith("metrics.")
    )
    if not ftdc_files:
        return
    from backend.app.db.connection import db_conn
    from backend.app.db.raw_files import store_raw_file
    with db_conn() as conn:
        for path in ftdc_files:
            store_raw_file(conn, run_id, "ftdc", path.name, path)


def _remove_upload_tree(upload_dir: Path) -> None:
    if upload_dir.is_dir():
        shutil.rmtree(upload_dir, ignore_errors=True)


def _require_run_exists(run_id: str) -> None:
    workspace = get_run_workspace()
    if workspace.upload_exists(run_id):
        return
    if EvidenceLoader(run_id).exists():
        return
    # K8s: API pod emptyDir may be wiped after restart — check PG chunk store.
    if get_settings().database_url:
        from backend.app.db.connection import db_conn
        from backend.app.db.raw_files import list_raw_filenames
        with db_conn() as conn:
            if list_raw_filenames(conn, run_id, "ftdc"):
                return
    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


def _is_log_filename(name: str) -> bool:
    """Accept mongod.log, .log.gz, .txt, and rotated names like mongod.log.2026-06-16T03-22-01."""
    lowered = name.lower()
    if lowered.startswith("."):
        return False
    if lowered.endswith(_LOG_SUFFIXES):
        return True
    if ".log." in lowered:
        return True
    return lowered.endswith(".gz") and ".log" in lowered


def _is_log_archive(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(_LOG_ARCHIVE_SUFFIXES) and not lowered.startswith(".")


async def _collect_log_uploads(request: Request) -> list[StarletteUploadFile]:
    """Read multipart parts explicitly — more reliable than list[UploadFile] binding in browsers."""
    form = await request.form()
    uploads: list[StarletteUploadFile] = []
    seen: set[int] = set()
    for field in ("files", "file"):
        for item in form.getlist(field):
            if not isinstance(item, StarletteUploadFile):
                continue
            item_id = id(item)
            if item_id in seen:
                continue
            seen.add(item_id)
            uploads.append(item)
    return uploads


async def _write_upload_file(upload: StarletteUploadFile, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as handle:
        while True:
            chunk = await upload.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            handle.write(chunk)


def _extract_logs_from_archive_bytes(content: bytes, archive_name: str, log_dir: Path) -> list[str]:
    log_dir.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    lowered = archive_name.lower()

    def save_member(filename: str, data: bytes) -> None:
        base = Path(filename).name
        if not base or not _is_log_filename(base):
            return
        dest = log_dir / base
        dest.write_bytes(data)
        if base not in saved:
            saved.append(base)

    if lowered.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(content), "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    save_member(info.filename, zf.read(info))
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail=f"Invalid zip archive: {archive_name}") from exc
    elif lowered.endswith((".tar.gz", ".tgz", ".tar")):
        try:
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as tf:
                for member in tf.getmembers():
                    if not member.isfile():
                        continue
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    save_member(member.name, extracted.read())
        except tarfile.TarError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid tar archive: {archive_name}") from exc
    else:
        raise HTTPException(status_code=400, detail="Unsupported archive format. Use .zip or .tar.gz")

    if not saved:
        raise HTTPException(
            status_code=400,
            detail="Archive must contain at least one supported log file (.log, rotated .log.*, .log.gz, or .txt)",
        )
    return saved


async def _save_log_upload(upload: StarletteUploadFile, log_dir: Path) -> list[str]:
    filename = (upload.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Missing filename on one of the uploads")

    safe_name = Path(filename).name
    if _is_log_archive(safe_name):
        content = await upload.read()
        return _extract_logs_from_archive_bytes(content, safe_name, log_dir)

    if not _is_log_filename(safe_name):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported log file: {safe_name} "
                "(use .log, rotated .log.*, .log.gz, .txt, or a .zip/.tar.gz of log files)"
            ),
        )

    dest = log_dir / safe_name
    await _write_upload_file(upload, dest)
    return [safe_name]


def _finalize_ftdc_upload(
    *,
    workspace_root: Path,
    run_id: str,
    upload_dir: Path,
    input_dir: Path,
    archive_path: Path,
    original_filename: str,
) -> dict[str, str]:
    """Unpack / store / enqueue off the asyncio event loop (can take minutes for big FTDC)."""
    workspace = RunWorkspace(workspace_root)
    filename_lower = original_filename.lower()
    safe_name = Path(original_filename).name
    try:
        if filename_lower.startswith("metrics.") or safe_name.lower().startswith("metrics."):
            dest = input_dir / safe_name
            if archive_path.resolve() != dest.resolve():
                shutil.move(str(archive_path), str(dest))
        else:
            _unpack_archive(archive_path, input_dir)
            if archive_path.exists():
                archive_path.unlink()

        # Kind: API emptyDir ≠ worker emptyDir — must land bytes in Postgres before enqueue.
        _store_ftdc_raw_files(run_id, input_dir)

        rel_input = input_dir.relative_to(workspace.root)
        job = job_store.create(
            run_id,
            input_path=str(rel_input),
            job_type=JOB_TYPE_MONGO_FTDC,
            workspace_root=workspace.root,
        )
        JobQueue(workspace).enqueue(job, input_dir)
        return {
            "job_id": job.job_id,
            "run_id": run_id,
            "input_path": str(rel_input),
            "status": job.state.value,
        }
    except Exception:
        _remove_upload_tree(upload_dir)
        raise


@router.post("")
async def upload_diagnostic_data(file: UploadFile = File(...)) -> dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    workspace = get_run_workspace()
    run_id = _new_run_id()
    upload_dir = workspace.upload_dir(run_id)
    input_dir = workspace.upload_diagnostic_dir(run_id)
    safe_name = Path(file.filename).name
    archive_path = input_dir.parent / safe_name

    try:
        input_dir.mkdir(parents=True, exist_ok=True)
        # Stream to disk — do not file.read() entire multi-GB zip into RAM on the event loop.
        await _write_upload_file(file, archive_path)
        return await asyncio.to_thread(
            _finalize_ftdc_upload,
            workspace_root=workspace.root,
            run_id=run_id,
            upload_dir=upload_dir,
            input_dir=input_dir,
            archive_path=archive_path,
            original_filename=file.filename,
        )
    except HTTPException:
        _remove_upload_tree(upload_dir)
        raise
    except Exception:
        _remove_upload_tree(upload_dir)
        raise


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, object]:
    job = job_store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return job.to_dict()


@router.post("/runs/{run_id}/retry")
def retry_pipeline_run(run_id: str) -> dict[str, str]:
    workspace = get_run_workspace()
    try:
        job = retry_pipeline_for_run(workspace.root, run_id)
    except PipelineRetryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "job_id": job.job_id,
        "run_id": job.run_id,
        "input_path": job.input_path or "",
        "status": job.state.value,
        "job_type": job.job_type,
    }


@router.post("/runs/{run_id}/logs")
async def upload_mongodb_logs(run_id: str, request: Request) -> dict[str, object]:
    uploads = await _collect_log_uploads(request)
    if not uploads:
        raise HTTPException(
            status_code=400,
            detail=(
                "No log files received. Select individual .log files, rotated .log.* files, "
                "or a .zip/.tar.gz archive containing them."
            ),
        )

    _require_run_exists(run_id)
    workspace = get_run_workspace()
    log_dir = workspace.mongodb_logs_dir(run_id)
    log_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    for upload in uploads:
        for name in await _save_log_upload(upload, log_dir):
            if name not in saved:
                saved.append(name)

    if not saved:
        raise HTTPException(status_code=400, detail="No supported log files were saved")

    workspace.clear_hatchet_artifacts(run_id)

    # K8s: store log bytes in PG so the worker pod can reassemble them from
    # its own emptyDir (API pod and worker pod have separate scratch volumes).
    if get_settings().database_url:
        from backend.app.db.connection import db_conn
        from backend.app.db.raw_files import store_raw_file
        with db_conn() as conn:
            for name in saved:
                path = log_dir / name
                if path.exists():
                    store_raw_file(conn, run_id, "logs", name, path)

    try:
        job = job_store.create(
            run_id,
            input_path=str(log_dir.relative_to(workspace.root)),
            job_type=JOB_TYPE_HATCHET,
            workspace_root=workspace.root,
        )
        JobQueue(workspace).enqueue(job, log_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "job_id": job.job_id,
        "run_id": run_id,
        "saved_files": saved,
        "status": job.state.value,
        "job_type": job.job_type,
    }


@router.post("/runs/{run_id}/logs/retry")
def retry_hatchet_run(run_id: str) -> dict[str, str]:
    workspace = get_run_workspace()
    _require_run_exists(run_id)
    try:
        job = retry_hatchet_for_run(workspace.root, run_id)
    except HatchetRetryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {
        "job_id": job.job_id,
        "run_id": job.run_id,
        "input_path": job.input_path or "",
        "status": job.state.value,
        "job_type": job.job_type,
    }
