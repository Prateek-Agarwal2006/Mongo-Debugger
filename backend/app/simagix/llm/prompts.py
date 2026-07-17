from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.simagix.evidence.hatchet_tools import HATCHET_MCP_TOOL_NAMES
from backend.app.simagix.evidence_block import build_phase2_prompt, build_tier1_evidence_block
from backend.app.simagix.llm.detail_requirements import DETAIL_REQUIREMENTS
from backend.app.simagix.llm.mcp.connectors import McpConnectorRegistry
from backend.app.simagix.llm.mcp.registry import build_mcp_server_specs
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.skills.registry import list_skill_dirs
from backend.app.simagix.output_schema import InvestigationSummary

_SIMAGIX_EVIDENCE_TOOLS = (
    "get_metric_window",
    "get_normalized_series",
    "list_fallback_metrics",
    "list_raw_paths",
    "get_raw_window",
    "execute_plot_script",
    "get_budget_status",
)
_GRAYLOG_TOOLS = ("query_logs_around_window",)

# Skill slots that, when uploaded, the agent must treat as binding playbooks
# (enforced via a hard clause in the runtime attachments block).
MANDATORY_SKILLS = ("metric-plotter",)

TIER_LIMITS_NOTICE = (
    "EVIDENCE TIERS (do not confuse these):\n"
    "- Tier 1 — ANALYZED (already in this prompt): findings, anomaly windows, assessment "
    "highlights. What/when from mongo-ftdc. Not the full FTDC path catalog.\n"
    "- Tier 2 — NORMALIZED slices via MCP: get_metric_window, get_normalized_series, "
    "list_fallback_metrics. Same curated ~89 playbook metrics as time series for proof — "
    "NOT a second opinionated diagnosis layer, and NOT raw FTDC.\n"
    "- Tier 3 — RAW FTDC (~thousands of paths/sec: per-command counters, locks, WiredTiger, "
    "repl internals, etc.): list_raw_paths → get_raw_window. This is where mechanism lives.\n"
    "MANDATORY TIER-3 (whenever tools are attached — investigation, final RCA, chatbot):\n"
    "- You MUST call list_raw_paths (browse taxonomy and/or pattern) AND at least one "
    "get_raw_window on paths relevant to the top anomaly / findings BEFORE claiming "
    "mechanism (InvestigationSummary why/how, RCA attribution, or chatbot mechanism answers).\n"
    "- Do NOT finish on tier 1+2 alone. Detection can start from tier 1; attribution "
    "('why/how', which command/namespace/lock/sync-source) REQUIRES tier-3 tool results "
    "cited in metric_insights, finding_analyses, or the reply.\n"
    "- list_raw_paths and get_raw_window consume the tool-call budget (list_fallback_metrics "
    "does not).\n"
)


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
    "- Tier-2 proof: simagix-evidence MCP (get_metric_window, get_normalized_series, "
    "list_fallback_metrics).\n"
    "- Tier-3 proof (MANDATORY): list_raw_paths then get_raw_window — do not skip.\n"
    "- Do NOT read, grep, or glob phase1/, normalized/, diagnosis/, or other export bundle files — "
    "tier-1 context is already in this prompt; use MCP for tier 2/3.\n"
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


def _tools_line_for_server(server_id: str) -> str:
    if server_id == "simagix-evidence":
        return ", ".join(_SIMAGIX_EVIDENCE_TOOLS)
    if server_id in {"graylog", "graylog-logs"}:
        return ", ".join(_GRAYLOG_TOOLS)
    if server_id == "hatchet-evidence":
        return ", ".join(sorted(HATCHET_MCP_TOOL_NAMES))
    return "(tool names discovered when the server connects)"


def build_runtime_attachments_block(
    session: Phase2Session,
    settings: Settings,
    package: dict[str, Any],
    *,
    enabled_mcp_ids: list[str] | None = None,
    include_tools: bool = True,
) -> str:
    """List MCP servers + skills actually attached this turn (known at runtime)."""
    if not include_tools:
        return (
            "ATTACHED THIS TURN: none — text-only phase (no MCP servers, no skills, no web_fetch).\n"
        )

    # Inventory is best-effort: an unknown WorkArea connector id must not fail
    # the run/chatbot request here — the provider's MCP wiring is the authority.
    try:
        specs = build_mcp_server_specs(
            session,
            settings,
            enabled_mcp_ids=enabled_mcp_ids,
        )
    except ValueError:
        specs = build_mcp_server_specs(session, settings, enabled_mcp_ids=None)
    connector_meta: dict[str, Any] = {}
    if enabled_mcp_ids:
        registry = McpConnectorRegistry(session.workspace_root)
        try:
            for record in registry.resolve_enabled(enabled_mcp_ids):
                connector_meta[record.id] = record
        except ValueError:
            pass

    lines = [
        "ATTACHED THIS TURN (runtime inventory — only these MCP servers/skills are wired; "
        "do not invent others):\n",
        "MCP servers:\n",
    ]
    if not specs:
        lines.append("- (none)\n")
    for spec in specs:
        record = connector_meta.get(spec.server_id)
        if record is not None:
            label = f"{record.name} [{spec.server_id}]"
            detail = record.description or f"WorkArea {spec.transport}"
        else:
            label = spec.server_id
            detail = f"builtin ({spec.transport})"
        tools = _tools_line_for_server(spec.server_id)
        lines.append(f"- {label} — {detail}\n  tools: {tools}\n")

    lines.append("- web_fetch — app HTTPS fetch tool (not an MCP server); use when prompts ask for docs\n")

    skills = list_skill_dirs(Path(session.workspace_root))
    lines.append("\nOperator skills (all slots attached automatically):\n")
    if not skills:
        lines.append("- (none uploaded)\n")
    else:
        for skill in skills:
            slot = skill.get("slot_name", "?")
            desc = (skill.get("description") or "").strip() or "operator skill"
            lines.append(f"- {slot} — {desc}\n")

    attached_slots = {skill.get("slot_name") for skill in skills}
    for slot in MANDATORY_SKILLS:
        if slot in attached_slots:
            lines.append(
                f"\nMANDATORY SKILL: '{slot}' is not optional reference material. "
                f"Read its SKILL.md before starting and follow its playbook exactly — "
                f"output that skips its required steps is invalid and will be rejected.\n"
            )

    lines.append(
        "\nUse only servers/skills listed above. WorkArea MCP checkboxes change this list per run.\n\n"
    )
    return "".join(lines)


