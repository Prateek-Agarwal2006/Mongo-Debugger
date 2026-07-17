"""Refuse pytest against Kind/live Postgres (operator data wipe protection)."""

from __future__ import annotations

from urllib.parse import urlparse


def require_disposable_test_database(database_url: str) -> None:
    """Raise RuntimeError if DATABASE_URL looks like Kind/live or a non-test DB."""
    parsed = urlparse(database_url)
    host = (parsed.hostname or "").lower()
    db_name = (parsed.path or "").lstrip("/").lower()

    # Kind Helm default: postgresql://…@postgres:5432/debugger
    if host == "postgres" or db_name == "debugger":
        raise RuntimeError(
            "Refusing DATABASE_URL that looks like Kind/live Postgres "
            f"(host={host!r}, db={db_name!r}). Use a disposable DB, e.g. "
            "postgresql://postgres:dev@127.0.0.1:5544/mongodebugger — "
            "never point pytest at the cluster database."
        )

    local_hosts = {"localhost", "127.0.0.1", "::1"}
    # CI + docs use db name mongodebugger on localhost
    if host in local_hosts and db_name == "mongodebugger":
        return
    if db_name.endswith("_test") or db_name.endswith("test"):
        return

    raise RuntimeError(
        "Refusing DATABASE_URL for pytest: use localhost mongodebugger "
        "(see docs/OPERATIONS.md) or a database name ending in 'test'. "
        f"Got host={host!r}, db={db_name!r}."
    )
