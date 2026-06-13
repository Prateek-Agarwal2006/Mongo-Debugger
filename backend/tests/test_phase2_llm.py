from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.simagix.llm import mcp_evidence_server as mcp_server
from backend.app.simagix.llm.mock_provider import MockLLMProvider
from backend.app.simagix.llm.parse_output import parse_clarifying_questions, parse_investigation_summary, parse_rca_report
from backend.app.simagix.llm.prompts import (
    build_clarify_user_message,
    build_investigate_user_message,
    build_phase2_user_message,
)
from backend.app.simagix.llm.tool_trace import classify_tool_category
from backend.app.simagix.llm.service import run_investigation, run_phase2
from backend.app.simagix.llm.session import Phase2SessionStore
from backend.app.simagix.orchestrator import SimagixRCAOrchestrator
from backend.app.simagix.output_schema import RCAReportDraft

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_RUN_ID = "phase1test20260609T133314Z"
EXPORTS_DIR = WORKSPACE_ROOT / "simagix-workspace/exports/mongo-ftdc"


def _bundle_exists(run_id: str) -> bool:
    return (EXPORTS_DIR / run_id / "manifest.json").exists()


@pytest.fixture
def fixture_run_id() -> str:
    if not _bundle_exists(FIXTURE_RUN_ID):
        pytest.skip(f"Fixture bundle not found: {FIXTURE_RUN_ID}")
    return FIXTURE_RUN_ID


@pytest.fixture
def session_store() -> Phase2SessionStore:
    return Phase2SessionStore()


def _complete_mock_rca(client: TestClient, run_id: str) -> dict:
    start = client.post(f"/simagix/runs/{run_id}/phase2/run", json={"force_mock": True})
    assert start.status_code == 200
    body = start.json()
    qids = [q["id"] for q in body["clarifying_questions"]["questions"]]
    answers = {qids[0]: "No maintenance during window"} if qids else {}
    clarify = client.post(
        f"/simagix/runs/{run_id}/phase2/clarify?force_mock=true",
        json={"answers": answers},
    )
    assert clarify.status_code == 200
    return clarify.json()


def test_parse_rca_report_from_json_fence() -> None:
    text = """Here is the report:
```json
{
  "run_id": "phase1test",
  "summary": "Replication lag incident",
  "root_cause": "Secondary apply lag",
  "causal_chain": ["writes increased", "lag grew"],
  "ruled_out_hypotheses": [],
  "evidence_citations": [],
  "safe_fixes": ["scale secondaries"],
  "findings_used": ["Replication Lag Issues"],
  "confidence": 0.8
}
```"""
    report = parse_rca_report(text, "phase1test")
    assert report.run_id == "phase1test"
    assert report.summary == "Replication lag incident"
    assert report.confidence == 0.8


def test_parse_clarifying_questions_caps_at_max() -> None:
    text = """```json
{
  "run_id": "phase1test",
  "context_summary": "need ops context",
  "questions": [
    {"id": "q1", "question": "Q1?", "rationale": "R1"},
    {"id": "q2", "question": "Q2?", "rationale": "R2"},
    {"id": "q3", "question": "Q3?", "rationale": "R3"}
  ]
}
```"""
    block = parse_clarifying_questions(text, "phase1test", max_questions=2)
    assert len(block.questions) == 2
    assert block.questions[0].id == "q1"


def test_parse_investigation_summary() -> None:
    text = """```json
{
  "run_id": "phase1test",
  "summary": "Investigated replication lag",
  "findings_reviewed": ["Replication Lag Issues"],
  "tool_calls_made": ["get_metric_window"],
  "metric_insights": ["cpu_idle stable"],
  "log_insights": [],
  "profiler_insights": ["not uploaded"],
  "open_questions_for_operator": ["Any maintenance?"]
}
```"""
    summary = parse_investigation_summary(text, "phase1test")
    assert summary.summary == "Investigated replication lag"
    assert summary.open_questions_for_operator == ["Any maintenance?"]


