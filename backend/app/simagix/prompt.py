from __future__ import annotations

from typing import Any

from backend.app.simagix.scoring import score_semantics_prompt_lines


def _format_finding_lines(findings: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in findings:
        symptoms = item.get("symptoms", [])
        shown = symptoms[:4]
        extra = len(symptoms) - len(shown)
        symptom_text = "; ".join(shown)
        if extra > 0:
            symptom_text += f" (+{extra} more)"
        description = item.get("description", "")
        suggestion = item.get("suggestion", "")
        block = (
            f"- [{item.get('severity')}] {item.get('name')}\n"
            f"  description: {description}\n"
            f"  symptoms: {symptom_text or 'none'}\n"
            f"  suggestion: {suggestion or 'none'}"
        )
        lines.append(block)
    return lines


def _format_activity_summary(activity: dict[str, Any] | None) -> str:
    if not activity:
        return ""
    keys = (
        "OpsQuery",
        "OpsUpdate",
        "OpsCommand",
        "OpsTotal",
        "ScanKeys",
        "ScanObjects",
        "DocsReturned",
        "CPUIdle",
        "MemResident",
        "CacheUsed",
    )
    parts = [f"{key}={activity[key]}" for key in keys if key in activity]
    if not parts:
        return ""
    return "Activity summary: " + ", ".join(parts)


def build_tier1_evidence_block(context: dict[str, Any]) -> str:
    findings = context.get("findings", [])
    windows = context.get("top_anomaly_windows", [])
    highlights = context.get("assessment_highlights", [])

    finding_lines = _format_finding_lines(findings)
    window_lines = [
        f"- {item.get('metric')} peak={item.get('peak')} severity={item.get('severity')} "
        f"from={item.get('from')} to={item.get('to')}"
        for item in windows[:10]
    ]
    highlight_lines = [
        f"- {item.get('metric')} score={item.get('score')} p95={item.get('p95')}"
        for item in highlights[:10]
    ]

    score_lines = "\n".join(score_semantics_prompt_lines())
    instruction = context.get("instruction", "")
    activity_line = _format_activity_summary(context.get("activity_summary"))

    fallback_note = (
        "Tier-1 findings are empty — you must call fallback retrieval tools for evidence before concluding.\n"
        if not findings
        else "If tier-1 findings are insufficient, call fallback retrieval tools for metric slices or raw paths.\n"
    )

    parts = [
        "You are the MongoDB RCA analyst. Use the analyzed mongo-ftdc report below as primary evidence.\n",
        "Do not rediscover health issues from raw metrics unless you call fallback tools for proof.\n",
        "Cite finding names, anomaly windows, metric slices, or suggestions for every causal claim.\n",
        fallback_note,
    ]
    if instruction:
        parts.append(f"Bundle instruction: {instruction}\n")
    parts.extend(
        [
            "Assessment score legend:\n",
            f"{score_lines}\n\n",
            f"Host: {context.get('host')}\n",
            f"MongoDB: {context.get('mongodb_version')}\n",
            f"Time range: {context.get('time_range')}\n",
        ]
    )
    if activity_line:
        parts.append(f"{activity_line}\n")
    parts.extend(
        [
            "\nFindings:\n",
            "\n\n".join(finding_lines) if finding_lines else "- none",
            "\n\nTop anomaly windows:\n",
            "\n".join(window_lines) if window_lines else "- none",
            "\n\nAssessment highlights:\n",
            "\n".join(highlight_lines) if highlight_lines else "- none",
        ]
    )
    return "".join(parts)


def build_phase2_prompt(context: dict[str, Any]) -> str:
    return (
        build_tier1_evidence_block(context)
        + "\n\nProduce an RCA report matching the RCAReportDraft schema."
    )
