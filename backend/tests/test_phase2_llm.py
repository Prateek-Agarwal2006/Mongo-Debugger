from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.run_workspace import RunWorkspace
from backend.app.core.config import get_settings
from backend.app.main import create_app
from backend.app.simagix.llm import mcp_evidence_server as mcp_server
from backend.app.simagix.llm.mock_provider import MockLLMProvider
from backend.app.simagix.llm.parse_output import parse_clarifying_questions, parse_investigation_summary, parse_rca_report
from backend.app.simagix.llm.prompts import (
    build_clarify_user_message,
    build_investigate_user_message,
    build_phase2_user_message,
)
from backend.app.simagix.llm.web_fetch import validate_web_fetch_url
from backend.app.simagix.llm.tool_trace import classify_tool_category, resolve_tool_identity
from backend.app.simagix.llm.service import run_investigation, run_phase2
from backend.app.simagix.llm.session import Phase2SessionStore, phase2_session_store
from backend.app.simagix.evidence_service import SimagixEvidenceService
from backend.app.simagix.output_schema import RCAReportDraft

from backend.tests.fixture_paths import FIXTURE_RUN_ID, fixture_bundle_exists, fixture_exports_dir

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def _mock_session_dir(run_id: str) -> Path:
    return RunWorkspace(WORKSPACE_ROOT).llm_session_dir(run_id, "mock")


def _bundle_exists(run_id: str) -> bool:
    if run_id != FIXTURE_RUN_ID:
        return False
    return fixture_bundle_exists()


@pytest.fixture
def fixture_run_id() -> str:
    if not _bundle_exists(FIXTURE_RUN_ID):
        pytest.skip(f"Fixture bundle not found: {FIXTURE_RUN_ID}")
    return FIXTURE_RUN_ID


@pytest.fixture
def session_store() -> Phase2SessionStore:
    return Phase2SessionStore()