def build_investigate_user_message(
    package: dict[str, Any],
    *,
    runtime_attachments: str = "",
) -> str:
    context = package.get("context", {})
    retrievable_metrics = context.get("retrievable_metrics", [])

    schema = InvestigationSummary.model_json_schema()
    attachments = runtime_attachments or (
        "ATTACHED THIS TURN: (inventory not provided — use simagix-evidence MCP if available)\n\n"
    )

    return (
        "You are a MongoDB RCA analyst in INVESTIGATION mode (not final RCA).\n"
        f"{INVESTIGATION_SCRATCH_RULES}"
        f"{TIER_LIMITS_NOTICE}"
        "Use simagix-evidence MCP for tier-2 slices and mandatory tier-3 raw windows.\n"
        "Tier-1 in this prompt is analyzed findings only. Call get_metric_window / "
        "list_fallback_metrics for tier-2 proof on retrievable metrics below — do not read "
        "normalized JSON from disk.\n"
        "REQUIRED before output: list_raw_paths + get_raw_window for mechanism paths tied to "
        "top anomalies (command / namespace / lock / sync-source / WiredTiger / repl internals). "
        "Record those calls in tool_calls_made and cite values in metric_insights.\n"
        "If a Graylog MCP server is listed below, query logs around the primary anomaly window.\n"
        f"{_hatchet_mcp_guidance(package)}"
        f"{WEB_SEARCH_INVESTIGATION}"
        f"{DETAIL_REQUIREMENTS}"
        "Do NOT produce a final RCAReportDraft — only an InvestigationSummary.\n"
        "Cite specific metrics, windows, tool results, and web sources in the appropriate fields.\n"
        "finding_analyses and incident_timeline are REQUIRED when tier-1 findings exist.\n\n"
        f"{attachments}"
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
    runtime_attachments: str = "",
) -> str:
    context = package.get("context", {})
    findings = context.get("findings", [])
    grounding_rules = package.get("grounding_rules", {})
    output_schema = package.get("output_schema", {})

    tier1_insufficient = len(findings) == 0
    fallback_guidance = (
        "Tier-1 findings are empty or insufficient. Call simagix-evidence fallback tools when available "
        "(get_metric_window, get_normalized_series, list_fallback_metrics, "
        "list_raw_paths, get_raw_window) "
        "to gather proof before concluding; skip tools not listed in ATTACHED THIS TURN.\n"
        if tier1_insufficient
        else (
            "Build on the investigation summary below. Call simagix-evidence tools only "
            "if additional proof is still required beyond the investigation."
        )
    )

    rules_text = json.dumps(grounding_rules, indent=2)
    schema_text = json.dumps(output_schema, indent=2)
    attachments = runtime_attachments or (
        "ATTACHED THIS TURN: (inventory not provided — use simagix-evidence MCP if available)\n\n"
    )

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
        f"{TIER_LIMITS_NOTICE}"
        "Use simagix-evidence MCP tools for supplemental metric retrieval.\n"
        f"{_hatchet_mcp_guidance(package)}"
        "Cite log insights, operator answers, and web sources when relevant.\n"
        "Every causal claim MUST cite evidence (finding, anomaly window, metric slice, log, operator, or web).\n"
        "For root-cause attribution (which command / namespace / lock / sync-source), you MUST use "
        "tier-3 (list_raw_paths → get_raw_window) — do not conclude from tier 1 findings or tier 2 "
        "curated slices alone. A tier-1/2-only attribution is a red flag.\n"
        f"{DETAIL_REQUIREMENTS}"
        f"{fallback_guidance}\n"
        f"{WEB_SEARCH_FINAL_RCA}\n"
        f"{attachments}"
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
    runtime_attachments: str = "",
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
    attachments = runtime_attachments or (
        "ATTACHED THIS TURN: (inventory not provided — use simagix-evidence MCP if available)\n\n"
    )

    return (
        "You are a MongoDB RCA chatbot helping an operator after the final report.\n"
        f"{SCRATCH_RULES}"
        f"{TIER_LIMITS_NOTICE}"
        f"Scratch directory: {scratch_dir}\n"
        "Use attached MCP tools, web_fetch, read/grep/shell when needed to answer.\n"
        "When the operator asks which command / namespace / lock / oplog mechanism drove an "
        "anomaly, you MUST use tier 3 (list_raw_paths → get_raw_window) — the report may only "
        "have tier 1/2 and that is not enough for mechanism.\n"
        "Reply in clear markdown. Do NOT output RCA JSON schemas.\n"
        "Ground answers in the report and investigation; cite evidence when making claims.\n\n"
        f"{attachments}"
        "--- Latest RCA report ---\n"
        f"{json.dumps(report, indent=2)}\n"
        f"{inv_block}"
        f"{summary_block}"
        f"{history_block}"
        f"\nuser: {user_message}\n"
    )