def test_prompt_builder_includes_investigation(fixture_run_id: str) -> None:
    investigation = run_investigation(WORKSPACE_ROOT, fixture_run_id, force_mock=True)
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_phase2_user_message(
        package,
        investigation=investigation,
        user_answers={"repl_topology": "No maintenance"},
    )
    assert "Prior tier-2 investigation" in message
    assert "finding_analyses" in message
    assert investigation.summary[:60] in message
    assert "Operator clarifications" in message


def test_prompt_builder_includes_user_answers(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_phase2_user_message(
        package,
        user_answers={"repl_topology": "No maintenance during window"},
    )
    assert "Operator clarifications" in message
    assert "repl_topology" in message
    assert "No maintenance during window" in message


def test_prompt_builder_includes_fallback_guidance(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_phase2_user_message(package)
    assert "READ-ONLY analysis mode" in message
    assert "RCAReportDraft" in message
    assert "get_metric_window" in message
    assert "search the web" in message.lower()
    assert "reference_urls" in message


def test_investigate_prompt_has_web_search_no_rca_footer(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_investigate_user_message(package)
    assert "search the web" in message.lower()
    assert "web_insights" in message
    assert "InvestigationSummary only" in message
    assert "Do NOT produce a final RCAReportDraft" in message
    assert "Produce an RCA report matching the RCAReportDraft schema" not in message


def test_clarify_prompt_has_no_rca_footer(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_clarify_user_message(package, max_questions=10)
    assert "ClarifyingQuestionsBlock only" in message
    assert "Produce an RCA report matching the RCAReportDraft schema" not in message
    assert "search the web" not in message.lower()


def test_classify_tool_category() -> None:
    assert classify_tool_category("web_search") == "web"
    assert classify_tool_category("fetch", {"url": "https://mongodb.com/docs"}) == "web"
    assert classify_tool_category("mcp_simagix-evidence_get_metric_window") == "mcp"
    assert classify_tool_category("grep") == "local"
    assert classify_tool_category("run_terminal_cmd") == "shell"


def test_mcp_evidence_tools_with_fixture(fixture_run_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if not (EXPORTS_DIR / fixture_run_id / "llm/fallback_retrieval_index.json").exists():
        pytest.skip("Bundle missing fallback index")

    session_store = Phase2SessionStore()
    session_store.reset(fixture_run_id)
    session = session_store.get_or_create(fixture_run_id, WORKSPACE_ROOT, max_tool_calls=12)
    env = session.mcp_server_env()
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    mcp_server._ORCHESTRATOR = None
    metrics = mcp_server.list_fallback_metrics()
    assert isinstance(metrics, list)
    assert len(metrics) >= 1

    result = mcp_server.get_metric_window("cpu_idle", limit=5)
    assert result["metric"] == "cpu_idle"
    assert result["point_count"] >= 1

    session.refresh_budget()
    assert session.budget_status()["tool_calls_used"] >= 1


def test_session_budget_shared_via_sync_file(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    budget_path = WORKSPACE_ROOT / "simagix-workspace/runs" / fixture_run_id / "phase2/budget_state.json"
    if budget_path.exists():
        budget_path.unlink()
    store.reset(fixture_run_id)

    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, max_tool_calls=12)
    before = session.budget_status()["tool_calls_used"]
    session.orchestrator.get_metric_window("cpu_idle", limit=3)
    session.refresh_budget()
    after = session.budget_status()["tool_calls_used"]
    assert after == before + 1

    session2 = store.get_or_create(fixture_run_id, WORKSPACE_ROOT)
    session2.refresh_budget()
    assert session2.budget_status()["tool_calls_used"] == after


def test_mock_provider_run(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT)
    package = session.orchestrator.build_phase2_llm_package()
    message = build_phase2_user_message(package)
    provider = MockLLMProvider()
    result = provider.run(session, message)
    assert result.report.run_id == fixture_run_id
    assert result.report.root_cause
    assert result.agent_id == "mock-agent-id"


def test_phase2_run_api_mock(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    response = client.post(
        f"/simagix/runs/{fixture_run_id}/phase2/run",
        json={"force_mock": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "awaiting_clarifications"
    assert body["run_id"] == fixture_run_id
    investigation = body.get("investigation", {})
    assert investigation.get("summary")
    assert body.get("clarifying_questions", {}).get("questions")
    assert investigation.get("web_insights")
    assert len(investigation.get("finding_analyses", [])) >= 1
    assert "[mock]" in investigation["finding_analyses"][0].get("why_it_happened", "")
    assert len(investigation.get("incident_timeline", [])) >= 1
    assert "[mock]" in investigation["incident_timeline"][0].get("mechanism", "")


def test_investigate_prompt_requires_mechanism_detail(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_investigate_user_message(package)
    assert "finding_analyses" in message
    assert "incident_timeline" in message
    assert "EVIDENCE RULES" in message
    assert "non-authoritative" in message.lower()
    assert "do not copy" in message.lower()
    assert "do not run shell commands" in message.lower()
    assert "mcp tools only" in message.lower()
    assert "do not use read, grep" in message.lower()


def test_final_rca_prompt_has_evidence_rules(fixture_run_id: str) -> None:
    orchestrator = SimagixRCAOrchestrator(WORKSPACE_ROOT, fixture_run_id)
    package = orchestrator.build_phase2_llm_package()
    message = build_phase2_user_message(package)
    assert "EVIDENCE RULES" in message
    assert "finding name keywords" in message.lower()


def test_phase2_tool_trace_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    client.post(f"/simagix/runs/{fixture_run_id}/phase2/run", json={"force_mock": True})
    trace = client.get(f"/simagix/runs/{fixture_run_id}/phase2/tool-trace")
    assert trace.status_code == 200
    body = trace.json()
    assert "entries" in body
    assert "summary" in body
    assert body["summary"]["total"] >= 1
    categories = body["summary"].get("by_category", {})
    assert categories.get("mcp", 0) >= 1
    assert categories.get("web", 0) >= 1

    status = client.get(f"/simagix/runs/{fixture_run_id}/phase2/status")
    assert status.status_code == 200
    assert "tool_trace_summary" in status.json()


def test_phase2_status_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    client.post(f"/simagix/runs/{fixture_run_id}/phase2/run", json={"force_mock": True})
    status = client.get(f"/simagix/runs/{fixture_run_id}/phase2/status")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "awaiting_clarifications"
    assert "investigation" in body


def test_phase2_latest_report_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    _complete_mock_rca(client, fixture_run_id)

    latest = client.get(f"/simagix/runs/{fixture_run_id}/phase2/reports/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert body["run_id"] == fixture_run_id
    assert "report_text" in body
    assert "RCA REPORT" in body["report_text"]
    report = RCAReportDraft.model_validate(body["report"])
    assert "[mock]" in report.mechanism_summary
    assert len(report.finding_analyses) >= 1
    assert "[mock]" in report.finding_analyses[0].why_it_happened
    assert len(report.incident_timeline) >= 1
    assert "[mock]" in report.summary
    assert "MECHANISM" in body["report_text"]
    assert "FINDING ANALYSES" in body["report_text"]
    assert "Evidence MCP tools:" in body["report_text"]
    assert "tool_usage" in body
    assert body["tool_usage"]["total_sdk_calls"] >= 1

    pretty = client.get(
        f"/simagix/runs/{fixture_run_id}/phase2/reports/latest",
        params={"format": "pretty"},
    )
    assert pretty.status_code == 200
    assert pretty.headers["content-type"].startswith("text/plain")
    assert "RCA REPORT" in pretty.text
    assert "SUMMARY" in pretty.text


def test_run_phase2_service_mock(fixture_run_id: str) -> None:
    run_investigation(WORKSPACE_ROOT, fixture_run_id, provider=MockLLMProvider())
    result = run_phase2(WORKSPACE_ROOT, fixture_run_id, provider=MockLLMProvider())
    assert result.report.run_id == fixture_run_id
    assert result.tool_calls_used >= 0
