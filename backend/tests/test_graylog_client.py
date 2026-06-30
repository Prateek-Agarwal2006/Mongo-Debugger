from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.simagix.graylog_client import search_absolute
from backend.app.simagix.llm.mcp.servers import graylog as graylog_mcp


def test_search_absolute_normalizes_messages() -> None:
    payload = {
        "messages": [
            {
                "message": {
                    "timestamp": "2026-06-05T10:00:00.000Z",
                    "message": "slow query on orders",
                    "source": "mongod-primary",
                }
            }
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = search_absolute(
            api_url="http://graylog.example",
            api_token="secret",
            query="source:mongod",
            from_iso="2026-06-05T09:00:00.000Z",
            to_iso="2026-06-05T11:00:00.000Z",
            limit=10,
        )

    assert result["configured"] is True
    assert result["message_count"] == 1
    assert result["messages"][0]["message"] == "slow query on orders"


def test_graylog_mcp_unconfigured_returns_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GRAYLOG_API_URL", raising=False)
    monkeypatch.delenv("GRAYLOG_API_TOKEN", raising=False)
    result = graylog_mcp.query_logs_around_window(
        query="error",
        from_iso="2026-06-05T09:00:00.000Z",
        to_iso="2026-06-05T11:00:00.000Z",
    )
    assert result["configured"] is False
    assert result["mock_sample"]


def test_graylog_mcp_configured_calls_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GRAYLOG_API_URL", "http://graylog.example")
    monkeypatch.setenv("GRAYLOG_API_TOKEN", "secret")

    with patch(
        "backend.app.simagix.llm.mcp.servers.graylog.search_absolute",
        return_value={"configured": True, "messages": [], "message_count": 0},
    ) as mock_search:
        result = graylog_mcp.query_logs_around_window(
            query="",
            from_iso="2026-06-05T09:00:00.000Z",
            to_iso="2026-06-05T11:00:00.000Z",
        )

    mock_search.assert_called_once()
    assert result["configured"] is True
