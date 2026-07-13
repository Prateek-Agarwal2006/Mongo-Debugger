from __future__ import annotations

import json
from typing import Any


def cursor_run_failure_message(result: Any) -> str:
    """Format a terminal Cursor run failure without summarizing away SDK fields."""
    payload = {
        "status": getattr(result, "status", None),
        "run_id": getattr(result, "id", None),
        "agent_id": getattr(result, "agent_id", None),
        "result": getattr(result, "result", None) or "",
        "duration_ms": getattr(result, "duration_ms", None),
    }
    return json.dumps(payload, indent=2, default=str)


def cursor_parse_failure_message(label: str, raw_text: str) -> str:
    """Return parse failure with full model output appended verbatim."""
    body = raw_text if raw_text else "(empty response)"
    return f"{label}\n\n{body}"