def _complete_mock_rca(client: TestClient, run_id: str) -> dict:
    start = client.post(f"/simagix/runs/{run_id}/phase2/run", json={"llm": "mock"})
    assert start.status_code == 200
    body = start.json()
    qids = [q["id"] for q in body["clarifying_questions"]["questions"]]
    answers = {qids[0]: "No maintenance during window"} if qids else {}
    clarify = client.post(
        f"/simagix/runs/{run_id}/phase2/clarify?llm=mock",
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




def test_parse_rca_report_nested_json_with_preamble() -> None:
    text = """MCP metric calls were rejected. RCA below uses tier-1 evidence.

```json
{
  "run_id": "upload20260611T133630Z",
  "summary": "FTDC capture showed replication lag",
  "root_cause": "Secondary apply lag",
  "finding_analyses": [
    {
      "finding_name": "Replication Lag",
      "what_observed": "lag elevated",
      "why_it_happened": "write burst"
    }
  ],
  "incident_timeline": [
    {
      "time_window": "2026-06-11T12:00:00Z",
      "observation": "lag spike",
      "mechanism": "oplog apply delay"
    }
  ],
  "causal_chain": ["writes increased", "lag grew"],
  "evidence_citations": [],
  "confidence": 0.8
}
```"""
    report = parse_rca_report(text, "upload20260611T133630Z")
    assert report.run_id == "upload20260611T133630Z"
    assert len(report.finding_analyses) == 1
    assert len(report.incident_timeline) == 1


def test_parse_rca_report_fills_missing_root_cause_from_summary() -> None:
    text = """```json
{"run_id": "x", "summary": "Disk pressure caused stalls"}
```"""
    report = parse_rca_report(text, "x")
    assert report.root_cause == "Disk pressure caused stalls"

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
    investigation = run_investigation(WORKSPACE_ROOT, fixture_run_id, llm="mock", force_mock=True)
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
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
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_phase2_user_message(
        package,
        user_answers={"repl_topology": "No maintenance during window"},
    )
    assert "Operator clarifications" in message
    assert "repl_topology" in message
    assert "No maintenance during window" in message


def test_prompt_builder_includes_fallback_guidance(fixture_run_id: str) -> None:
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_phase2_user_message(package)
    assert "READ-ONLY analysis mode" in message
    assert "RCAReportDraft" in message
    assert "get_metric_window" in message
    assert "search the web" in message.lower()
    assert "reference_urls" in message


def test_investigate_prompt_has_web_search_no_rca_footer(fixture_run_id: str) -> None:
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_investigate_user_message(package)
    assert "search the web" in message.lower()
    assert "web_insights" in message
    assert "InvestigationSummary only" in message
    assert "Do NOT produce a final RCAReportDraft" in message
    assert "Produce an RCA report matching the RCAReportDraft schema" not in message


def test_clarify_prompt_has_no_rca_footer(fixture_run_id: str) -> None:
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_clarify_user_message(package, max_questions=10)
    assert "ClarifyingQuestionsBlock only" in message
    assert "Produce an RCA report matching the RCAReportDraft schema" not in message
    assert "search the web" not in message.lower()


def test_classify_tool_category() -> None:
    assert classify_tool_category("web_search") == "web"
    assert classify_tool_category("fetch", {"url": "https://mongodb.com/docs"}) == "web"
    assert classify_tool_category("mcp_simagix-evidence_get_metric_window") == "mcp"
    assert classify_tool_category(
        "mcp",
        {"toolName": "get_metric_window", "providerIdentifier": "simagix-evidence"},
    ) == "mcp"
    assert classify_tool_category("grep") == "local"
    assert classify_tool_category("run_terminal_cmd") == "shell"


def test_resolve_tool_identity_mcp_wrapper() -> None:
    name, server = resolve_tool_identity(
        "mcp",
        {"toolName": "get_metric_window", "providerIdentifier": "simagix-evidence"},
    )
    assert name == "simagix-evidence/get_metric_window"
    assert server == "simagix-evidence"




def test_mcp_server_env_includes_pythonpath(fixture_run_id: str, session_store: Phase2SessionStore) -> None:
    session = session_store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock")
    env = session.mcp_server_env()
    assert "PYTHONPATH" in env
    assert str(WORKSPACE_ROOT) in env["PYTHONPATH"]
    assert env["SIMAGIX_BUDGET_STATE_PATH"].endswith("phase2/llm/mock/budget_state.json")

def test_mcp_evidence_tools_with_fixture(fixture_run_id: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if not (fixture_exports_dir() / "llm/fallback_retrieval_index.json").exists():
        pytest.skip("Bundle missing fallback index")

    session_store = Phase2SessionStore()
    session_store.reset(fixture_run_id, "mock")
    session = session_store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    env = session.mcp_server_env()
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    mcp_server._EVIDENCE_SERVICE = None
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
    budget_path = _mock_session_dir(fixture_run_id) / "budget_state.json"
    if budget_path.exists():
        budget_path.unlink()
    store.reset(fixture_run_id, "mock")

    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock", max_tool_calls=12)
    before = session.budget_status()["tool_calls_used"]
    session.evidence.get_metric_window("cpu_idle", limit=3)
    session.refresh_budget()
    after = session.budget_status()["tool_calls_used"]
    assert after == before + 1

    session2 = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock")
    session2.refresh_budget()
    assert session2.budget_status()["tool_calls_used"] == after


def test_mock_provider_run(fixture_run_id: str) -> None:
    store = Phase2SessionStore()
    session = store.get_or_create(fixture_run_id, WORKSPACE_ROOT, llm="mock")
    package = session.evidence.build_phase2_llm_package()
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
        json={"llm": "mock"},
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
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_investigate_user_message(package)
    assert "finding_analyses" in message
    assert "incident_timeline" in message
    assert "EVIDENCE RULES" in message
    assert "non-authoritative" in message.lower()
    assert "do not copy" in message.lower()
    assert "SCRATCH RULES" in message
    assert "chatbot_scratch" in message
    assert "web_fetch" in message.lower()


def test_validate_web_fetch_url_public_https() -> None:
    assert validate_web_fetch_url("https://www.mongodb.com/docs/manual/replication/").startswith("https://")
    assert validate_web_fetch_url("https://example.com/page").startswith("https://")
    with pytest.raises(ValueError, match="https"):
        validate_web_fetch_url("http://example.com/page")
    with pytest.raises(ValueError, match="not allowed"):
        validate_web_fetch_url("https://127.0.0.1/internal")


def test_final_rca_prompt_has_evidence_rules(fixture_run_id: str) -> None:
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    package = evidence.build_phase2_llm_package()
    message = build_phase2_user_message(package)
    assert "EVIDENCE RULES" in message
    assert "finding name keywords" in message.lower()


def test_phase2_tool_trace_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    client.post(f"/simagix/runs/{fixture_run_id}/phase2/run", json={"llm": "mock"})
    trace = client.get(f"/simagix/runs/{fixture_run_id}/phase2/tool-trace?llm=mock")
    assert trace.status_code == 200
    body = trace.json()
    assert "entries" in body
    assert "summary" in body
    assert body["summary"]["total"] >= 1
    categories = body["summary"].get("by_category", {})
    assert categories.get("mcp", 0) >= 1
    assert categories.get("web", 0) >= 1

    status = client.get(f"/simagix/runs/{fixture_run_id}/phase2/status?llm=mock")
    assert status.status_code == 200
    assert "tool_trace_summary" in status.json()


def test_phase2_status_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    client.post(f"/simagix/runs/{fixture_run_id}/phase2/run", json={"llm": "mock"})
    status = client.get(f"/simagix/runs/{fixture_run_id}/phase2/status?llm=mock")
    assert status.status_code == 200
    body = status.json()
    assert body["status"] == "awaiting_clarifications"
    assert "investigation" in body


def test_phase2_latest_report_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    _complete_mock_rca(client, fixture_run_id)

    latest = client.get(f"/simagix/runs/{fixture_run_id}/phase2/reports/latest?llm=mock")
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
        params={"format": "pretty", "llm": "mock"},
    )
    assert pretty.status_code == 200
    assert pretty.headers["content-type"].startswith("text/plain")
    assert "RCA REPORT" in pretty.text
    assert "SUMMARY" in pretty.text


def test_run_phase2_service_mock(fixture_run_id: str) -> None:
    run_investigation(WORKSPACE_ROOT, fixture_run_id, llm="mock", provider=MockLLMProvider())
    result = run_phase2(WORKSPACE_ROOT, fixture_run_id, llm="mock", provider=MockLLMProvider())
    assert result.report.run_id == fixture_run_id
    assert result.tool_calls_used >= 0


def test_get_llm_provider_defaults_to_mock_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "cursor")
    monkeypatch.setenv("CURSOR_API_KEY", "")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    get_settings.cache_clear()
    from backend.app.simagix.llm.service import get_llm_provider

    provider = get_llm_provider()
    assert provider.provider_name == "mock"
    get_settings.cache_clear()


