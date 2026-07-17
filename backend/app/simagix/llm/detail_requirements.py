"""Shared prompt text for mechanistic RCA: format, illustrative examples, evidence rules."""

MOCK_WHY_STUB = (
    "[mock] Not inferred — live agent must derive mechanism from metric/log tool results."
)

MOCK_MECHANISM_STUB = "[mock] pending evidence-backed analysis"

FORMAT_REQUIREMENTS = (
    "FORMAT REQUIREMENTS:\n"
    "- Populate finding_analyses (one row per tier-1 finding reviewed) and incident_timeline "
    "(chronological observation + mechanism per anomaly window).\n"
    "- Include mechanism_summary on final RCA.\n"
    "- summary and root_cause must be multi-sentence narratives, not one-liners.\n"
    "- causal_chain steps must use 'because' / 'which caused' language linking mechanism to effect.\n"
    "- Charts: when execute_plot_script returns a chart_id, set it on that finding's chart_id "
    "field AND append a matching entry to the report's charts array "
    "(chart_id, metric_paths, time_window, caption, finding_name). Never invent chart_id values — "
    "only use ids returned by the tool.\n"
)

EXAMPLES = (
    "EXAMPLES (non-authoritative — format illustration only):\n"
    "- Illustrates desired depth and format only — do not copy wording or infer causes "
    "without tool evidence for this run.\n"
    "- Bad: '<metric> dropped during the window.'\n"
    "- Good: '<metric_A> rose because <prior cause from tool output>, which caused <effect>; "
    "cite <metric_B>@<timestamp> from MCP or tier-1 evidence.'\n"
)

# Phrases from older illustrative examples; warn if echoed verbatim in agent output.
EXAMPLE_PHRASE_MARKERS = (
    "exhausting read tickets",
    "stalled engine threads",
)


def warn_prompt_example_echo(text: str) -> list[str]:
    """Return marker phrases found verbatim in text (case-insensitive)."""
    lowered = text.lower()
    return [phrase for phrase in EXAMPLE_PHRASE_MARKERS if phrase in lowered]

EVIDENCE_RULES = (
    "EVIDENCE RULES (binding):\n"
    "- Every why_it_happened and incident_timeline mechanism must cite at least one of: "
    "metric_insights value (prefer tier-3 get_raw_window), anomaly window, log slice, or "
    "operator answer.\n"
    "- Investigation with tools: MUST include list_raw_paths and get_raw_window results before "
    "claiming mechanism; tier 1+2 alone is insufficient for why/how.\n"
    "- Forbidden: inferring mechanism from finding name keywords alone "
    "(e.g. seeing 'RAM' and asserting cache eviction without metric proof).\n"
    "- Forbidden: copying prompt examples verbatim into output.\n"
    "- If tools were not called for a claim, state insufficient evidence and list the required "
    "tool call in open_questions_for_operator or ruled_out_hypotheses.\n"
    "- Also call tier-2 fallback slices (ticket_avail_read, ticket_avail_write, cache_used, "
    "cpu_iowait, latency_read, repl_lag_*) around top_anomaly_windows when needed for proof.\n"
)

DETAIL_REQUIREMENTS = (
    f"{FORMAT_REQUIREMENTS}\n"
    f"{EXAMPLES}\n"
    f"{EVIDENCE_RULES}"
)
