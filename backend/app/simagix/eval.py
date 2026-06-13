from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.simagix.orchestrator import SimagixRCAOrchestrator


def load_golden_incident(workspace_root: Path) -> dict[str, Any]:
    path = workspace_root / "backend/app/simagix/fixtures/golden_incident.json"
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def evaluate_run(workspace_root: Path, run_id: str) -> dict[str, Any]:
    golden = load_golden_incident(workspace_root)
    orchestrator = SimagixRCAOrchestrator(workspace_root, run_id)
    tier1 = orchestrator.load_tier1()
    context = orchestrator.get_prompt_context()

    finding_names = {finding.name for finding in tier1.findings}
    expected_findings = set(golden.get("expected_findings", []))
    matched_findings = sorted(finding_names & expected_findings)
    missing_findings = sorted(expected_findings - finding_names)

    checks = golden.get("minimum_tier1_checks", {})
    findings_ok = len(tier1.findings) >= int(checks.get("findings_count_min", 1))
    anomaly_ok = tier1.executive_context.anomaly_event_count >= int(
        checks.get("anomaly_event_count_min", 1)
    )
    executive_ok = bool(context.get("findings"))

    metric = "repl_lag_host-1"
    window = golden.get("critical_window", {})
    sample = orchestrator.get_metric_window(
        metric,
        start=None,
        end=None,
        limit=5,
    )

    passed = findings_ok and anomaly_ok and executive_ok and len(matched_findings) >= 2
    return {
        "run_id": run_id,
        "passed": passed,
        "matched_findings": matched_findings,
        "missing_findings": missing_findings,
        "findings_count": len(tier1.findings),
        "anomaly_event_count": tier1.executive_context.anomaly_event_count,
        "fallback_sample_metric": metric,
        "fallback_sample_point_count": sample.get("point_count", 0),
        "checks": {
            "findings_ok": findings_ok,
            "anomaly_ok": anomaly_ok,
            "executive_ok": executive_ok,
            "critical_window": window,
        },
    }
