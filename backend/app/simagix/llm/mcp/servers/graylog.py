from __future__ import annotations

import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from backend.app.simagix.graylog_client import search_absolute

mcp = FastMCP("graylog-logs")


def _configured() -> bool:
    return bool(os.environ.get("GRAYLOG_API_URL") and os.environ.get("GRAYLOG_API_TOKEN"))


@mcp.tool()
def query_logs_around_window(
    query: str,
    from_iso: str,
    to_iso: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Query application logs around an anomaly window (requires GRAYLOG_API_URL + GRAYLOG_API_TOKEN)."""
    if not _configured():
        return {
            "configured": False,
            "messages": [],
            "note": "Graylog is not configured. Set GRAYLOG_API_URL and GRAYLOG_API_TOKEN to enable live log retrieval.",
            "mock_sample": [
                {
                    "timestamp": from_iso,
                    "message": "slow query: COLLSCAN on orders collection (mock — configure Graylog for live data)",
                    "source": "app-mongodb-logs",
                }
            ],
        }

    api_url = os.environ["GRAYLOG_API_URL"]
    api_token = os.environ["GRAYLOG_API_TOKEN"]
    auth_mode = os.environ.get("GRAYLOG_AUTH_MODE", "token")
    default_query = os.environ.get("GRAYLOG_DEFAULT_QUERY", "source:mongod OR mongodb OR mongo")
    search_limit = int(os.environ.get("GRAYLOG_SEARCH_LIMIT", str(limit)))
    effective_query = query.strip() or default_query
    effective_limit = min(limit, search_limit)

    try:
        return search_absolute(
            api_url=api_url,
            api_token=api_token,
            query=effective_query,
            from_iso=from_iso,
            to_iso=to_iso,
            limit=effective_limit,
            auth_mode=auth_mode,
        )
    except RuntimeError as exc:
        return {
            "configured": True,
            "query": effective_query,
            "from": from_iso,
            "to": to_iso,
            "limit": effective_limit,
            "messages": [],
            "error": str(exc),
        }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
