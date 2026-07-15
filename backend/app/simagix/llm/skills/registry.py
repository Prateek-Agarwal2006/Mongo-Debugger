from __future__ import annotations

import io
import json
import logging
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace
from backend.app.db.connection import db_conn

logger = logging.getLogger(__name__)

_SLOT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SKILL_MD_NAMES = ("SKILL.md", "skill.md")
_FRONTMATTER_DESC_RE = re.compile(
    r"^---\s*\n.*?^description:\s*(.+?)\s*$",
    re.MULTILINE | re.DOTALL,
)
_FRONTMATTER_BLOCK_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
_FRONTMATTER_NAME_LINE_RE = re.compile(r"^name:\s*.+\s*$", re.MULTILINE)


def operator_skills_dir(workspace_root: Path) -> Path:
    return RunWorkspace(workspace_root).simagix_root / "operator" / "skills"


def validate_slot_name(slot_name: str) -> str:
    normalized = slot_name.strip()
    if not _SLOT_NAME_RE.match(normalized):
        raise ValueError(
            "Skill slot name must be 1–64 chars: lowercase letters, digits, hyphen, underscore; "
            "must start with a letter or digit."
        )
    return normalized


def _skill_markdown_direct(root: Path) -> Path | None:
    for name in _SKILL_MD_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def _find_skill_markdown(root: Path) -> Path | None:
    direct = _skill_markdown_direct(root)
    if direct is not None:
        return direct
    for path in root.rglob("*"):
        if path.is_file() and path.name in _SKILL_MD_NAMES:
            return path
    return None


def _extract_description_from_content(content: str) -> str | None:
    match = _FRONTMATTER_DESC_RE.search(content)
    if not match:
        return None
    description = match.group(1).strip().strip("\"'")
    return description or None


def _sync_skill_frontmatter_name_content(content: str, slot_name: str) -> str:
    """Return content with `name:` in frontmatter set to slot_name."""
    match = _FRONTMATTER_BLOCK_RE.match(content)
    if match:
        body = match.group(1)
        rest = content[match.end():]
        if _FRONTMATTER_NAME_LINE_RE.search(body):
            body = _FRONTMATTER_NAME_LINE_RE.sub(f"name: {slot_name}", body, count=1)
        else:
            body = f"name: {slot_name}\n{body}"
        return f"---\n{body}\n---{rest}"
    return f"---\nname: {slot_name}\ndescription: Operator skill\n---\n{content}"


def _resolve_extract_root(extract_dir: Path) -> Path:
    if _skill_markdown_direct(extract_dir) is not None:
        return extract_dir
    children = [path for path in extract_dir.iterdir() if path.name != "__MACOSX"]
    dirs = [path for path in children if path.is_dir()]
    files = [path for path in children if path.is_file()]
    if len(dirs) == 1 and not files:
        nested = dirs[0]
        if _find_skill_markdown(nested) is not None:
            return nested
    return extract_dir


def _safe_extract_zip(archive: bytes, dest_dir: Path) -> None:
    dest_resolved = dest_dir.resolve()
    try:
        with zipfile.ZipFile(io.BytesIO(archive), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                member_path = Path(info.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"Unsafe zip entry path: {info.filename}")
                target = (dest_dir / member_path).resolve()
                if not target.is_relative_to(dest_resolved):
                    raise ValueError(f"Zip entry escapes destination: {info.filename}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip archive") from exc


def list_skill_dirs(workspace_root: Path) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT slot_name, description FROM skills ORDER BY slot_name"
        ).fetchall()
    return [{"slot_name": row[0], "description": row[1]} for row in rows]


def upload_skill_zip(workspace_root: Path, slot_name: str, archive: bytes) -> dict[str, Any]:
    normalized = validate_slot_name(slot_name)
    if not archive:
        raise ValueError("Empty zip archive")

    with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
        extract_dir = Path(tmp)
        _safe_extract_zip(archive, extract_dir)
        skill_root = _resolve_extract_root(extract_dir)
        if _find_skill_markdown(skill_root) is None:
            raise ValueError("Zip must contain SKILL.md (or skill.md) somewhere in the package")

        files: dict[str, str] = {}
        for file_path in sorted(skill_root.rglob("*")):
            if file_path.is_dir():
                continue
            rel = str(file_path.relative_to(skill_root))
            files[rel] = file_path.read_text(encoding="utf-8", errors="replace")

    for md_name in _SKILL_MD_NAMES:
        if md_name in files:
            files[md_name] = _sync_skill_frontmatter_name_content(files[md_name], normalized)
            break

    skill_md_content = files.get("SKILL.md") or files.get("skill.md") or ""
    description = _extract_description_from_content(skill_md_content)

    with db_conn() as conn:
        conn.execute(
            "INSERT INTO skills (slot_name, files, description, updated_at)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (slot_name) DO UPDATE SET files = EXCLUDED.files,"
            " description = EXCLUDED.description, updated_at = EXCLUDED.updated_at",
            (normalized, json.dumps(files), description, time.time()),
        )

    return {"slot_name": normalized, "description": description}


def delete_skill(workspace_root: Path, slot_name: str) -> bool:
    normalized = validate_slot_name(slot_name)
    with db_conn() as conn:
        cur = conn.execute(
            "DELETE FROM skills WHERE slot_name = %s", (normalized,)
        )
    return (cur.rowcount or 0) > 0


def copy_all_to_cursor_scratch(workspace_root: Path, scratch_dir: Path) -> None:
    with db_conn() as conn:
        rows = conn.execute("SELECT slot_name, files FROM skills").fetchall()
    if not rows:
        return
    cursor_skills_root = scratch_dir / ".cursor" / "skills"
    cursor_skills_root.mkdir(parents=True, exist_ok=True)
    for slot_name, files_data in rows:
        files: dict[str, str] = files_data if isinstance(files_data, dict) else json.loads(files_data)
        slot_dir = cursor_skills_root / slot_name
        if slot_dir.exists():
            shutil.rmtree(slot_dir)
        slot_dir.mkdir(parents=True)
        for rel_path, content in files.items():
            target = slot_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")


def build_adk_skill_toolset_all(workspace_root: Path) -> Any | None:
    try:
        from google.adk.skills import load_skill_from_dir
        from google.adk.tools.skill_toolset import SkillToolset
    except ImportError:  # pragma: no cover
        logger.warning("google-adk skills unavailable; skipping SkillToolset")
        return None

    with db_conn() as conn:
        rows = conn.execute("SELECT slot_name, files FROM skills").fetchall()
    if not rows:
        return None

    skills_root = operator_skills_dir(workspace_root)
    skills_root.mkdir(parents=True, exist_ok=True)

    loaded: list[Any] = []
    for slot_name, files_data in rows:
        files: dict[str, str] = files_data if isinstance(files_data, dict) else json.loads(files_data)
        slot_dir = skills_root / slot_name
        if slot_dir.exists():
            shutil.rmtree(slot_dir)
        slot_dir.mkdir(parents=True)
        for rel_path, content in files.items():
            target = slot_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        if _find_skill_markdown(slot_dir) is None:
            logger.warning("Skipping skill %s: no SKILL.md found", slot_name)
            continue
        try:
            loaded.append(load_skill_from_dir(slot_dir))
        except Exception:
            logger.exception("Skipping skill %s: ADK load_skill_from_dir failed", slot_name)

    if not loaded:
        return None
    return SkillToolset(skills=loaded)
