from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any

from backend.app.db.connection import db_conn
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


_FIELD_NAMES = frozenset(f.name for f in fields(JobStatus))

_COLUMNS = "job_id, run_id, job_type, state, message, error, input_path, created_at, updated_at"


def _row_to_status(row: tuple) -> JobStatus:
    return JobStatus(
        job_id=row[0],
        run_id=row[1],
        job_type=normalize_job_type(row[2]),
        state=JobState(row[3]),
        message=row[4],
        error=row[5],
        input_path=row[6],
        created_at=row[7],
        updated_at=row[8],
    )


class JobStore:
    """Job lifecycle status on Postgres (docs/PRODUCTION_ARCHITECTURE.md, Decision 8).

    Orchestrator and workers share this state through the database; any pod
    sees any job. The workspace_root parameters are kept for call-site
    compatibility with the old disk-backed store and are ignored.
    """

    def create(
        self,
        run_id: str,
        *,
        input_path: str | None = None,
        job_type: str = DEFAULT_JOB_TYPE,
        workspace_root: Path | None = None,
    ) -> JobStatus:
        job = JobStatus(
            job_id=str(uuid.uuid4()),
            run_id=run_id,
            state=JobState.PENDING,
            input_path=input_path,
            job_type=normalize_job_type(job_type),
            message="Queued",
        )
        self.persist(workspace_root, job)
        return job

    def get(self, job_id: str, *, workspace_root: Path | None = None) -> JobStatus | None:
        with db_conn() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM job_status WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        return _row_to_status(row) if row else None

    def update(self, job_id: str, *, workspace_root: Path | None = None, **kwargs: Any) -> JobStatus | None:
        with db_conn() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM job_status WHERE job_id = %s FOR UPDATE",
                (job_id,),
            ).fetchone()
            if row is None:
                return None
            job = _row_to_status(row)
            for key, value in kwargs.items():
                if key in _FIELD_NAMES:
                    setattr(job, key, value)
            job.updated_at = time.time()
            conn.execute(
                """
                UPDATE job_status
                SET state = %s, message = %s, error = %s, input_path = %s,
                    job_type = %s, updated_at = %s
                WHERE job_id = %s
                """,
                (
                    job.state.value,
                    job.message,
                    job.error,
                    job.input_path,
                    job.job_type,
                    job.updated_at,
                    job_id,
                ),
            )
        return job

    def list_recent(self, limit: int = 20, *, workspace_root: Path | None = None) -> list[JobStatus]:
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM job_status ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [_row_to_status(row) for row in rows]

    def list_all(self) -> list[JobStatus]:
        with db_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM job_status ORDER BY updated_at"
            ).fetchall()
        return [_row_to_status(row) for row in rows]

    def load(self, workspace_root: Path, job_id: str) -> JobStatus | None:
        return self.get(job_id)

    def persist(self, workspace_root: Path | None, job: JobStatus) -> None:
        with db_conn() as conn:
            conn.execute(
                """
                INSERT INTO job_status
                    (job_id, run_id, job_type, state, message, error, input_path,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    message = EXCLUDED.message,
                    error = EXCLUDED.error,
                    input_path = EXCLUDED.input_path,
                    job_type = EXCLUDED.job_type,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    job.job_id,
                    job.run_id,
                    job.job_type,
                    job.state.value,
                    job.message,
                    job.error,
                    job.input_path,
                    job.created_at,
                    job.updated_at,
                ),
            )


job_store = JobStore()
