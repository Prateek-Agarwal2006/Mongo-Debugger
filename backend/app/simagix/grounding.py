from __future__ import annotations

from typing import Any

from backend.app.simagix.scoring import score_semantics


class GroundingRules:
    """Citation and anti-hallucination rules for Phase 2 LLM RCA."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "must_cite_evidence": True,
            "allowed_evidence_sources": [
                "finding.name",
                "finding.symptoms",
                "finding.suggestion",
                "top_anomaly_windows",
                "assessment_highlights",
                "fallback_tool_results",
                "investigation_summary",
                "log_insights",
                "operator_clarifications",
                "web_search",
            ],
            "citation_format": {
                "finding": "finding:{name}",
                "metric": "metric:{metric}@{from}->{to}",
                "anomaly": "anomaly:{metric} peak={peak} from={from}",
                "log": "log:{reference}",
                "operator": "operator:{question_id}",
                "suggestion": "suggestion:finding:{name}",
                "web": "web:{url}",
            },
            "score_semantics": score_semantics(),
            "rules": [
                "Start from tier_1 analyzed mongo-ftdc findings; do not rediscover health issues from raw metrics.",
                "Simagix scores 0-100 only: lower is worse. Score 101 means not assessed (N/A) — never interpret 101 as healthy.",
                "Every root-cause claim must cite at least one finding, anomaly window, fallback metric slice, log, or operator clarification.",
                "safe_fixes may use finding.suggestion, cited metric/log evidence, or web sources the agent actually fetched.",
                "Label web-based fixes as recommended actions when not confirmed by tier-1 incident evidence.",
                "Do not invent namespaces, queries, hostnames, or fixes beyond cited evidence and fetched web sources.",
                "If evidence is insufficient, say so and request a specific fallback tool call or web search.",
                "Separate confirmed causes from hypotheses and ruled-out causes.",
                "Never report only that a metric changed (e.g. 'tickets dropped'); always explain the MongoDB mechanism "
                "(cache eviction, I/O wait, admission control, replication apply, etc.) in finding_analyses, "
                "incident_timeline, mechanism_summary, and causal_chain.",
                "Mechanism claims must be evidence-backed (metric slice, anomaly window, log, or operator "
                "answer) — never infer from finding name keywords alone.",
                "Prompt examples illustrate format only; they are not evidence and must not be copied verbatim.",
            ],
        }
