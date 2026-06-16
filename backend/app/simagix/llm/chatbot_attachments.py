from __future__ import annotations

import re
import uuid
from pathlib import Path

from backend.app.core.config import get_settings
from backend.app.simagix.llm.session import Phase2Session

ATTACHMENT_SUBDIR = "attachments"
ALLOWED_SUFFIXES = frozenset({".json", ".txt", ".log", ".md", ".csv", ".yaml", ".yml"})

_SAFE_NAME = re.compile(r"[^a-zA-Z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    base = Path(name).name.strip() or "attachment"
    cleaned = _SAFE_NAME.sub("_", base).strip("._")
    return (cleaned[:120] or "attachment")


def attachment_abs_path(session: Phase2Session, relative_path: str) -> Path:
    scratch = session.ensure_chatbot_scratch_dir().resolve()
    rel = Path(relative_path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError("Invalid attachment path")
    if rel.parts[0] != ATTACHMENT_SUBDIR:
        raise ValueError("Attachments must live under chatbot_scratch/attachments/")
    target = (scratch / rel).resolve()
    if not str(target).startswith(str(scratch)):
        raise ValueError("Invalid attachment path")
    return target


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
    dest_dir = session.ensure_chatbot_scratch_dir() / ATTACHMENT_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex[:8]}_{safe}"
    dest = dest_dir / stored_name
    dest.write_bytes(data)

    return {
        "name": safe,
        "path": f"{ATTACHMENT_SUBDIR}/{stored_name}",
        "size": len(data),
    }


def validate_attachment_refs(
    session: Phase2Session,
    attachments: list[dict[str, object]],
) -> list[dict[str, object]]:
    validated: list[dict[str, object]] = []
    for item in attachments:
        rel = str(item.get("path", "")).strip()
        if not rel:
            raise ValueError("Each attachment must include path")
        target = attachment_abs_path(session, rel)
        if not target.is_file():
            raise ValueError(f"Attachment not found: {rel}")
        validated.append(
            {
                "name": str(item.get("name") or target.name),
                "path": rel,
                "size": int(item.get("size") or target.stat().st_size),
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
