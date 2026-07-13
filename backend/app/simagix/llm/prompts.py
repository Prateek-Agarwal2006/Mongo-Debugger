from __future__ import annotations

import json
from typing import Any

from backend.app.simagix.llm.detail_requirements import DETAIL_REQUIREMENTS
from backend.app.simagix.output_schema import InvestigationSummary
from backend.app.simagix.prompt import build_phase2_prompt, build_tier1_evidence_block
from backend.app.simagix.hatchet_summary import build_hatchet_evidence_block

WEB_SEARCH_INVESTIGATION = (
    "When findings reference MongoDB subsystems (replication, WiredTiger, indexes, memory, CPU), "
    "search the web for official documentation and reputable engineering sources that match the symptoms.\n"
    "Call the web_fetch tool for each HTTPS URL before listing it in web_insights.\n"
    "Record each source in web_insights as: '<url> — one-line takeaway'.\n"
    "Prefer official docs; do not treat unsourced forum posts as confirmed incident facts.\n"
)

WEB_SEARCH_FINAL_RCA = (
    "Before writing safe_fixes, search the web for remediation guidance aligned with findings_used and investigation.\n"
    "Call web_fetch for each URL you cite.\n"
    "Add evidence_citations rows with source_type web and reference set to the URL.\n"
    "Also list all fetched URLs in reference_urls for the bibliography.\n"
    "Label web-based fixes as recommendations when not confirmed by tier-1.\n"
)

SCRATCH_RULES = (
    "SCRATCH RULES:\n"
    "- You MAY use read, grep, and shell for analysis.\n"
    "- read/grep: FTDC export bundle, workspace exports, session artifacts, chatbot_scratch/.\n"
    "- shell: create and run scripts ONLY under chatbot_scratch/; print results to stdout.\n"
    "- Do NOT write or edit backend/, simagix-workspace/exports/ (except chatbot_scratch/), "
    "latest_report.json, investigation.json, or git-tracked files.\n"
)

# Phase A: tier-1 is embedded in the prompt — forbid bundle reads so the agent uses simagix-evidence MCP.
INVESTIGATION_SCRATCH_RULES = (
    "SCRATCH RULES (Phase A — investigation):\n"
    "- Tier-2 metric proof MUST use simagix-evidence MCP (get_metric_window, get_normalized_series, "
    "list_fallback_metrics, get_raw_path). Do not skip MCP.\n"
    "- Do NOT read, grep, or glob phase1/, normalized/, diagnosis/, or other export bundle files — "
    "tier-1 context is already in this prompt.\n"
    "- read/grep/shell only under chatbot_scratch/ for transient scratch work.\n"
    "- Do NOT write or edit backend/, simagix-workspace/exports/ (except chatbot_scratch/), "
    "latest_report.json, investigation.json, or git-tracked files.\n"
)


def _hatchet_mcp_guidance(package: dict[str, Any]) -> str:
    tools = package.get("available_tools", [])
    if not any(tool in tools for tool in ("get_hatchet_slow_ops", "get_hatchet_log_examples")):
        return ""
    return (
        "When Hatchet log evidence is present, use hatchet-evidence MCP tools for tier-2 log proof "
        "(get_hatchet_slow_ops, get_hatchet_log_examples, get_hatchet_audit, get_hatchet_connection_timeline). "
        "Cite hatchet_slow_op, hatchet_log_example, hatchet_audit, or hatchet_connection_timeline in evidence.\n"
    )


def _format_retrievable_metrics(metrics: list[str]) -> str:
    if not metrics:
        return ""
    lines = "\n".join(f"- {name}" for name in metrics)
    return (
        f"\n\nRetrievable metrics ({len(metrics)} total — use get_metric_window for slices):\n"
        f"{lines}\n"
        "Assessment highlights above are mongo-ftdc priorities, not the full set.\n"
    )


def _hatchet_evidence_suffix(package: dict[str, Any]) -> str:
    block = package.get("hatchet_evidence_block")
    if not block:
        return ""
    return f"\n\n--- Hatchet log evidence (tier 1) ---\n{block}"


