from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.core.run_workspace import RunWorkspace
from backend.app.simagix.llm.session import Phase2SessionStore
from backend.app.simagix.llm.tool_trace import ToolTraceCollector, ToolTraceEntry
from backend.tests.fixture_paths import FIXTURE_RUN_ID, fixture_bundle_exists

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fixture_run_id() -> str:
    if not fixture_bundle_exists():
        pytest.skip(f"Fixture bundle not found: {FIXTURE_RUN_ID}")
    return FIXTURE_RUN_ID


def _budget_path(run_id: str, llm: str) -> Path:
    return RunWorkspace(WORKSPACE_ROOT).llm_session_dir(run_id, llm) / "budget_state.json"


def test_separate_sessions_and_budgets_per_llm(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    store.reset(fixture_run_id, "mock")
    store.reset(fixture_run_id, "gemini")

    mock_session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    gemini_session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="gemini", max_tool_calls=12)

    assert mock_session is not gemini_session
    assert mock_session.llm == "mock"
    assert gemini_session.llm == "gemini"
    assert mock_session.evidence.bundle_dir == gemini_session.evidence.bundle_dir

    mock_session.configure_budget(12, reset=True)
    gemini_session.configure_budget(12, reset=True)
    mock_session.evidence.get_metric_window("cpu_idle", limit=3)
    mock_session.refresh_budget()

    mock_budget = json.loads(_budget_path(fixture_run_id, "mock").read_text(encoding="utf-8"))
    gemini_budget_path = _budget_path(fixture_run_id, "gemini")
    assert mock_budget["tool_calls_used"] >= 1
    if gemini_budget_path.exists():
        gemini_budget = json.loads(gemini_budget_path.read_text(encoding="utf-8"))
        assert gemini_budget.get("tool_calls_used", 0) == 0


def test_separate_tool_traces_per_llm(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    store.reset(fixture_run_id, "mock")
    store.reset(fixture_run_id, "gemini")

    mock_session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    gemini_session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="gemini", max_tool_calls=12)

    collector = ToolTraceCollector(mock_session.tool_trace_path, agent_id="mock-agent")
    collector.append_entry(
        ToolTraceEntry(
            phase="investigation",
            timestamp="2026-06-11T00:00:00+00:00",
            tool_name="mcp_simagix-evidence_get_metric_window",
            category="mcp",
            status="completed",
            call_id="mock-only",
            mcp_server="simagix-evidence",
        )
    )
    collector.save()

    mock_trace = json.loads(mock_session.tool_trace_path.read_text(encoding="utf-8"))
    assert mock_trace["entries"]
    assert mock_trace["entries"][0]["call_id"] == "mock-only"

    if gemini_session.tool_trace_path.exists():
        gemini_trace = json.loads(gemini_session.tool_trace_path.read_text(encoding="utf-8"))
        call_ids = {entry.get("call_id") for entry in gemini_trace.get("entries", [])}
        assert "mock-only" not in call_ids
