from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.app.simagix.llm.detail_requirements import warn_prompt_example_echo
from pydantic import ValidationError

from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary, RCAReportDraft

logger = logging.getLogger(__name__)


def _find_balanced_json_object(text: str, start: int) -> str | None:
    """Return a {...} slice starting at `start`, respecting strings and nesting."""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _loads_json_object(candidate: str) -> dict[str, Any]:
    payload = json.loads(candidate)
    if not isinstance(payload, dict):
        raise ValueError("Agent JSON must be an object")
    return payload


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("No JSON object found in agent output")

    for fence in re.finditer(r"```(?:json)?\s*", stripped, re.IGNORECASE):
        brace = stripped.find("{", fence.end())
        if brace < 0:
            continue
        candidate = _find_balanced_json_object(stripped, brace)
        if candidate is None:
            continue
        try:
            return _loads_json_object(candidate)
        except json.JSONDecodeError:
            continue

    search_from = 0
    while True:
        brace = stripped.find("{", search_from)
        if brace < 0:
            break
        candidate = _find_balanced_json_object(stripped, brace)
        if candidate is not None:
            try:
                return _loads_json_object(candidate)
            except json.JSONDecodeError:
                pass
        search_from = brace + 1

    raise ValueError("No JSON object found in agent output")




_VALID_EVIDENCE_SOURCE_TYPES = {
    "finding",
    "anomaly",
    "assessment",
    "metric_slice",
    "raw_path",
    "log",
    "operator",
    "web",
}


def _normalize_rca_payload(payload: dict[str, Any], run_id: str) -> dict[str, Any]:
    normalized = dict(payload)
    normalized.setdefault("run_id", run_id)
    if not normalized.get("summary") and normalized.get("root_cause"):
        normalized["summary"] = str(normalized["root_cause"])
    if not normalized.get("root_cause") and normalized.get("summary"):
        normalized["root_cause"] = str(normalized["summary"])

    confidence = normalized.get("confidence")
    if isinstance(confidence, str):
        try:
            normalized["confidence"] = float(confidence)
        except ValueError:
            normalized["confidence"] = None

    citations = normalized.get("evidence_citations")
    if isinstance(citations, list):
        cleaned: list[dict[str, Any]] = []
        for item in citations:
            if not isinstance(item, dict):
                continue
            source_type = item.get("source_type")
            if source_type not in _VALID_EVIDENCE_SOURCE_TYPES:
                continue
            if not item.get("reference") or not item.get("summary"):
                continue
            cleaned.append(item)
        normalized["evidence_citations"] = cleaned

    return normalized


def _lint_prompt_example_echo(report: RCAReportDraft) -> None:
    chunks: list[str] = [
        report.summary,
        report.root_cause,
        report.mechanism_summary or "",
        *report.causal_chain,
    ]
    for analysis in report.finding_analyses:
        chunks.extend([analysis.what_observed, analysis.why_it_happened])
    for event in report.incident_timeline:
        chunks.extend([event.observation, event.mechanism])
    combined = "\n".join(chunks)
    matches = warn_prompt_example_echo(combined)
    if matches:
        logger.warning(
            "RCA text may echo non-authoritative prompt examples: %s",
            ", ".join(matches),
        )


def parse_rca_report(text: str, run_id: str) -> RCAReportDraft:
    payload = _normalize_rca_payload(_extract_json_object(text), run_id)
    try:
        report = RCAReportDraft.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"RCAReportDraft validation failed: {exc}") from exc
    _lint_prompt_example_echo(report)
    return report


def load_persisted_rca_report(raw_json: str, run_id: str) -> RCAReportDraft:
    """Load report JSON from disk; strips legacy fields (e.g. profiler citations)."""
    payload = json.loads(raw_json)
    return RCAReportDraft.model_validate(_normalize_rca_payload(payload, run_id))


def parse_clarifying_questions(
    text: str,
    run_id: str,
    *,
    max_questions: int,
) -> ClarifyingQuestionsBlock:
    payload = _extract_json_object(text)
    if "run_id" not in payload:
        payload["run_id"] = run_id
    questions = list(payload.get("questions") or [])
    if len(questions) > max_questions:
        payload["questions"] = questions[:max_questions]
    return ClarifyingQuestionsBlock.model_validate(payload)


def parse_investigation_summary(text: str, run_id: str) -> InvestigationSummary:
    payload = _extract_json_object(text)
    if "run_id" not in payload:
        payload["run_id"] = run_id
    payload.pop("profiler_insights", None)
    return InvestigationSummary.model_validate(payload)
