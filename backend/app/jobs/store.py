from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace
from backend.app.jobs.job_types import DEFAULT_JOB_TYPE, normalize_job_type


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class JobStatus:
    job_id: str
    run_id: str
    state: JobState
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    message: str = ""
    error: str | None = None
    input_path: str | None = None
    job_type: str = DEFAULT_JOB_TYPE

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message": self.message,
            "error": self.error,
            "input_path": self.input_path,
            "job_type": self.job_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobStatus:
        return cls(
            job_id=data["job_id"],
            run_id=data["run_id"],
            state=JobState(data["state"]),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            message=str(data.get("message", "")),
            error=data.get("error"),
            input_path=data.get("input_path"),
            job_type=normalize_job_type(data.get("job_type")),
        )


def _iter_job_record_paths(workspace: RunWorkspace) -> list[Path]:
    paths: list[Path] = []
    seen: set[str] = set()
    for run_dir in workspace.iter_upload_run_dirs():
        jobs_dir = run_dir / "phase1" / "jobs"
        if not jobs_dir.is_dir():
            continue
        for path in jobs_dir.glob("*.json"):
            if path.stem not in seen:
                seen.add(path.stem)
                paths.append(path)
    legacy = workspace.legacy_jobs_root()
    if legacy.is_dir():
        for path in legacy.glob("*.json"):
            if path.stem not in seen:
                seen.add(path.stem)
                paths.append(path)
    return paths


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobStatus] = {}
        self._lock = threading.Lock()

    def create(
        self,
        run_id: str,
        *,
        input_path: str | None = None,
        job_type: str = DEFAULT_JOB_TYPE,
        workspace_root: Path,
    ) -> JobStatus:
        job_id = str(uuid.uuid4())
        job = JobStatus(
            job_id=job_id,
            run_id=run_id,
            state=JobState.PENDING,
            input_path=input_path,
            job_type=normalize_job_type(job_type),
            message="Queued",
        )
        with self._lock:
            self._jobs[job_id] = job
        self.persist(workspace_root, job)
        return job

    def get(self, job_id: str, *, workspace_root: Path | None = None) -> JobStatus | None:
        root = workspace_root
        if root is None:
            from backend.app.core.run_workspace import get_run_workspace

            root = get_run_workspace().root
        disk_job = self._read_from_disk(root, job_id)
        with self._lock:
            cached = self._jobs.get(job_id)
        if disk_job is None:
            return cached
        if cached is None or disk_job.updated_at >= cached.updated_at:
            with self._lock:
                self._jobs[job_id] = disk_job
            return disk_job
        return cached

    def update(self, job_id: str, *, workspace_root: Path | None = None, **kwargs: Any) -> JobStatus | None:
        root = workspace_root
        if root is None:
            from backend.app.core.run_workspace import get_run_workspace

            root = get_run_workspace().root
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                job = self._read_from_disk(root, job_id)
            if job is None:
                return None
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = time.time()
            self._jobs[job_id] = job
        self.persist(root, job)
        return job

    def list_recent(self, limit: int = 20, *, workspace_root: Path | None = None) -> list[JobStatus]:
        root = workspace_root
        if root is None:
            from backend.app.core.run_workspace import get_run_workspace

            root = get_run_workspace().root
        workspace = RunWorkspace(root)
        paths = _iter_job_record_paths(workspace)
        if not paths:
            with self._lock:
                jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            return jobs[:limit]
        jobs: list[JobStatus] = []
        for path in paths:
            job = self._read_from_disk(root, path.stem)
            if job is not None:
                jobs.append(job)
        jobs.sort(key=lambda item: item.updated_at, reverse=True)
        return jobs[:limit]

    def load(self, workspace_root: Path, job_id: str) -> JobStatus | None:
        job = self._read_from_disk(workspace_root, job_id)
        if job is None:
            return None
        with self._lock:
            self._jobs[job_id] = job
        return job

    def _read_from_disk(self, workspace_root: Path, job_id: str) -> JobStatus | None:
        workspace = RunWorkspace(workspace_root)
        path = workspace.find_job_record_path(job_id)
        if path is None:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return JobStatus.from_dict(data)

    def persist(self, workspace_root: Path, job: JobStatus) -> None:
        workspace = RunWorkspace(workspace_root)
        payload = json.dumps(job.to_dict(), indent=2)
        record_path = workspace.job_record_path(job.run_id, job.job_id)
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(payload, encoding="utf-8")
        run_status_path = workspace.job_status_path(job.run_id)
        run_status_path.parent.mkdir(parents=True, exist_ok=True)
        run_status_path.write_text(payload, encoding="utf-8")
        with self._lock:
            self._jobs[job.job_id] = job


job_store = JobStore()
