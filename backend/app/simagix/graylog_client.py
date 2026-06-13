from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _auth_header(token: str, auth_mode: str) -> dict[str, str]:
    mode = auth_mode.lower()
    if mode == "basic":
        encoded = base64.b64encode(f"{token}:token".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {encoded}"}
    return {"Authorization": f"Bearer {token}"}


def search_absolute(
    *,
    api_url: str,
    api_token: str,
    query: str,
    from_iso: str,
    to_iso: str,
    limit: int = 50,
    auth_mode: str = "token",
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Query Graylog Universal Search absolute time range API."""
    base = api_url.rstrip("/")
    params = urllib.parse.urlencode(
        {
            "query": query,
            "from": from_iso,
            "to": to_iso,
            "limit": str(limit),
        }
    )
    url = f"{base}/api/search/universal/absolute?{params}"
    request = urllib.request.Request(
        url,
        headers={
            **_auth_header(api_token, auth_mode),
            "Accept": "application/json",
            "X-Requested-By": "mongo-debugger",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Graylog HTTP {exc.code}: {body[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Graylog request failed: {exc.reason}") from exc

    messages = _normalize_messages(payload)
    return {
        "configured": True,
        "query": query,
        "from": from_iso,
        "to": to_iso,
        "limit": limit,
        "message_count": len(messages),
        "messages": messages,
    }


def _normalize_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    raw_messages = payload.get("messages") or []
    for entry in raw_messages:
        if not isinstance(entry, dict):
            continue
        message = entry.get("message") if isinstance(entry.get("message"), dict) else entry
        if not isinstance(message, dict):
            continue
        messages.append(
            {
                "timestamp": message.get("timestamp") or message.get("gl2_processing_timestamp"),
                "message": message.get("message") or message.get("full_message") or "",
                "source": message.get("source") or message.get("gl2_source_node"),
                "fields": {
                    k: v
                    for k, v in message.items()
                    if k not in {"timestamp", "message", "full_message", "source", "gl2_source_node"}
                },
            }
        )
    return messages
