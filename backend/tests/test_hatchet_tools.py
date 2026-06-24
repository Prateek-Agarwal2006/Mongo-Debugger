from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from backend.app.core.run_workspace import RunWorkspace
from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.hatchet_export import export_hatchet_summary
from backend.app.simagix.hatchet_tools import HatchetEvidenceTools, hatchet_evidence_available
from backend.app.simagix.hatchet_tools import HATCHET_MCP_TOOL_NAMES

RUN_ID = "upload20260618T120000Z"


def _seed_hatchet_run(tmp_path: Path) -> None:
    workspace = RunWorkspace(tmp_path)
    hatchet_dir = workspace.hatchet_dir(RUN_ID)
    hatchet_dir.mkdir(parents=True)
    db_path = workspace.hatchet_db_path(RUN_ID)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hatchet (name TEXT, merge INTEGER, version TEXT, module TEXT, arch TEXT, os TEXT, start TEXT, end TEXT);
        INSERT INTO hatchet VALUES ('merge', 1, '7.0', 'mongod', 'arm64', 'linux', '2024-01-01', '2024-01-02');

        CREATE TABLE merge (date TEXT, op TEXT, ns TEXT, milli REAL, filter TEXT, message TEXT, marker INTEGER);
        INSERT INTO merge VALUES ('2024-01-01T00:00:00', 'find', 'db.coll', 120.0, '{}', 'slow find', 1);

        CREATE TABLE merge_ops (op TEXT, count INTEGER, avg_ms REAL, max_ms REAL, total_ms REAL, ns TEXT, _index TEXT, filter TEXT, marker INTEGER);
        INSERT INTO merge_ops VALUES ('find', 5, 100.0, 200.0, 500.0, 'db.coll', 'idx', '{}', 1);

        CREATE TABLE merge_audit (type TEXT, name TEXT, value INTEGER);
        INSERT INTO merge_audit VALUES ('exception', 'SocketException', 3);

        CREATE TABLE merge_clients (date TEXT, accepted INTEGER, ended INTEGER);
        INSERT INTO merge_clients VALUES ('2024-01-01T00:00:00', 10, 2);
        """
    )
    conn.commit()
    conn.close()

    summary = {
        "hatchet_name": "merge",
        "store_paths": {
            "logs_table": "merge",
            "ops_table": "merge_ops",
            "audit_table": "merge_audit",
            "clients_table": "merge_clients",
        },
    }
    workspace.hatchet_summary_path(RUN_ID).write_text(json.dumps(summary), encoding="utf-8")


def test_hatchet_evidence_available(tmp_path: Path) -> None:
    assert not hatchet_evidence_available(tmp_path, RUN_ID)
    _seed_hatchet_run(tmp_path)
    assert hatchet_evidence_available(tmp_path, RUN_ID)


def test_get_hatchet_slow_ops(tmp_path: Path) -> None:
    _seed_hatchet_run(tmp_path)
    tools = HatchetEvidenceTools(tmp_path, RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_slow_ops(limit=5)
    assert result["hatchet_name"] == "merge"
    assert len(result["ops"]) == 1
    assert result["ops"][0]["op"] == "find"


def test_get_hatchet_log_examples(tmp_path: Path) -> None:
    _seed_hatchet_run(tmp_path)
    tools = HatchetEvidenceTools(tmp_path, RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_log_examples(limit=3)
    assert len(result["examples"]) == 1
    assert result["examples"][0]["milli"] == 120.0


def test_get_hatchet_audit(tmp_path: Path) -> None:
    _seed_hatchet_run(tmp_path)
    tools = HatchetEvidenceTools(tmp_path, RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_audit(audit_type="exception")
    assert result["rows"][0]["name"] == "SocketException"


def test_get_hatchet_connection_timeline(tmp_path: Path) -> None:
    _seed_hatchet_run(tmp_path)
    tools = HatchetEvidenceTools(tmp_path, RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_connection_timeline(limit=5)
    assert result["timeline"][0]["accepted"] == 10


def test_export_hatchet_summary_ip_based_clients(tmp_path: Path) -> None:
    """Real Hatchet 7.x merge_clients has ip/accepted/ended but no date column."""
    workspace = RunWorkspace(tmp_path)
    hatchet_dir = workspace.hatchet_dir(RUN_ID)
    hatchet_dir.mkdir(parents=True)
    db_path = workspace.hatchet_db_path(RUN_ID)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE hatchet (
            name TEXT, version TEXT, module TEXT, arch TEXT, os TEXT,
            start TEXT, end TEXT, merge INTEGER, created_at TEXT
        );
        INSERT INTO hatchet VALUES (
            'merge', '7.0.28', '', 'x86_64', 'rhel80',
            '2026-06-16T03:22:01', '2026-06-16T10:38:26', 1, '2026-06-24'
        );

        CREATE TABLE merge (
            date TEXT, op TEXT, ns TEXT, milli INTEGER, filter TEXT, message TEXT, marker INTEGER
        );
        INSERT INTO merge VALUES ('2026-06-16T04:00:00', 'find', 'db.coll', 50, '{}', 'slow', 1);

        CREATE TABLE merge_ops (
            op TEXT, count INTEGER, avg_ms REAL, max_ms REAL, total_ms REAL,
            ns TEXT, _index TEXT, filter TEXT, marker INTEGER
        );
        INSERT INTO merge_ops VALUES ('find', 1, 50.0, 50, 50, 'db.coll', 'idx', '{}', 1);

        CREATE TABLE merge_audit (type TEXT, name TEXT, value INTEGER);
        INSERT INTO merge_audit VALUES ('exception', 'SocketException', 2);

        CREATE TABLE merge_clients (
            id INTEGER PRIMARY KEY, ip TEXT, port TEXT, conns INTEGER,
            accepted INTEGER, ended INTEGER, context TEXT, marker INTEGER
        );
        INSERT INTO merge_clients VALUES (1, '10.0.0.1', '27017', 1, 5, 1, '', 1);
        INSERT INTO merge_clients VALUES (2, '10.0.0.2', '27017', 1, 3, 0, '', 1);

        CREATE TABLE merge_drivers (driver TEXT, version TEXT, marker INTEGER);
        INSERT INTO merge_drivers VALUES ('mongo-go-driver', '1.12', 1);
        """
    )
    conn.commit()
    conn.close()

    summary = export_hatchet_summary(
        db_path,
        source_files=[{"marker": 1, "name": "mongod-case.log", "path": "logs/mongod-case.log"}],
        run_id=RUN_ID,
    )
    assert summary["metadata"]["log_line_count"] == 1
    assert summary["connection_timeline"][0]["bucket"] == "10.0.0.1"
    assert summary["connection_timeline"][0]["accepted"] == 5


def test_hatchet_tool_budget_exhaustion(tmp_path: Path) -> None:
    _seed_hatchet_run(tmp_path)
    budget = RetrievalBudget(max_tool_calls=1)
    tools = HatchetEvidenceTools(tmp_path, RUN_ID, budget=budget)
    tools.get_hatchet_audit()
    with pytest.raises(RuntimeError, match="budget exhausted"):
        tools.get_hatchet_slow_ops()


def test_hatchet_mcp_tool_names_complete() -> None:
    assert HATCHET_MCP_TOOL_NAMES == frozenset(
        {
            "get_hatchet_slow_ops",
            "get_hatchet_log_examples",
            "get_hatchet_audit",
            "get_hatchet_connection_timeline",
        }
    )
