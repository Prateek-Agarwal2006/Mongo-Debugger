from __future__ import annotations

from types import SimpleNamespace

from backend.app.simagix.llm.providers.cursor.errors import (
    cursor_parse_failure_message,
    cursor_run_failure_message,
)


def test_cursor_run_failure_message_includes_sdk_fields() -> None:
    result = SimpleNamespace(
        status="error",
        id="run-abc",
        agent_id="agent-1",
        result="MCP server hatchet-evidence exited",
        duration_ms=1200,
    )
    text = cursor_run_failure_message(result)
    assert "run-abc" in text
    assert "MCP server hatchet-evidence exited" in text
    assert "error" in text


def test_cursor_parse_failure_message_includes_full_raw_text() -> None:
    raw = "x" * 500
    text = cursor_parse_failure_message("bad json", raw)
    assert raw in text
    assert "bad json" in text