def build_investigate_user_message(package: dict[str, Any]) -> str:
    context = package.get("context", {})
    available_tools = package.get("available_tools", [])
    tools_text = ", ".join(available_tools)
    retrievable_metrics = context.get("retrievable_metrics", [])

    schema = InvestigationSummary.model_json_schema()

    return (
        "You are a MongoDB RCA analyst in INVESTIGATION mode (not final RCA).\n"
        f"{INVESTIGATION_SCRATCH_RULES}"
        "Use simagix-evidence MCP tools for metric slices and logs when available.\n"
        "Tier-1 summarizes mongo-ftdc findings; call MCP (get_metric_window, list_fallback_metrics) "
        "for tier-2 proof on any retrievable metric listed below — do not read normalized JSON from disk.\n"
        "If Graylog MCP is available, query logs around the primary anomaly window.\n"
        f"{_hatchet_mcp_guidance(package)}"
        f"{WEB_SEARCH_INVESTIGATION}"
        f"{DETAIL_REQUIREMENTS}"
        "Do NOT produce a final RCAReportDraft — only an InvestigationSummary.\n"
        "Cite specific metrics, windows, tool results, and web sources in the appropriate fields.\n"
        "finding_analyses and incident_timeline are REQUIRED when tier-1 findings exist.\n\n"
        f"Available MCP tools: {tools_text}\n"
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
        f"{_format_retrievable_metrics(retrievable_metrics)}"
        f"{_hatchet_evidence_suffix(package)}"
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
        "(deployments, maintenance, topology, RAM/cache config, etc.).\n"
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
        f"{_hatchet_evidence_suffix(package)}"
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
        "Tier-1 findings are empty or insufficient. Call simagix-evidence fallback tools when available "
        "(get_metric_window, get_normalized_series, get_raw_path, list_fallback_metrics) "
        "to gather proof before concluding; skip tools not registered on this run.\n"
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
            "log_insights, and web_insights) ---\n"
            f"{json.dumps(inv_payload, indent=2)}\n"
        )

    return (
        "You are a MongoDB RCA analyst operating in READ-ONLY analysis mode.\n"
        f"{SCRATCH_RULES}"
        "Use simagix-evidence MCP tools for supplemental metric retrieval.\n"
        f"{_hatchet_mcp_guidance(package)}"
        "Cite log insights, operator answers, and web sources when relevant.\n"
        "Every causal claim MUST cite evidence (finding, anomaly window, metric slice, log, operator, or web).\n"
        f"{DETAIL_REQUIREMENTS}"
        f"{fallback_guidance}\n"
        f"{WEB_SEARCH_FINAL_RCA}\n"
        f"Available MCP tools: {tools_text}\n\n"
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
        f"{_hatchet_evidence_suffix(package)}"
    )


def build_chatbot_summarize_prompt(
    messages_to_fold: list[dict[str, str]],
    *,
    prior_summary: str | None = None,
) -> str:
    lines: list[str] = []
    if prior_summary:
        lines.append(f"Prior summary:\n{prior_summary}\n")
    lines.append("Messages to compress:\n")
    for msg in messages_to_fold:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return (
        "Compress the chat history below into short factual prose. "
        "Keep topics asked, conclusions, and open questions. "
        "Do not use tools. Reply with plain text only.\n\n"
        + "\n".join(lines)
    )


def build_chatbot_prompt(
    *,
    report: dict[str, Any],
    investigation: dict[str, Any] | None,
    summary_of_older: str | None,
    recent_messages: list[dict[str, str]],
    user_message: str,
    scratch_dir: str,
) -> str:
    inv_block = ""
    if investigation:
        inv_block = (
            "\n--- Investigation summary ---\n"
            f"{json.dumps(investigation, indent=2)}\n"
        )
    summary_block = ""
    if summary_of_older:
        summary_block = (
            "\n--- Earlier conversation summary ---\n"
            f"{summary_of_older}\n"
        )
    history_lines: list[str] = []
    for msg in recent_messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        history_lines.append(f"{role}: {content}")
    history_block = ""
    if history_lines:
        history_block = "\n--- Recent chat ---\n" + "\n".join(history_lines) + "\n"

    return (
        "You are a MongoDB RCA chatbot helping an operator after the final report.\n"
        f"{SCRATCH_RULES}"
        f"Scratch directory: {scratch_dir}\n"
        "Use simagix-evidence MCP tools, web_fetch, read/grep/shell when needed to answer.\n"
        "Reply in clear markdown. Do NOT output RCA JSON schemas.\n"
        "Ground answers in the report and investigation; cite evidence when making claims.\n\n"
        "--- Latest RCA report ---\n"
        f"{json.dumps(report, indent=2)}\n"
        f"{inv_block}"
        f"{summary_block}"
        f"{history_block}"
        f"\nuser: {user_message}\n"
    )
