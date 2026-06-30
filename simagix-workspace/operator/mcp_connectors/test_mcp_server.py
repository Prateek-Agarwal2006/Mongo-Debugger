"""Minimal stdio MCP server for testing operator MCP connector wiring.

Run from repo root:
  uv run python simagix-workspace/operator/mcp_connectors/test_mcp_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("test-ping-mcp")


@mcp.tool()
def test_ping(message: str = "hello") -> dict[str, object]:
    """Return pong — use to verify MCP stdio wiring from Phase 2 / MCP WorkArea."""
    return {"ok": True, "pong": message}


@mcp.tool()
def test_echo(text: str) -> dict[str, str]:
    """Echo text back unchanged."""
    return {"echo": text}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
