import os

import pytest

from backend.tests.db_guard import require_disposable_test_database

# The job queue is Postgres-backed (docs/PRODUCTION_ARCHITECTURE.md, Decision 7).
# Tests require a *disposable* Postgres — never Kind/live `debugger` on service `postgres`.
#   docker run -d --name mongo-debugger-pg -e POSTGRES_PASSWORD=dev \
#     -e POSTGRES_DB=mongodebugger -p 5544:5432 postgres:16-alpine
#   export DATABASE_URL=postgresql://postgres:dev@localhost:5544/mongodebugger
if not os.environ.get("DATABASE_URL"):
    raise RuntimeError(
        "DATABASE_URL must be set to run the test suite (see backend/tests/conftest.py)"
    )

require_disposable_test_database(os.environ["DATABASE_URL"])

from backend.tests.fixture_paths import FIXTURE_RUN_ID, REPO_ROOT, fixture_bundle_exists  # noqa: E402


_FIXTURE_METRIC_NAMES = ("cpu_idle", "cache_used", "conn_current", "repl_lag")
_FIXTURE_METRIC_TS_BASE = 1_718_000_000_000


@pytest.fixture(scope="session", autouse=True)
def _seed_fixture_bundle():
    """Seed fixture evidence blobs + a small synthetic metrics sample into Postgres (once per session)."""
    if not fixture_bundle_exists():
        return
    from backend.app.jobs.ingest import ingest_pipeline_evidence_only
    from backend.app.db.connection import db_conn

    ingest_pipeline_evidence_only(REPO_ROOT, FIXTURE_RUN_ID)

    with db_conn() as conn:
        with conn.cursor() as cur:
            rows = [
                (FIXTURE_RUN_ID, name, _FIXTURE_METRIC_TS_BASE + i * 60_000, float(i))
                for name in _FIXTURE_METRIC_NAMES
                for i in range(5)
            ]
            cur.executemany(
                "INSERT INTO metrics (run_id, name, ts, value) VALUES (%s, %s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                rows,
            )


@pytest.fixture(autouse=True)
def _clean_job_tables():
    """Reset queue / phase2 scratch tables only — never DELETE metrics/evidence/raw_files by run_id.

    Wipe of operator run bodies was removed after a live Kind DB incident. Isolation for
    those tables relies on disposable DATABASE_URL (see require_disposable_test_database).
    """
    from backend.app.db.connection import db_conn

    with db_conn() as conn:
        conn.execute("TRUNCATE jobs, job_status")
        conn.execute("TRUNCATE phase2_state")
    yield
