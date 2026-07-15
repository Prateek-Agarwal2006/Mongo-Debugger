from __future__ import annotations

import json

import pytest

from backend.app.db.connection import db_conn
from backend.app.simagix.budget import RetrievalBudget
from backend.app.simagix.evidence.hatchet_tools import (
    HATCHET_MCP_TOOL_NAMES,
    HatchetTools,
    hatchet_evidence_available,
    load_hatchet_summary,
)

RUN_ID = "upload20260618T120000Z"

_SUMMARY = {
    "contract_version": "1.0.0",
    "run_id": RUN_ID,
    "hatchet_name": "merge",
    "merge": True,
    "metadata": {
        "mongodb_version": "7.0",
        "module": "mongod",
        "arch": "arm64",
        "os": "linux",
        "start": "2024-01-01",
        "end": "2024-01-02",
        "log_line_count": 3,
    },
    "source_files": [],
    "marker_counts": [{"marker": 1, "count": 3}],
}


def _seed(run_id: str = RUN_ID) -> None:
    with db_conn() as conn:
        for key, data in [
            ("hatchet_summary", _SUMMARY),
            ("hatchet_meta", {"hatchet_name": "merge"}),
        ]:
            conn.execute(
                "INSERT INTO evidence (run_id, key, data) VALUES (%s, %s, %s)"
                " ON CONFLICT (run_id, key) DO UPDATE SET data = EXCLUDED.data",
                (run_id, key, json.dumps(data)),
            )
        conn.execute(
            "INSERT INTO hatchet_ops (run_id, op, count, avg_ms, max_ms, total_ms, ns, _index, filter, marker)"
            " VALUES (%s, 'find', 5, 100.0, 200, 500, 'db.coll', 'idx', '{}', 1),"
            "        (%s, 'update', 2, 300.0, 400, 600, 'db.coll', 'COLLSCAN', '{}', 1)",
            (run_id, run_id),
        )
        conn.execute(
            "INSERT INTO hatchet_logs (run_id, date, op, ns, milli, filter, message, marker)"
            " VALUES (%s, '2024-01-01T00:00:00', 'find', 'db.coll', 120, '{}', 'slow find', 1),"
            "        (%s, '2024-01-01T00:01:00', 'update', 'db.coll', 80, '{}', 'slow update', 1),"
            "        (%s, '2024-01-01T00:02:00', 'insert', 'db.coll', NULL, NULL, 'no milli', 1)",
            (run_id, run_id, run_id),
        )
        conn.execute(
            "INSERT INTO hatchet_audit (run_id, type, name, value)"
            " VALUES (%s, 'exception', 'SocketException', 3), (%s, 'failed', 'authentication', 1)",
            (run_id, run_id),
        )
        conn.execute(
            "INSERT INTO hatchet_clients (run_id, ip, port, conns, accepted, ended, context, marker)"
            " VALUES (%s, '10.0.0.1', '27017', 12, 10, 2, 'listener', 1)",
            (run_id,),
        )
        conn.execute(
            "INSERT INTO hatchet_drivers (run_id, ip, driver, version, marker)"
            " VALUES (%s, '10.0.0.1', 'mongo-java-driver|sync', '4.11.0', 1)",
            (run_id,),
        )


def test_hatchet_evidence_available() -> None:
    assert not hatchet_evidence_available(RUN_ID)
    _seed()
    assert hatchet_evidence_available(RUN_ID)


def test_load_hatchet_summary() -> None:
    _seed()
    summary = load_hatchet_summary(RUN_ID)
    assert summary is not None
    assert summary["hatchet_name"] == "merge"


def test_get_hatchet_slow_ops() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_slow_ops(limit=5)
    assert result["hatchet_name"] == "merge"
    assert len(result["ops"]) == 2
    assert result["ops"][0]["op"] == "update"  # avg_ms 300 sorts first


def test_get_hatchet_slow_ops_collscan_only() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_slow_ops(limit=5, collscan_only=True)
    assert len(result["ops"]) == 1
    assert result["ops"][0]["index"] == "COLLSCAN"


def test_get_hatchet_log_examples() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_log_examples(limit=3)
    assert len(result["examples"]) == 2  # NULL-milli row excluded
    assert result["examples"][0]["milli"] == 120
    assert result["examples"][0]["snippet"] == "slow find"


def test_get_hatchet_log_examples_min_milli() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_log_examples(limit=5, min_milli=100)
    assert len(result["examples"]) == 1
    assert result["examples"][0]["op"] == "find"


def test_get_hatchet_audit() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_audit(audit_type="exception")
    assert result["rows"][0]["name"] == "SocketException"


def test_get_hatchet_connection_timeline() -> None:
    _seed()
    tools = HatchetTools(RUN_ID, budget=RetrievalBudget(max_tool_calls=5))
    result = tools.get_hatchet_connection_timeline(limit=5)
    assert result["timeline"][0]["bucket"] == "10.0.0.1"
    assert result["timeline"][0]["accepted"] == 10


def test_hatchet_tool_budget_exhaustion() -> None:
    _seed()
    budget = RetrievalBudget(max_tool_calls=1)
    tools = HatchetTools(RUN_ID, budget=budget)
    tools.get_hatchet_audit()
    with pytest.raises(RuntimeError, match="budget exhausted"):
        tools.get_hatchet_slow_ops()


def test_hatchet_mcp_tool_names_complete() -> None:
    assert HATCHET_MCP_TOOL_NAMES == frozenset({
        "get_hatchet_slow_ops",
        "get_hatchet_log_examples",
        "get_hatchet_audit",
        "get_hatchet_connection_timeline",
    })
