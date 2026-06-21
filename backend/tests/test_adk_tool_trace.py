from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from backend.app.simagix.llm.tool_trace import (
    ToolTraceCollector,
    adk_tool_trace_identity,
    record_grounding_metadata,
)


def test_adk_tool_trace_identity_google_search() -> None:
    name, category, server = adk_tool_trace_identity("google_search_agent")
    assert name == "google_search"
    assert category == "web"
    assert server is None


def test_adk_tool_trace_identity_evidence() -> None:
    name, category, server = adk_tool_trace_identity("get_metric_window")
    assert name == "simagix-evidence/get_metric_window"
    assert category == "mcp"
    assert server == "simagix-evidence"


def test_record_grounding_metadata_writes_web_row(tmp_path: Path) -> None:
    trace_path = tmp_path / "tool_trace.json"
    trace = ToolTraceCollector(trace_path, agent_id="gemini-adk:test")
    metadata = SimpleNamespace(
        web_search_queries=["MongoDB replication lag"],
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(uri="https://www.mongodb.com/docs/manual/replication/"))
        ],
    )
    event = SimpleNamespace(grounding_metadata=metadata)
    record_grounding_metadata(trace, "investigation", [event])
    trace.save()

    payload = trace_path.read_text(encoding="utf-8")
    assert "google_search" in payload
    assert "replication" in payload
    assert '"category": "web"' in payload


def test_build_adk_agent_tools_includes_web_fetch() -> None:
    from backend.app.simagix.evidence_service import SimagixEvidenceService

    from backend.tests.fixture_paths import FIXTURE_RUN_ID, fixture_bundle_exists

    workspace = Path(__file__).resolve().parents[2]
    run_id = FIXTURE_RUN_ID
    if not fixture_bundle_exists():
        import pytest

        pytest.skip("fixture bundle missing")

    from backend.app.simagix.llm.adk_evidence_tools import build_adk_agent_tools

    evidence = SimagixEvidenceService(workspace, run_id)
    tools = build_adk_agent_tools(evidence)
    tool_names = [getattr(t, "__name__", type(t).__name__) for t in tools]
    assert "web_fetch" in tool_names
