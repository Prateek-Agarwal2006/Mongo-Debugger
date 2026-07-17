"""Per-module row cleanup helpers.

conftest deliberately does NOT wipe run-scoped tables between tests (see the
live Kind DB incident note in conftest._clean_job_tables). Modules that seed
run-scoped rows must clean up after themselves using these helpers.
"""
from __future__ import annotations

from backend.app.db.connection import db_conn

_HATCHET_TABLES = (
    "hatchet_ops",
    "hatchet_logs",
    "hatchet_audit",
    "hatchet_clients",
    "hatchet_drivers",
)


def wipe_hatchet_rows(run_id: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM evidence WHERE run_id = %s AND key LIKE 'hatchet%%'",
            (run_id,),
        )
        for table in _HATCHET_TABLES:
            conn.execute(f"DELETE FROM {table} WHERE run_id = %s", (run_id,))


def wipe_raw_rows(run_id: str) -> None:
    with db_conn() as conn:
        conn.execute("DELETE FROM raw_files WHERE run_id = %s", (run_id,))
        conn.execute("DELETE FROM raw_file_index WHERE run_id = %s", (run_id,))


def wipe_manifest_row(run_id: str) -> None:
    """Remove the synthetic 'manifest' evidence row tests seed to fake an export."""
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM evidence WHERE run_id = %s AND key = 'manifest'",
            (run_id,),
        )
