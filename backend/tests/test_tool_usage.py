from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.simagix.llm.detail_requirements import warn_prompt_example_echo
from backend.app.simagix.llm.session import Phase2SessionStore
from backend.app.simagix.llm.tool_trace import ToolTraceEntry, ToolTraceCollector
from backend.app.simagix.output_schema import RCAReportDraft
from backend.app.simagix.tool_usage import resolve_tool_usage, tool_usage_summary

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"


@pytest.fixture
def fixture_run_id() -> str:
    bundle = WORKSPACE_ROOT / "simagix-workspace/exports/mongo-ftdc" / FIXTURE_RUN_ID
    if not (bundle / "manifest.json").exists():
        pytest.skip(f"Fixture bundle not found: {FIXTURE_RUN_ID}")
    return FIXTURE_RUN_ID


def test_tool_usage_summary_prefers_trace_mcp_over_zero_budget(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    store.reset(fixture_run_id, "mock")
    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    session.configure_budget(12, reset=True)

    collector = ToolTraceCollector(session.tool_trace_path, agent_id="test-agent")
    collector.append_entry(
        ToolTraceEntry(
            phase="investigation",
            timestamp="2026-06-11T00:00:00+00:00",
            tool_name="mcp_simagix-evidence_get_metric_window",
            category="mcp",
            status="completed",
            call_id="test-mcp-1",
            mcp_server="simagix-evidence",
        )
    )
    collector.save()

    usage = tool_usage_summary(session)
    assert usage["mcp_evidence_calls"] >= 1
    assert usage["total_sdk_calls"] >= 1


def test_persist_report_stores_tool_usage(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    store.reset(fixture_run_id, "mock")
    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    report = RCAReportDraft(
        run_id=fixture_run_id,
        summary="[mock] test",
        root_cause="[mock] test",
    )
    session.persist_report(report, agent_id="agent-test", provider="mock")

    meta = json.loads(session.metadata_path.read_text(encoding="utf-8"))
    assert "tool_usage" in meta
    assert "mcp_evidence_calls" in meta["tool_usage"]
    assert "total_sdk_calls" in meta["tool_usage"]


def test_resolve_tool_usage_uses_persisted_snapshot(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    snapshot = {
        "mcp_evidence_calls": 9,
        "mcp_budget_max": 12,
        "total_sdk_calls": 15,
        "by_category": {"mcp": 9, "web": 3, "local": 3},
        "tool_call_history": ["get_metric_window"],
    }
    session.metadata_path.write_text(
        json.dumps({"tool_usage": snapshot}, indent=2),
        encoding="utf-8",
    )
    assert resolve_tool_usage(session) == snapshot


def test_warn_prompt_example_echo_detects_markers() -> None:
    matches = warn_prompt_example_echo("Disk I/O stalled engine threads during the spike.")
    assert "stalled engine threads" in matches
