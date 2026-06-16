from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.simagix.bundle import SimagixBundleLoader
from backend.app.simagix.eval import evaluate_run
from backend.app.simagix.grounding import GroundingRules
from backend.app.simagix.evidence_service import SimagixEvidenceService
from backend.app.simagix.output_schema import RCAReportDraft

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
EXPORTS_DIR = WORKSPACE_ROOT / "simagix-workspace/exports/mongo-ftdc"


def _latest_run_id() -> str | None:
    latest_path = EXPORTS_DIR / "latest_run_id.txt"
    if latest_path.exists():
        return latest_path.read_text(encoding="utf-8").strip()
    runs = sorted(
        [item.name for item in EXPORTS_DIR.iterdir() if item.is_dir() and (item / "manifest.json").exists()],
        reverse=True,
    )
    return runs[0] if runs else None


@pytest.fixture(scope="module")
def run_id() -> str:
    current = _latest_run_id()
    if not current:
        pytest.skip("No Simagix export bundle available")
    return current


def test_grounding_rules_present() -> None:
    rules = GroundingRules().as_dict()
    assert rules["must_cite_evidence"] is True
    assert len(rules["rules"]) >= 3
    assert "score_semantics" in rules
    assert rules["score_semantics"]["101"]["meaning"].startswith("not assessed")


def test_grounding_allowed_sources_include_web_and_investigation() -> None:
    sources = GroundingRules().as_dict()["allowed_evidence_sources"]
    for key in (
        "finding.suggestion",
        "investigation_summary",
        "profiler_insights",
        "log_insights",
        "operator_clarifications",
        "web_search",
    ):
        assert key in sources
    citation = GroundingRules().as_dict()["citation_format"]
    assert "web" in citation
    assert citation["web"] == "web:{url}"
    assert "suggestion" in citation


def test_score_semantics_in_context(run_id: str) -> None:
    loader = SimagixBundleLoader(EXPORTS_DIR / run_id)
    context = loader.assemble_prompt_context(run_id)
    assert "score_semantics" in context
    assert context["score_semantics"]["101"]["meaning"].startswith("not assessed")


def test_prompt_includes_score_legend(run_id: str) -> None:
    from backend.app.simagix.prompt import build_phase2_prompt

    loader = SimagixBundleLoader(EXPORTS_DIR / run_id)
    prompt = build_phase2_prompt(loader.assemble_prompt_context(run_id))
    assert "Score 101" in prompt
    assert "NOT ASSESSED" in prompt


def test_tier1_evidence_block_includes_suggestion(run_id: str) -> None:
    from backend.app.simagix.prompt import build_tier1_evidence_block

    loader = SimagixBundleLoader(EXPORTS_DIR / run_id)
    context = loader.assemble_prompt_context(run_id)
    block = build_tier1_evidence_block(context)
    assert "suggestion:" in block
    assert "description:" in block
    findings = context.get("findings", [])
    if findings and findings[0].get("suggestion"):
        assert findings[0]["suggestion"] in block


def test_output_schema_shape() -> None:
    draft = RCAReportDraft(
        run_id="test",
        summary="summary",
        root_cause="cause",
        causal_chain=["a -> b"],
        ruled_out_hypotheses=["disk full"],
        evidence_citations=[],
        safe_fixes=["add index"],
        findings_used=["Replication Lag Issues"],
        confidence=0.8,
    )
    payload = draft.model_dump()
    assert payload["run_id"] == "test"
    assert payload["confidence"] == 0.8


def test_tier1_loader(run_id: str) -> None:
    bundle_dir = EXPORTS_DIR / run_id
    if not (bundle_dir / "llm/executive_context.json").exists():
        pytest.skip("Bundle uses legacy format; regenerate export with updated llm-export")
    loader = SimagixBundleLoader(bundle_dir)
    tier1 = loader.load_tier1(run_id)
    assert tier1.executive_context.contract_version == "1.0.0"
    assert len(tier1.findings) >= 1
    assert tier1.executive_context.anomaly_event_count >= 1
    assert "llm/executive_context.json" in tier1.executive_context.read_order


def test_fallback_metric_window(run_id: str) -> None:
    bundle_dir = EXPORTS_DIR / run_id
    if not (bundle_dir / "llm/fallback_retrieval_index.json").exists():
        pytest.skip("Bundle missing fallback index; regenerate export")
    evidence = SimagixEvidenceService(WORKSPACE_ROOT, run_id)
    result = evidence.get_metric_window("cpu_idle", limit=10)
    assert result["metric"] == "cpu_idle"
    assert result["point_count"] >= 1


def test_simagix_api_endpoints(run_id: str) -> None:
    bundle_dir = EXPORTS_DIR / run_id
    if not (bundle_dir / "llm/executive_context.json").exists():
        pytest.skip("Bundle uses legacy format; regenerate export")
    client = TestClient(create_app())
    assert client.get("/simagix/runs").status_code == 200
    context = client.get(f"/simagix/runs/{run_id}/context")
    assert context.status_code == 200
    body = context.json()
    assert body["run_id"] == run_id
    assert "findings" in body
    tools = client.get(
        f"/simagix/runs/{run_id}/tools/metric-window",
        params={"metric": "cpu_idle", "limit": 5},
    )
    assert tools.status_code == 200
    package = client.get(f"/simagix/runs/{run_id}/phase2/package")
    assert package.status_code == 200
    assert "prompt" in package.json()
    assert "grounding_rules" in package.json()


def test_golden_incident_eval(run_id: str) -> None:
    bundle_dir = EXPORTS_DIR / run_id
    if not (bundle_dir / "llm/executive_context.json").exists():
        pytest.skip("Bundle uses legacy format; regenerate export")
    result = evaluate_run(WORKSPACE_ROOT, run_id)
    assert result["findings_count"] >= 2
    if run_id == "phase1test20260609T133314Z":
        assert result["fallback_sample_point_count"] >= 1


def test_contract_doc_exists() -> None:
    contract = WORKSPACE_ROOT / "docs/export_contract.md"
    assert contract.exists()
    text = contract.read_text(encoding="utf-8")
    assert "tier_1_analyzed" in text
    assert "tier_2_normalized" in text


def test_evidence_guide_exists() -> None:
    guide = WORKSPACE_ROOT / "docs/EVIDENCE_GUIDE.md"
    assert guide.exists()
    text = guide.read_text(encoding="utf-8")
    assert "tier_1_analyzed" in text
    assert "fallback_retrieval_index" in text
    assert "executive_context" in text
