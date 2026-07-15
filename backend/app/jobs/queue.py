from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.core.run_workspace import RunWorkspace
from backend.app.db.connection import db_conn
from backend.app.jobs.job_types import DEFAULT_JOB_TYPE, normalize_job_type
from backend.app.jobs.store import JobStatus


@dataclass(frozen=True)
class QueuedPipelineJob:
    job_id: str
    run_id: str
    input_path: str
    job_type: str = DEFAULT_JOB_TYPE


def _worker_id() -> str:
    return get_settings().worker_id or socket.gethostname()


class JobQueue:
    """Phase 1 job queue on Postgres (docs/PRODUCTION_ARCHITECTURE.md, Decision 7).

    Claims use FOR UPDATE SKIP LOCKED so any number of worker pods drain one
    queue without coordination. A restarting worker requeues only the
    PROCESSING rows it claimed itself (claimed_by = pod hostname), never
    another worker's in-flight jobs.
    """

    def __init__(self, workspace: RunWorkspace) -> None:
        self.workspace = workspace

    def enqueue(self, job: JobStatus, input_dir: Path) -> None:
        rel_input = str(input_dir.relative_to(self.workspace.root))
        with db_conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (job_id, run_id, job_type, input_path)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (job_id) DO NOTHING
                """,
                (job.job_id, job.run_id, normalize_job_type(job.job_type), rel_input),
            )

    def requeue_stale_processing(self) -> int:
        """Crash recovery on worker startup: reclaim only this worker's rows."""
        with db_conn() as conn:
            result = conn.execute(
                """
                UPDATE jobs
                SET state = 'PENDING', claimed_by = NULL, claimed_at = NULL
                WHERE state = 'PROCESSING' AND claimed_by = %s
                """,
                (_worker_id(),),
            )
            return result.rowcount or 0

    def claim_next(self) -> QueuedPipelineJob | None:
        with db_conn() as conn:
            row = conn.execute(
                """
                UPDATE jobs
                SET state = 'PROCESSING', claimed_by = %s, claimed_at = now()
                WHERE job_id = (
                    SELECT job_id FROM jobs
                    WHERE state = 'PENDING'
                    ORDER BY enqueued_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING job_id, run_id, input_path, job_type
                """,
                (_worker_id(),),
            ).fetchone()
        if row is None:
            return None
        return QueuedPipelineJob(
            job_id=row[0],
            run_id=row[1],
            input_path=row[2],
            job_type=normalize_job_type(row[3]),
        )

    def complete(self, run_id: str, job_id: str) -> None:
        with db_conn() as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = %s", (job_id,))

    def has_active_job_for_run(self, run_id: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE run_id = %s LIMIT 1",
                (run_id,),
            ).fetchone()
        return row is not None

    def job_is_queued(self, run_id: str, job_id: str) -> bool:
        return self._in_state(job_id, "PENDING")

    def job_is_processing(self, run_id: str, job_id: str) -> bool:
        return self._in_state(job_id, "PROCESSING")

    def _in_state(self, job_id: str, state: str) -> bool:
        with db_conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM jobs WHERE job_id = %s AND state = %s",
                (job_id, state),
            ).fetchone()
        return row is not None
