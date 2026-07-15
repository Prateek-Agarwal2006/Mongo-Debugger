from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.run_workspace import RunWorkspace
from backend.app.main import create_app
from backend.app.simagix.llm.mcp.connectors import (
    McpConnectorRegistry,
    validate_connector_payload,
)
from backend.app.simagix.llm.mcp.registry import build_user_mcp_servers

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    return TestClient(create_app())


def test_validate_http_connector() -> None:
    record = validate_connector_payload(
        {
            "id": "my-remote",
            "name": "Remote MCP",
            "transport": "http",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer x"},
        }
    )
    assert record.id == "my-remote"
    assert record.transport == "http"
    assert record.url == "https://example.com/mcp"


def test_validate_local_http_connector() -> None:
    record = validate_connector_payload(
        {
            "id": "local-test-http",
            "name": "Local test HTTP",
            "transport": "http",
            "url": "http://127.0.0.1:8765/mcp",
            "headers": {},
        }
    )
    assert record.url == "http://127.0.0.1:8765/mcp"


def test_validate_stdio_template_requires_env() -> None:
    with pytest.raises(ValueError, match="Missing required env"):
        validate_connector_payload(
            {
                "id": "gh",
                "name": "GitHub",
                "transport": "stdio_template",
                "template_id": "github-mcp",
                "env": {},
            }
        )


def test_validate_test_ping_stdio_template_no_env() -> None:
    record = validate_connector_payload(
        {
            "id": "local-test",
            "name": "Local test",
            "transport": "stdio_template",
            "template_id": "test-ping-mcp",
            "env": {},
        }
    )
    assert record.template_id == "test-ping-mcp"
    assert record.env == {}


def test_registry_persists_in_pg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from backend.app.db.connection import db_conn

    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    workspace = RunWorkspace(tmp_path)
    registry = McpConnectorRegistry(workspace.root)
    record = registry.upsert(
        {
            "id": "docs-mcp-pg",
            "name": "Docs MCP",
            "transport": "http",
            "url": "https://example.com/mcp",
        }
    )
    assert record.id == "docs-mcp-pg"

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM mcp_connectors WHERE id = %s", ("docs-mcp-pg",)
        ).fetchone()
    assert row is not None
    data = row[0]
    assert data["id"] == "docs-mcp-pg"


def test_build_user_mcp_servers_resolves_ids(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    workspace = RunWorkspace(tmp_path)
    registry = McpConnectorRegistry(workspace.root)
    registry.upsert(
        {
            "id": "docs-mcp-resolve",
            "name": "Docs MCP",
            "transport": "http",
            "url": "https://example.com/mcp",
        }
    )
    servers = build_user_mcp_servers(workspace.root, ["docs-mcp-resolve"])
    assert "docs-mcp-resolve" in servers
    assert build_user_mcp_servers(workspace.root, []) == {}


def test_mcp_connectors_api_list_and_create(client: TestClient) -> None:
    listing = client.get("/simagix/mcp-connectors")
    assert listing.status_code == 200
    body = listing.json()
    assert "connectors" in body
    assert "stdio_templates" in body
    assert any(item["id"] == "simagix-evidence" for item in body["builtins"])

    create = client.post(
        "/simagix/mcp-connectors",
        json={
            "id": "remote-one",
            "name": "Remote One",
            "transport": "http",
            "url": "https://example.com/mcp",
        },
    )
    assert create.status_code == 200
    assert create.json()["connector"]["id"] == "remote-one"

    listing2 = client.get("/simagix/mcp-connectors")
    ids = [item["id"] for item in listing2.json()["connectors"]]
    assert "remote-one" in ids

    delete = client.delete("/simagix/mcp-connectors/remote-one")
    assert delete.status_code == 200


def test_mcp_workarea_is_spa_not_api(client: TestClient) -> None:
    """HTML UI is nginx SPA; API has no /mcp-workarea route."""
    resp = client.get("/mcp-workarea")
    assert resp.status_code == 404


def test_build_user_mcp_servers_unknown_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_ROOT", str(tmp_path))
    workspace = RunWorkspace(tmp_path)
    with pytest.raises(ValueError, match="Unknown MCP connector"):
        build_user_mcp_servers(workspace.root, ["missing-id"])
