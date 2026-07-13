from __future__ import annotations

import io
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from backend.app.core.run_workspace import RunWorkspace

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


def _read_description_best_effort(skill_root: Path) -> str | None:
    skill_md = _find_skill_markdown(skill_root)
    if skill_md is None:
        return None
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _FRONTMATTER_DESC_RE.search(text)
    if not match:
        return None
    description = match.group(1).strip().strip("\"'")
    return description or None


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


def _sync_skill_frontmatter_name(slot_dir: Path, slot_name: str) -> None:
    """ADK/Cursor require SKILL.md `name:` to match the slot directory name."""
    skill_md = _find_skill_markdown(slot_dir)
    if skill_md is None:
        return
    text = skill_md.read_text(encoding="utf-8")
    match = _FRONTMATTER_BLOCK_RE.match(text)
    if match:
        body = match.group(1)
        rest = text[match.end() :]
        if _FRONTMATTER_NAME_LINE_RE.search(body):
            body = _FRONTMATTER_NAME_LINE_RE.sub(f"name: {slot_name}", body, count=1)
        else:
            body = f"name: {slot_name}\n{body}"
        text = f"---\n{body}\n---{rest}"
    else:
        text = f"---\nname: {slot_name}\ndescription: Operator skill\n---\n{text}"
    skill_md.write_text(text, encoding="utf-8")


def list_skill_dirs(workspace_root: Path) -> list[dict[str, Any]]:
    root = operator_skills_dir(workspace_root)
    if not root.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        items.append(
            {
                "slot_name": entry.name,
                "description": _read_description_best_effort(entry),
            }
        )
    return items


def upload_skill_zip(workspace_root: Path, slot_name: str, archive: bytes) -> dict[str, Any]:
    normalized = validate_slot_name(slot_name)
    if not archive:
        raise ValueError("Empty zip archive")

    skills_root = operator_skills_dir(workspace_root)
    skills_root.mkdir(parents=True, exist_ok=True)
    slot_dir = skills_root / normalized

    with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
        extract_dir = Path(tmp)
        _safe_extract_zip(archive, extract_dir)
        skill_root = _resolve_extract_root(extract_dir)
        if _find_skill_markdown(skill_root) is None:
            raise ValueError("Zip must contain SKILL.md (or skill.md) somewhere in the package")

        if slot_dir.exists():
            shutil.rmtree(slot_dir)
        shutil.copytree(skill_root, slot_dir)

    _sync_skill_frontmatter_name(slot_dir, normalized)

    return {
        "slot_name": normalized,
        "description": _read_description_best_effort(slot_dir),
    }


def delete_skill(workspace_root: Path, slot_name: str) -> bool:
    normalized = validate_slot_name(slot_name)
    slot_dir = operator_skills_dir(workspace_root) / normalized
    if not slot_dir.is_dir():
        return False
    shutil.rmtree(slot_dir)
    return True


def copy_all_to_cursor_scratch(workspace_root: Path, scratch_dir: Path) -> None:
    skills = list_skill_dirs(workspace_root)
    if not skills:
        return
    cursor_skills_root = scratch_dir / ".cursor" / "skills"
    cursor_skills_root.mkdir(parents=True, exist_ok=True)
    source_root = operator_skills_dir(workspace_root)
    for item in skills:
        slot_name = str(item["slot_name"])
        source = source_root / slot_name
        target = cursor_skills_root / slot_name
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)


def build_adk_skill_toolset_all(workspace_root: Path) -> Any | None:
    skills_root = operator_skills_dir(workspace_root)
    if not skills_root.is_dir():
        return None

    try:
        from google.adk.skills import load_skill_from_dir
        from google.adk.tools.skill_toolset import SkillToolset
    except ImportError:  # pragma: no cover
        logger.warning("google-adk skills unavailable; skipping SkillToolset")
        return None

    loaded: list[Any] = []
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if _find_skill_markdown(entry) is None:
            logger.warning("Skipping skill %s: no SKILL.md found", entry.name)
            continue
        try:
            loaded.append(load_skill_from_dir(entry))
        except Exception:
            logger.exception("Skipping skill %s: ADK load_skill_from_dir failed", entry.name)

    if not loaded:
        return None
    return SkillToolset(skills=loaded)
