from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path

from backend.app.core.config import get_settings

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_pool = None
_pool_lock = threading.Lock()
_schema_lock = threading.Lock()
_schema_ready = False


def get_pool():
    """Process-wide psycopg connection pool. Requires DATABASE_URL to be set.

    psycopg is imported lazily so importing app modules never needs a
    database; the first actual query does.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                settings = get_settings()
                if not settings.database_url:
                    raise RuntimeError("DATABASE_URL is not configured")
                from psycopg_pool import ConnectionPool

                _pool = ConnectionPool(
                    settings.database_url,
                    min_size=1,
                    max_size=8,
                    open=True,
                    # Don't queue forever when schema/DDL is locked by a stuck txn.
                    timeout=30,
                )
    return _pool


def ensure_schema() -> None:
    """Apply schema.sql once per process. All statements are idempotent."""
    global _schema_ready
    if _schema_ready:
        return
    pool = get_pool()
    with _schema_lock:
        if _schema_ready:
            return
        with pool.connection() as conn:
            # Fail fast if another session holds DDL/relation locks (idle-in-transaction).
            conn.execute("SET lock_timeout = '10s'")
            conn.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
            # Any phase2 rows left in a running state from the previous pod will
            # never complete — reset them to failed so the UI doesn't hang.
            conn.execute(
                "UPDATE phase2_state SET data = '\"failed\"'::jsonb, updated_at = %s"
                " WHERE key = 'status'"
                " AND data::text IN ('\"running_investigation\"', '\"running_rca\"')",
                (time.time(),),
            )
        _schema_ready = True


@contextmanager
def db_conn():
    """A pooled connection with the schema guaranteed applied."""
    ensure_schema()
    with get_pool().connection() as conn:
        yield conn


def reset_for_tests() -> None:
    global _pool, _schema_ready
    if _pool is not None:
        _pool.close()
    _pool = None
    _schema_ready = False
