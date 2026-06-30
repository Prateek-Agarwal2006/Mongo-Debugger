from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

McpServerTransport = Literal["stdio", "http"]

# FastMCP server names that expose unique tool names — keep bare names for ADK trace parity.
BARE_TOOL_MCP_SERVER_NAMES = frozenset(
    {
        "simagix-evidence",
        "hatchet-evidence",
        "graylog-logs",
        "graylog",
    }
)


@dataclass(frozen=True)
class McpServerSpec:
    """Provider-neutral MCP server attachment (Cursor SDK or ADK MCP client)."""

    server_id: str
    transport: McpServerTransport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
