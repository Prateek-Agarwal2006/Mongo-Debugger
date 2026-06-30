from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.app.core.run_workspace import get_run_workspace
from backend.app.simagix.llm.skills.registry import (
    delete_skill,
    list_skill_dirs,
    upload_skill_zip,
)

router = APIRouter(prefix="/simagix/skills", tags=["simagix-skills"])


@router.get("")
def list_skills() -> dict[str, object]:
    workspace = get_run_workspace()
    return {"skills": list_skill_dirs(workspace.root)}


@router.post("")
async def upload_skill(
    slot_name: str = Form(...),
    archive: UploadFile = File(...),
) -> dict[str, object]:
    filename = (archive.filename or "").strip().lower()
    if not filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Upload must be a .zip file")
    content = await archive.read()
    workspace = get_run_workspace()
    try:
        record = upload_skill_zip(workspace.root, slot_name, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"skill": record}


@router.delete("/{slot_name}")
def remove_skill(slot_name: str) -> dict[str, object]:
    workspace = get_run_workspace()
    try:
        deleted = delete_skill(workspace.root, slot_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill not found: {slot_name}")
    return {"deleted": slot_name}
