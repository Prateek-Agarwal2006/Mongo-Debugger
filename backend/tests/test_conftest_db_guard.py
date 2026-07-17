"""Guard: pytest must never target Kind/live Postgres."""

from __future__ import annotations

import pytest

from backend.tests.db_guard import require_disposable_test_database


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:password@postgres:5432/debugger",
        "postgresql://postgres:password@127.0.0.1:5432/debugger",
        "postgresql://postgres:dev@localhost:5544/production",
    ],
)
def test_refuse_live_or_non_test_database_url(url: str) -> None:
    with pytest.raises(RuntimeError, match="Refusing DATABASE_URL"):
        require_disposable_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://postgres:dev@localhost:5544/mongodebugger",
        "postgresql://postgres:test@127.0.0.1:5432/mongodebugger",
        "postgresql://postgres:dev@localhost:5432/mongo_debugger_test",
    ],
)
def test_allow_disposable_test_database_url(url: str) -> None:
    require_disposable_test_database(url)
