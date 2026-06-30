"""Local Streamable HTTP MCP for testing operator HTTP connectors.

From repo root:

  uv run python simagix-workspace/operator/mcp_connectors/test_mcp_http_server.py

Listens on http://127.0.0.1:8765/mcp (tools: test_ping, test_echo).

Optional: TEST_MCP_HTTP_PORT (default 8765). Auth is not enforced on this
test server — fill Authorization in registry.json only if your client sends it.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

_DEFAULT_PORT = 8765

mcp = FastMCP(
    "test-http-mcp",
    host="127.0.0.1",
    port=int(os.environ.get("TEST_MCP_HTTP_PORT", str(_DEFAULT_PORT))),
    stateless_http=True,
)


@mcp.tool()
def test_ping(message: str = "hello") -> dict[str, object]:
    """Return pong — verify Streamable HTTP MCP wiring from Phase 2."""
    return {"ok": True, "pong": message, "transport": "streamable-http"}


@mcp.tool()
def test_echo(text: str) -> dict[str, str]:
    """Echo text back unchanged."""
    return {"echo": text}


def main() -> None:
    port = mcp.settings.port
    print(f"Test HTTP MCP listening on http://127.0.0.1:{port}/mcp")
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
