from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.app.simagix.llm.detail_requirements import warn_prompt_example_echo
from backend.app.simagix.output_schema import ClarifyingQuestionsBlock, InvestigationSummary, RCAReportDraft

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> dict[str, Any]:
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence_match:
        return json.loads(fence_match.group(1))

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])

    raise ValueError("No JSON object found in agent output")


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
    payload = _extract_json_object(text)
    if "run_id" not in payload:
        payload["run_id"] = run_id
    report = RCAReportDraft.model_validate(payload)
    _lint_prompt_example_echo(report)
    return report


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
    return InvestigationSummary.model_validate(payload)
