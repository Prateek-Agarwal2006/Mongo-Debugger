from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.simagix.llm.skills.registry import (
    copy_all_to_cursor_scratch,
    delete_skill,
    list_skill_dirs,
    operator_skills_dir,
    upload_skill_zip,
    validate_slot_name,
)


def _make_skill_zip(*, root_prefix: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        prefix = f"{root_prefix}/" if root_prefix else ""
        zf.writestr(
            f"{prefix}SKILL.md",
            "---\ndescription: Test playbook\n---\n# Skill body\n",
        )
        zf.writestr(f"{prefix}references/notes.txt", "extra context")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    from backend.app.core.config import get_settings

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def test_validate_slot_name_rejects_invalid() -> None:
    with pytest.raises(ValueError, match="Skill slot name"):
        validate_slot_name("Bad Name!")


def test_upload_skill_zip_flat_layout(tmp_path: Path) -> None:
    record = upload_skill_zip(tmp_path, "my-playbook", _make_skill_zip())
    assert record["slot_name"] == "my-playbook"
    assert record["description"] == "Test playbook"
    slot_dir = operator_skills_dir(tmp_path) / "my-playbook"
    assert (slot_dir / "SKILL.md").is_file()
    assert (slot_dir / "references" / "notes.txt").read_text(encoding="utf-8") == "extra context"


def test_upload_skill_zip_single_top_level_folder(tmp_path: Path) -> None:
    upload_skill_zip(tmp_path, "nested", _make_skill_zip(root_prefix="pkg"))
    slot_dir = operator_skills_dir(tmp_path) / "nested"
    assert (slot_dir / "SKILL.md").is_file()


def test_upload_skill_zip_rejects_missing_skill_md(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("README.md", "no skill here")
    with pytest.raises(ValueError, match="SKILL.md"):
        upload_skill_zip(tmp_path, "bad", buf.getvalue())


def test_upload_skill_zip_rejects_zip_slip(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../SKILL.md", "---\ndescription: evil\n---\n")
    with pytest.raises(ValueError, match="Unsafe|escapes"):
        upload_skill_zip(tmp_path, "evil", buf.getvalue())


def test_list_and_delete_skill(tmp_path: Path) -> None:
    upload_skill_zip(tmp_path, "one", _make_skill_zip())
    upload_skill_zip(tmp_path, "two", _make_skill_zip())
    names = [item["slot_name"] for item in list_skill_dirs(tmp_path)]
    assert names == ["one", "two"]
    assert delete_skill(tmp_path, "one") is True
    assert delete_skill(tmp_path, "one") is False
    assert [item["slot_name"] for item in list_skill_dirs(tmp_path)] == ["two"]


def test_copy_all_to_cursor_scratch(tmp_path: Path) -> None:
    upload_skill_zip(tmp_path, "playbook", _make_skill_zip())
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    copy_all_to_cursor_scratch(tmp_path, scratch)
    target = scratch / ".cursor" / "skills" / "playbook" / "SKILL.md"
    assert target.is_file()


def test_skills_api_list_upload_delete(client: TestClient) -> None:
    listing = client.get("/simagix/skills")
    assert listing.status_code == 200
    assert listing.json()["skills"] == []

    upload = client.post(
        "/simagix/skills",
        data={"slot_name": "api-skill"},
        files={"archive": ("skill.zip", _make_skill_zip(), "application/zip")},
    )
    assert upload.status_code == 200
    assert upload.json()["skill"]["slot_name"] == "api-skill"

    listing2 = client.get("/simagix/skills")
    names = [item["slot_name"] for item in listing2.json()["skills"]]
    assert "api-skill" in names

    delete = client.delete("/simagix/skills/api-skill")
    assert delete.status_code == 200


def test_skill_workarea_page(client: TestClient) -> None:
    resp = client.get("/skill-workarea")
    assert resp.status_code == 200
    assert "Skill WorkArea" in resp.text


def test_to_adk_mcp_toolsets_builds_stdio_and_http() -> None:
    import asyncio

    from backend.app.simagix.llm.mcp.registry import to_adk_mcp_toolsets
    from backend.app.simagix.llm.mcp.specs import McpServerSpec

    specs = [
        McpServerSpec(
            server_id="evidence",
            transport="stdio",
            command="python",
            args=["-m", "test"],
            cwd="/tmp",
        ),
        McpServerSpec(
            server_id="remote",
            transport="http",
            url="https://example.com/mcp",
            headers={"Authorization": "Bearer x"},
        ),
    ]
    toolsets = to_adk_mcp_toolsets(specs)
    assert len(toolsets) == 2

    async def _close_all() -> None:
        for toolset in toolsets:
            await toolset.close()

    asyncio.run(_close_all())


def test_build_adk_skill_toolset_all_skips_invalid(tmp_path: Path) -> None:
    import asyncio

    from backend.app.simagix.llm.skills.registry import build_adk_skill_toolset_all

    skills_root = operator_skills_dir(tmp_path)
    skills_root.mkdir(parents=True)
    (skills_root / "good").mkdir()
    (skills_root / "good" / "SKILL.md").write_text(
        "---\nname: good\ndescription: ok\n---\n# Good\n",
        encoding="utf-8",
    )
    (skills_root / "bad").mkdir()
    (skills_root / "bad" / "README.md").write_text("no skill md", encoding="utf-8")

    toolset = build_adk_skill_toolset_all(tmp_path)
    if toolset is None:
        pytest.skip("google-adk skills unavailable in this environment")
    asyncio.run(toolset.close())
