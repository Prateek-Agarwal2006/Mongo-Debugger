from __future__ import annotations

import json
from typing import Any

from backend.app.simagix.llm.detail_requirements import DETAIL_REQUIREMENTS
from backend.app.simagix.output_schema import InvestigationSummary
from backend.app.simagix.prompt import build_phase2_prompt, build_tier1_evidence_block

WEB_SEARCH_INVESTIGATION = (
    "When findings reference MongoDB subsystems (replication, WiredTiger, indexes, memory, CPU), "
    "search the web for official MongoDB documentation and reputable engineering sources that match the symptoms.\n"
    "Record each source in web_insights as: '<url> — one-line takeaway'.\n"
    "Prefer mongodb.com/docs; do not treat unsourced forum posts as confirmed incident facts.\n"
)

WEB_SEARCH_FINAL_RCA = (
    "Before writing safe_fixes, search the web for remediation guidance aligned with findings_used and investigation.\n"
    "Add evidence_citations rows with source_type web and reference set to the URL.\n"
    "Also list all fetched URLs in reference_urls for the bibliography.\n"
    "Prefer mongodb.com/docs; label web-based fixes as recommendations when not confirmed by tier-1.\n"
)


def build_investigate_user_message(package: dict[str, Any]) -> str:
    context = package.get("context", {})
    available_tools = package.get("available_tools", [])
    tools_text = ", ".join(available_tools)

    schema = InvestigationSummary.model_json_schema()

    return (
        "You are a MongoDB RCA analyst in INVESTIGATION mode (not final RCA).\n"
        "Do NOT edit, create, or delete any files. Do NOT run shell commands.\n"
        "Do NOT use read, grep, or local file tools — use simagix-evidence MCP tools ONLY "
        "for metric slices, profiler samples, and logs.\n"
        "Tier-1 context in this prompt is sufficient for findings; call MCP for tier-2 proof.\n"
        "Use simagix-evidence MCP tools to gather tier-2 proof for tier-1 findings.\n"
        "You MUST call get_profiler_samples to check for uploaded db.system.profile data.\n"
        "If Graylog MCP is available, query logs around the primary anomaly window.\n"
        f"{WEB_SEARCH_INVESTIGATION}"
        f"{DETAIL_REQUIREMENTS}"
        "Do NOT produce a final RCAReportDraft — only an InvestigationSummary.\n"
        "Cite specific metrics, windows, tool results, and web sources in the appropriate fields.\n"
        "finding_analyses and incident_timeline are REQUIRED when tier-1 findings exist.\n\n"
        f"Available MCP tools: {tools_text}, get_budget_status, get_profiler_samples\n"
        "Optional: graylog query_logs_around_window when Graylog is configured.\n\n"
        "Output requirements:\n"
        "- Respond with a single JSON object matching InvestigationSummary.\n"
        "- Wrap the JSON in a ```json fenced code block.\n"
        "- Do not include prose outside the JSON fence.\n\n"
        "InvestigationSummary JSON schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Output InvestigationSummary only.\n\n"
        "--- Tier-1 analyzed evidence ---\n"
        f"{build_tier1_evidence_block(context)}"
    )


def build_clarify_user_message(
    package: dict[str, Any],
    *,
    max_questions: int,
    investigation: InvestigationSummary | dict[str, Any] | None = None,
) -> str:
    context = package.get("context", {})
    schema = {
        "run_id": "string",
        "context_summary": "one-line summary of what you need from the operator",
        "questions": [
            {
                "id": "snake_case_identifier",
                "question": "specific question for the operator",
                "rationale": "why tier-1 + investigation evidence is still insufficient",
            }
        ],
    }

    investigation_block = ""
    if investigation:
        inv_payload = (
            investigation.model_dump() if isinstance(investigation, InvestigationSummary) else investigation
        )
        investigation_block = (
            "\n--- Tier-2 investigation summary (already gathered; do not re-ask what tools proved) ---\n"
            f"{json.dumps(inv_payload, indent=2)}\n"
        )

    return (
        "You are a MongoDB RCA analyst preparing clarifying questions for a human operator.\n"
        "You have tier-1 FTDC analysis AND a completed tier-2 investigation summary below.\n"
        "No MCP tools — do not request metric slices the investigation already retrieved.\n"
        "Ask ONLY for operational context that metrics and logs cannot answer "
        "(deployments, maintenance, topology, RAM/cache config, profiler upload if unavailable, etc.).\n"
        f"Return at most {max_questions} questions. If investigation is sufficient, return questions: [].\n"
        "Prefer questions from open_questions_for_operator when still unresolved.\n"
        "Use stable snake_case ids (e.g. repl_maintenance, wt_cache_sizing).\n\n"
        "Output requirements:\n"
        "- Respond with a single JSON object and nothing else.\n"
        "- Wrap the JSON in a ```json fenced code block.\n"
        "- Do not include prose outside the JSON fence.\n\n"
        "ClarifyingQuestionsBlock JSON schema:\n"
        f"{json.dumps(schema, indent=2)}\n\n"
        "Output ClarifyingQuestionsBlock only.\n\n"
        f"{investigation_block}"
        "--- Tier-1 analyzed evidence ---\n"
        f"{build_tier1_evidence_block(context)}"
    )


