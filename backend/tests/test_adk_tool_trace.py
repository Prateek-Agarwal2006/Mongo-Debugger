from __future__ import annotations

from types import SimpleNamespace

from backend.app.simagix.llm.tool_trace import (
    ToolTraceCollector,
    ToolTraceEntry,
    adk_tool_trace_call_id,
    adk_tool_trace_status,
    adk_tool_trace_identity,
    record_grounding_metadata,
)


def test_adk_tool_trace_status_error_from_context() -> None:
    class Ctx:
        error = "MCP tool rejected"

    assert adk_tool_trace_status(Ctx(), {}) == "error"


def test_adk_tool_trace_status_error_from_mcp_response() -> None:
    class Ctx:
        error = None

    assert adk_tool_trace_status(Ctx(), {"isError": True, "content": []}) == "error"
    assert adk_tool_trace_status(Ctx(), {"content": [{"isError": True}]}) == "error"


def test_adk_tool_trace_status_completed() -> None:
    class Ctx:
        error = None

    assert adk_tool_trace_status(Ctx(), {"content": [{"text": "ok"}]}) == "completed"


def test_adk_tool_trace_call_id_prefers_function_call_id() -> None:
    class Ctx:
        function_call_id = "fc-abc"
        invocation_id = "inv-run"

    assert adk_tool_trace_call_id(Ctx()) == "fc-abc"


def test_adk_tool_trace_call_id_none_without_function_call_id() -> None:
    class Ctx:
        invocation_id = "inv-run"

    assert adk_tool_trace_call_id(Ctx()) is None


def test_adk_tool_trace_call_id_scoped_by_phase() -> None:
    trace = ToolTraceCollector("adk-trace-test-run", "gemini", agent_id="gemini-adk:test")

    class Ctx:
        def __init__(self, function_call_id: str) -> None:
            self.function_call_id = function_call_id

    for phase in ("investigation", "final_rca"):
        trace.append_entry(
            ToolTraceEntry(
                phase=phase,
                timestamp="2026-06-30T12:00:00+00:00",
                tool_name="simagix-evidence/get_metric_window",
                category="mcp",
                status="completed",
                call_id=adk_tool_trace_call_id(Ctx("fc-1"), phase),
                args_summary='{"metric": "cpu_idle"}',
                mcp_server="simagix-evidence",
            )
        )
    assert len(trace.entries) == 2


def test_adk_tool_trace_call_id_dedupes_distinct_calls() -> None:
    trace = ToolTraceCollector("adk-trace-test-run", "gemini", agent_id="gemini-adk:test")

    class Ctx:
        def __init__(self, function_call_id: str) -> None:
            self.function_call_id = function_call_id
            self.invocation_id = "same-invocation"

    for metric in ("wt_cache_used", "latency_read", "repl_lag_host-4"):
        trace.append_entry(
            ToolTraceEntry(
                phase="investigation",
                timestamp="2026-06-30T12:00:00+00:00",
                tool_name="simagix-evidence/get_metric_window",
                category="mcp",
                status="completed",
                call_id=adk_tool_trace_call_id(Ctx(f"fc-{metric}")),
                args_summary=f'{{"metric": "{metric}"}}',
                mcp_server="simagix-evidence",
            )
        )
    assert len(trace.entries) == 3


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


def test_record_grounding_metadata_writes_web_row() -> None:
    trace = ToolTraceCollector("adk-trace-test-run", "gemini", agent_id="gemini-adk:test")
    metadata = SimpleNamespace(
        web_search_queries=["MongoDB replication lag"],
        grounding_chunks=[
            SimpleNamespace(web=SimpleNamespace(uri="https://www.mongodb.com/docs/manual/replication/"))
        ],
    )
    event = SimpleNamespace(grounding_metadata=metadata)
    record_grounding_metadata(trace, "investigation", [event])
    trace.save()

    from backend.app.simagix.llm.tool_trace import load_tool_trace

    payload = load_tool_trace("adk-trace-test-run", "gemini")
    entries = payload["entries"]
    assert any(e["tool_name"] == "google_search" for e in entries)
    assert any("replication" in (e.get("args_summary") or "") for e in entries)
    assert any(e["category"] == "web" for e in entries)


def test_adk_tool_trace_identity_prefixed_evidence() -> None:
    name, category, server = adk_tool_trace_identity("simagix-evidence/get_metric_window")
    assert name == "simagix-evidence/get_metric_window"
    assert category == "mcp"
    assert server == "simagix-evidence"


def test_build_web_fetch_tool_callable() -> None:
    from backend.app.simagix.llm.web_fetch import build_web_fetch_tool

    tool = build_web_fetch_tool()
    assert getattr(tool, "__name__", "") == "web_fetch"
