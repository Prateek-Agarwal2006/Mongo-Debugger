from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.core.run_workspace import get_run_workspace
from backend.app.simagix.llm.mcp.connectors import McpConnectorRegistry, list_stdio_templates

router = APIRouter(prefix="/simagix/mcp-connectors", tags=["simagix-mcp-connectors"])


class McpConnectorCreateRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=120)
    transport: str = Field(..., description="http or stdio_template")
    description: str = Field(default="")
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    template_id: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


@router.get("")
def list_mcp_connectors() -> dict[str, object]:
    registry = McpConnectorRegistry(get_run_workspace().root)
    return {
        "connectors": [item.to_dict() for item in registry.list_connectors()],
        "stdio_templates": list_stdio_templates(),
        "builtins": [
            {
                "id": "simagix-evidence",
                "name": "Simagix evidence",
                "locked": True,
                "description": "Required FTDC evidence MCP for RCA",
            }
        ],
    }


@router.post("")
def create_mcp_connector(body: McpConnectorCreateRequest) -> dict[str, object]:
    registry = McpConnectorRegistry(get_run_workspace().root)
    try:
        record = registry.upsert(body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"connector": record.to_dict()}


@router.delete("/{connector_id}")
def delete_mcp_connector(connector_id: str) -> dict[str, object]:
    registry = McpConnectorRegistry(get_run_workspace().root)
    try:
        deleted = registry.delete(connector_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Connector not found: {connector_id}")
    return {"deleted": connector_id}