def test_get_llm_provider_gemini_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-google-key")
    get_settings.cache_clear()
    from backend.app.simagix.llm.service import get_llm_provider

    provider = get_llm_provider()
    assert provider.provider_name == "gemini-adk"
    get_settings.cache_clear()


def test_gemini_adk_provider_requires_api_key() -> None:
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.gemini_adk_provider import GeminiAdkLLMProvider

    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        GeminiAdkLLMProvider(Settings(google_api_key=None))


def test_adk_evidence_tools_delegate_to_service(fixture_run_id: str) -> None:
    from backend.app.simagix.llm.adk_evidence_tools import build_adk_evidence_tools

    evidence = SimagixEvidenceService(WORKSPACE_ROOT, fixture_run_id)
    tools = build_adk_evidence_tools(evidence)
    names = {getattr(tool, "__name__", "") for tool in tools}
    assert "get_metric_window" in names
    assert "get_budget_status" in names
    budget = tools[4]()
    assert "remaining" in budget or "tool_calls_used" in budget


def test_phase2_status_requires_llm(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    status = client.get(f"/simagix/runs/{fixture_run_id}/phase2/status")
    assert status.status_code == 400


def test_llm_sessions_list_api(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    client.post(f"/simagix/runs/{fixture_run_id}/phase2/run", json={"llm": "mock"})
    resp = client.get(f"/simagix/runs/{fixture_run_id}/phase2/llm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == fixture_run_id
    llms = {entry["llm"] for entry in body["llm_sessions"]}
    assert "mock" in llms


def test_phase2_run_accepts_llm_provider_mock(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    start = client.post(
        f"/simagix/runs/{fixture_run_id}/phase2/run",
        json={"llm_provider": "mock"},
    )
    assert start.status_code == 200
    assert start.json()["llm_provider"] == "mock"


def test_llm_providers_api() -> None:
    client = TestClient(create_app())
    resp = client.get("/simagix/runs/phase2/llm-providers")
    assert resp.status_code == 200
    body = resp.json()
    assert "options" in body
    ids = {opt["id"] for opt in body["options"]}
    assert ids == {"default", "cursor", "gemini", "mock"}


def test_chatbot_404_without_report(fixture_run_id: str) -> None:
    session_dir = _mock_session_dir(fixture_run_id)
    report_path = session_dir / "latest_report.json"
    backup = report_path.read_text(encoding="utf-8") if report_path.exists() else None
    if report_path.exists():
        report_path.unlink()
    phase2_session_store.reset(fixture_run_id, "mock")
    try:
        client = TestClient(create_app())
        resp = client.get(f"/simagix/runs/{fixture_run_id}/phase2/chatbot?llm=mock")
        assert resp.status_code == 404
    finally:
        if backup is not None:
            report_path.write_text(backup, encoding="utf-8")


def test_chatbot_api_mock(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    _complete_mock_rca(client, fixture_run_id)
    chat_path = _mock_session_dir(fixture_run_id) / "chatbot_chat.json"
    if chat_path.exists():
        chat_path.unlink()
    phase2_session_store.reset(fixture_run_id, "mock")
    before = client.get(f"/simagix/runs/{fixture_run_id}/phase2/chatbot?llm=mock")
    assert before.status_code == 200
    assert before.json()["messages"] == []
    post = client.post(
        f"/simagix/runs/{fixture_run_id}/phase2/chatbot/messages?llm=mock",
        json={"content": "What is the root cause?"},
    )
    assert post.status_code == 200
    body = post.json()
    assert body["message"]["role"] == "assistant"
    assert "root cause" in body["message"]["content"].lower()
    after = client.get(f"/simagix/runs/{fixture_run_id}/phase2/chatbot?llm=mock")
    assert len(after.json()["messages"]) == 2


def test_chatbot_attachment_upload_and_message(fixture_run_id: str) -> None:
    client = TestClient(create_app())
    _complete_mock_rca(client, fixture_run_id)
    chat_path = _mock_session_dir(fixture_run_id) / "chatbot_chat.json"
    if chat_path.exists():
        chat_path.unlink()
    phase2_session_store.reset(fixture_run_id, "mock")

    upload = client.post(
        f"/simagix/runs/{fixture_run_id}/phase2/chatbot/attachments?llm=mock",
        files={"file": ("notes.txt", b"slow query on orders", "text/plain")},
    )
    assert upload.status_code == 200
    attachment = upload.json()
    assert attachment["path"].startswith("attachments/")
    assert attachment["name"] == "notes.txt"

    post = client.post(
        f"/simagix/runs/{fixture_run_id}/phase2/chatbot/messages?llm=mock",
        json={
            "content": "What does the attached notes file say?",
            "attachments": [
                {
                    "name": attachment["name"],
                    "path": attachment["path"],
                    "size": attachment["size"],
                }
            ],
        },
    )
    assert post.status_code == 200
    history = client.get(f"/simagix/runs/{fixture_run_id}/phase2/chatbot?llm=mock")
    user_msg = history.json()["messages"][0]
    assert user_msg["attachments"][0]["path"] == attachment["path"]

    scratch_file = _mock_session_dir(fixture_run_id) / "chatbot_scratch" / attachment["path"]
    assert scratch_file.is_file()
    assert b"slow query" in scratch_file.read_bytes()
