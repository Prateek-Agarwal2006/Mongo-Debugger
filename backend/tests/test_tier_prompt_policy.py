"""Prompt policy: clear tiers + mandatory tier-3 language (prompt-only, no code gate)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.core.config import Settings
from backend.app.simagix.llm.mcp.specs import McpServerSpec
from backend.app.simagix.llm.prompts import (
    TIER_LIMITS_NOTICE,
    build_investigate_user_message,
    build_runtime_attachments_block,
)


def test_tier_limits_notice_separates_tiers_and_mandates_tier3() -> None:
    text = TIER_LIMITS_NOTICE
    assert "Tier 1 — ANALYZED" in text
    assert "Tier 2 — NORMALIZED" in text
    assert "Tier 3 — RAW" in text
    assert "SUBSET of tier 1" not in text
    assert "No budget cost" not in text
    assert "MUST call list_raw_paths" in text
    assert "get_raw_window" in text
    assert "consume the tool-call budget" in text
    assert "Phase A / investigation with tools" not in text
    assert "whenever tools are attached" in text


def test_phase_a_prompt_requires_tier3_tools() -> None:
    msg = build_investigate_user_message(
        {
            "context": {
                "findings": [],
                "top_anomaly_windows": [],
                "assessment_highlights": [],
                "retrievable_metrics": ["cpu_idle"],
            },
            "available_tools": [
                "get_metric_window",
                "list_raw_paths",
                "get_raw_window",
            ],
        },
        runtime_attachments=(
            "ATTACHED THIS TURN:\n"
            "MCP servers:\n"
            "- simagix-evidence — builtin\n"
            "  tools: get_metric_window, list_raw_paths, get_raw_window\n"
            "Operator skills:\n"
            "- mongo-rca-playbook — playbook\n\n"
        ),
    )
    assert "REQUIRED before output: list_raw_paths + get_raw_window" in msg
    assert "MANDATORY TIER-3" in msg
    assert "ATTACHED THIS TURN" in msg
    assert "mongo-rca-playbook" in msg
    assert "Available MCP tools:" not in msg


def test_runtime_attachments_block_lists_mcp_and_skills(monkeypatch) -> None:
    session = SimpleNamespace(workspace_root="/tmp/ws", run_id="r1")
    settings = MagicMock(spec=Settings)
    package: dict = {
        "available_tools": [
            "get_metric_window",
            "list_raw_paths",
            "get_raw_window",
        ]
    }

    monkeypatch.setattr(
        "backend.app.simagix.llm.prompts.build_mcp_server_specs",
        lambda *_a, **_k: [
            McpServerSpec(server_id="simagix-evidence", transport="stdio", command="python"),
        ],
    )
    monkeypatch.setattr(
        "backend.app.simagix.llm.prompts.list_skill_dirs",
        lambda _root: [{"slot_name": "mongo-rca-playbook", "description": "RCA playbook"}],
    )

    block = build_runtime_attachments_block(
        session,  # type: ignore[arg-type]
        settings,
        package,
        enabled_mcp_ids=None,
        include_tools=True,
    )
    assert "simagix-evidence" in block
    assert "list_raw_paths" in block
    assert "mongo-rca-playbook" in block
    assert "web_fetch" in block
    assert "ATTACHED THIS TURN" in block