def build_phase2_user_message(
    package: dict[str, Any],
    *,
    user_answers: dict[str, str] | None = None,
    investigation: InvestigationSummary | dict[str, Any] | None = None,
) -> str:
    context = package.get("context", {})
    findings = context.get("findings", [])
    grounding_rules = package.get("grounding_rules", {})
    output_schema = package.get("output_schema", {})
    available_tools = package.get("available_tools", [])

    tier1_insufficient = len(findings) == 0
    fallback_guidance = (
        "Tier-1 findings are empty or insufficient. You MUST call the simagix-evidence "
        "fallback tools (get_metric_window, get_normalized_series, get_raw_path, "
        "list_fallback_metrics, get_profiler_samples) to gather proof before concluding."
        if tier1_insufficient
        else (
            "Build on the investigation summary below. Call simagix-evidence tools only "
            "if additional proof is still required beyond the investigation."
        )
    )

    rules_text = json.dumps(grounding_rules, indent=2)
    schema_text = json.dumps(output_schema, indent=2)
    tools_text = ", ".join(available_tools)

    user_context_block = ""
    if user_answers:
        answer_lines = "\n".join(f"- {qid}: {answer}" for qid, answer in user_answers.items() if answer.strip())
        if answer_lines:
            user_context_block = (
                "\n--- Operator clarifications (incorporate into RCA; cite when used) ---\n"
                f"{answer_lines}\n"
            )

    investigation_block = ""
    if investigation:
        inv_payload = (
            investigation.model_dump() if isinstance(investigation, InvestigationSummary) else investigation
        )
        investigation_block = (
            "\n--- Prior tier-2 investigation (use as evidence; cite metric_insights, "
            "profiler_insights, log_insights, and web_insights) ---\n"
            f"{json.dumps(inv_payload, indent=2)}\n"
        )

    return (
        "You are a MongoDB RCA analyst operating in READ-ONLY analysis mode.\n"
        "Do NOT edit, create, or delete any files. Do NOT run shell commands.\n"
        "Do NOT use read, grep, or local file tools — use simagix-evidence MCP tools ONLY "
        "for supplemental metric/profiler retrieval.\n"
        "Cite profiler samples, log insights, operator answers, and web sources when relevant.\n"
        "Every causal claim MUST cite evidence (finding, anomaly window, metric slice, profiler, log, operator, or web).\n"
        f"{DETAIL_REQUIREMENTS}"
        f"{fallback_guidance}\n"
        f"{WEB_SEARCH_FINAL_RCA}\n"
        f"Available MCP tools: {tools_text}, get_budget_status, get_profiler_samples\n\n"
        "Grounding rules:\n"
        f"{rules_text}\n\n"
        "Output requirements:\n"
        "- Respond with a single JSON object matching RCAReportDraft schema and nothing else.\n"
        "- Wrap the JSON in a ```json fenced code block.\n"
        "- Do not include prose outside the JSON fence.\n\n"
        "RCAReportDraft JSON schema:\n"
        f"{schema_text}\n\n"
        "Output RCAReportDraft only.\n\n"
        f"{investigation_block}"
        f"{user_context_block}"
        "--- Tier-1 analyzed evidence ---\n"
        f"{build_phase2_prompt(context)}"
    )
