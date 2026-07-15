from __future__ import annotations

import re
import uuid
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.simagix.llm.session import Phase2Session
from backend.app.simagix.llm.state import (
    ATTACHMENT_KEY_PREFIX,
    list_attachments,
    load_state,
    save_state,
)

ATTACHMENT_SUBDIR = "attachments"
ALLOWED_SUFFIXES = frozenset({".json", ".txt", ".log", ".md", ".csv", ".yaml", ".yml"})

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    base = Path(name).name.strip() or "attachment"
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return (cleaned[:120] or "attachment")


def _stored_name_from_path(relative_path: str) -> str:
    rel = Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Invalid attachment path")
    if len(rel.parts) != 2 or rel.parts[0] != ATTACHMENT_SUBDIR:
        raise ValueError("Attachments must live under chatbot_scratch/attachments/")
    return rel.parts[1]


def save_chatbot_attachment(
    session: Phase2Session,
    filename: str,
    data: bytes,
) -> dict[str, object]:
    settings = get_settings()
    max_bytes = settings.phase2_chatbot_max_attachment_bytes
    if len(data) > max_bytes:
        raise ValueError(f"Attachment exceeds {max_bytes} bytes")
    if not data:
        raise ValueError("Attachment is empty")

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
        raise ValueError(f"Unsupported file type. Allowed: {allowed}")

    safe = _sanitize_filename(filename)
    stored_name = f"{uuid.uuid4().hex[:8]}_{safe}"
    record = {
        "name": safe,
        "path": f"{ATTACHMENT_SUBDIR}/{stored_name}",
        "size": len(data),
        "content": data.decode("utf-8", errors="replace"),
    }
    save_state(
        session.run_id,
        session.llm,
        f"{ATTACHMENT_KEY_PREFIX}{stored_name}",
        record,
    )
    _write_to_scratch(session, record)
    return {"name": safe, "path": record["path"], "size": record["size"]}


def _write_to_scratch(session: Phase2Session, record: dict) -> Path:
    dest = session.ensure_chatbot_scratch_dir() / ATTACHMENT_SUBDIR
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / Path(str(record["path"])).name
    target.write_text(str(record["content"]), encoding="utf-8")
    return target


def materialize_attachments(session: Phase2Session) -> None:
    """Rebuild the local scratch cache from Postgres so the LLM's read/grep tools
    see every attachment regardless of which pod received the upload."""
    for record in list_attachments(session.run_id, session.llm):
        _write_to_scratch(session, record)


def validate_attachment_refs(
    session: Phase2Session,
    attachments: list[dict[str, object]],
) -> list[dict[str, object]]:
    validated: list[dict[str, object]] = []
    for item in attachments:
        rel = str(item.get("path", "")).strip()
        if not rel:
            raise ValueError("Each attachment must include path")
        stored_name = _stored_name_from_path(rel)
        record = load_state(
            session.run_id, session.llm, f"{ATTACHMENT_KEY_PREFIX}{stored_name}"
        )
        if record is None:
            raise ValueError(f"Attachment not found: {rel}")
        validated.append(
            {
                "name": str(item.get("name") or record["name"]),
                "path": rel,
                "size": int(item.get("size") or record["size"]),
            }
        )
    return validated


def format_user_content_with_attachments(
    content: str,
    attachments: list[dict[str, object]],
) -> str:
    if not attachments:
        return content
    lines = [content, "", "[Attachments saved under chatbot_scratch — use read/grep tools:]"]
    for item in attachments:
        lines.append(f"- {item['name']} → {item['path']}")
    return "\n".join(lines)
