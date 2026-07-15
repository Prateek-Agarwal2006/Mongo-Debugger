"""
Integration test for the raw tier (tier-3) pipeline:

  upload FTDC files → raw_files chunks in PG
  ingest (pipeline mock) → raw_file_index + raw_path_catalog + raw_path_prefix_map
  list_raw_paths() → prefix map + pattern search
  get_raw_window() → real per-second series via ftdc-slice

Requires:
  - DATABASE_URL set (standard test requirement)
  - ftdc-slice binary on PATH (test skips if absent)
  - Real FTDC files at tmp/diagnostic.data/ (test skips if absent)

Seams (correctness):
  - FtdcTools.get_raw_window == independent `ftdc-slice --mode window` on the
    original FTDC file bytes (CLI is the oracle — not recomputed in Python).
  - Every returned timestamp is inside the requested [start_ts, end_ts].
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.db.connection import db_conn
from backend.app.db.raw_files import (
    list_raw_filenames,
    reassemble_raw_file,
    store_raw_file,
)
from backend.app.jobs.ingest import _ingest_raw_file_index, _ingest_raw_path_catalog
from backend.app.simagix.evidence.ftdc_tools import FtdcTools

_RUN = "intgtest20260715T000000Z"
_KIND = "ftdc"
_KNOWN_PATH = "serverStatus/opcounters/insert"
_KNOWN_PATH_2 = "serverStatus/opcounters/query"

# Real FTDC fixture — the files used to validate the Go binary.
_FTDC_DIR = Path(__file__).resolve().parents[2] / "tmp" / "diagnostic.data"
_FTDC_FILES = sorted(_FTDC_DIR.glob("metrics.*")) if _FTDC_DIR.is_dir() else []

# The binary used for all tier-3 calls in this test module.
_FTDC_SLICE = shutil.which("ftdc-slice")

needs_ftdc = pytest.mark.skipif(
    not _FTDC_FILES,
    reason="tmp/diagnostic.data/ not found — run with real FTDC files",
)
needs_binary = pytest.mark.skipif(
    _FTDC_SLICE is None,
    reason="ftdc-slice binary not on PATH",
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _seed_raw_files() -> None:
    """Store the first two FTDC files into raw_files."""
    with db_conn() as conn:
        for path in _FTDC_FILES[:2]:
            store_raw_file(conn, _RUN, _KIND, path.name, path)


def _seed_raw_index(workspace_root: Path) -> None:
    """Run ftdc-slice --mode index to populate raw_file_index."""
    _ingest_raw_file_index(workspace_root, _RUN)


def _seed_raw_catalog(workspace_root: Path) -> None:
    """Run ftdc-slice --mode catalog to populate raw_path_catalog + prefix_map."""
    _ingest_raw_path_catalog(workspace_root, _RUN)


def _stage_ftdc_for_index(tmp_path: Path, path: Path) -> Path:
    """Copy one FTDC file into the upload layout ingest expects, return dest."""
    diag_dir = tmp_path / "simagix-workspace" / "uploads" / _RUN / "inputs" / "diagnostic.data"
    diag_dir.mkdir(parents=True)
    dest = diag_dir / path.name
    dest.write_bytes(path.read_bytes())
    return dest


def _cli_window(ftdc_path: Path, paths: list[str], start_ts: float, end_ts: float) -> dict:
    """Independent oracle: ftdc-slice on the original file (not via PG)."""
    assert _FTDC_SLICE is not None
    cmd = [
        _FTDC_SLICE,
        "--mode",
        "window",
        "--paths",
        ",".join(paths),
        "--start",
        str(start_ts),
        "--end",
        str(end_ts),
        str(ftdc_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=True)
    return json.loads(result.stdout)


def _file_index_bounds(ftdc_path: Path) -> tuple[float, float]:
    assert _FTDC_SLICE is not None
    result = subprocess.run(
        [_FTDC_SLICE, "--mode", "index", str(ftdc_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    rows = json.loads(result.stdout)
    return float(rows[0]["start_ts"]), float(rows[0]["end_ts"])


# ── raw_files chunk store ─────────────────────────────────────────────────────

@needs_ftdc
def test_store_and_list_real_ftdc(tmp_path: Path) -> None:
    """Store real FTDC files; list_raw_filenames returns them sorted."""
    _seed_raw_files()

    with db_conn() as conn:
        names = list_raw_filenames(conn, _RUN, _KIND)

    expected = sorted(p.name for p in _FTDC_FILES[:2])
    assert names == expected


@needs_ftdc
def test_reassemble_matches_original(tmp_path: Path) -> None:
    """Reassembled bytes are byte-for-byte identical to the source file."""
    path = _FTDC_FILES[0]
    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, path.name, path)

    dest = tmp_path / path.name
    with db_conn() as conn:
        reassemble_raw_file(conn, _RUN, _KIND, path.name, dest)

    assert dest.read_bytes() == path.read_bytes()


# ── raw_file_index ────────────────────────────────────────────────────────────

@needs_ftdc
@needs_binary
def test_raw_file_index_populated(tmp_path: Path) -> None:
    """After seeding, raw_file_index has one row per stored FTDC file."""
    # Seed files on disk under a tmp workspace so _ingest_raw_file_index finds them.
    diag_dir = tmp_path / "simagix-workspace" / "uploads" / _RUN / "inputs" / "diagnostic.data"
    diag_dir.mkdir(parents=True)
    for path in _FTDC_FILES[:2]:
        (diag_dir / path.name).write_bytes(path.read_bytes())

    _seed_raw_index(tmp_path)

    with db_conn() as conn:
        rows = conn.execute(
            "SELECT filename, start_ts, end_ts, bytes FROM raw_file_index"
            " WHERE run_id=%s ORDER BY filename",
            (_RUN,),
        ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row[1] > 0, f"start_ts should be > 0, got {row[1]}"
        assert row[2] > row[1], f"end_ts {row[2]} should be > start_ts {row[1]}"
        assert row[3] > 0


# ── raw_path_catalog + prefix_map ────────────────────────────────────────────

@needs_ftdc
@needs_binary
def test_raw_path_catalog_stored(tmp_path: Path) -> None:
    """After catalog ingest, evidence has raw_path_catalog with >1000 paths."""
    diag_dir = tmp_path / "simagix-workspace" / "uploads" / _RUN / "inputs" / "diagnostic.data"
    diag_dir.mkdir(parents=True)
    (diag_dir / _FTDC_FILES[-1].name).write_bytes(_FTDC_FILES[-1].read_bytes())

    _seed_raw_catalog(tmp_path)

    with db_conn() as conn:
        row = conn.execute(
            "SELECT data FROM evidence WHERE run_id=%s AND key='raw_path_catalog'",
            (_RUN,),
        ).fetchone()
        pmap = conn.execute(
            "SELECT data FROM evidence WHERE run_id=%s AND key='raw_path_prefix_map'",
            (_RUN,),
        ).fetchone()

    assert row is not None
    catalog = row[0]
    assert catalog["path_count"] > 1000
    assert "serverStatus" in [p.split("/")[0] for p in catalog["paths"]]

    assert pmap is not None
    assert "serverStatus" in pmap[0]


# ── FtdcTools.list_raw_paths ──────────────────────────────────────────────────

@needs_ftdc
@needs_binary
def test_list_raw_paths_prefix_map(tmp_path: Path) -> None:
    """list_raw_paths() with no args returns top-level prefix map."""
    diag_dir = tmp_path / "simagix-workspace" / "uploads" / _RUN / "inputs" / "diagnostic.data"
    diag_dir.mkdir(parents=True)
    (diag_dir / _FTDC_FILES[-1].name).write_bytes(_FTDC_FILES[-1].read_bytes())
    _seed_raw_catalog(tmp_path)

    tools = FtdcTools(_RUN, workspace_root=tmp_path)
    result = tools.list_raw_paths()

    assert "error" not in result
    assert "serverStatus" in result
    assert isinstance(result["serverStatus"], list)
    assert len(result["serverStatus"]) > 10


@needs_ftdc
@needs_binary
def test_list_raw_paths_pattern(tmp_path: Path) -> None:
    """list_raw_paths(pattern) returns matching paths from catalog."""
    diag_dir = tmp_path / "simagix-workspace" / "uploads" / _RUN / "inputs" / "diagnostic.data"
    diag_dir.mkdir(parents=True)
    (diag_dir / _FTDC_FILES[-1].name).write_bytes(_FTDC_FILES[-1].read_bytes())
    _seed_raw_catalog(tmp_path)

    tools = FtdcTools(_RUN, workspace_root=tmp_path)
    result = tools.list_raw_paths("opcounters")

    assert "error" not in result
    assert result["count"] > 0
    assert all("opcounters" in p.lower() for p in result["paths"])


# ── FtdcTools.get_raw_window ──────────────────────────────────────────────────

@needs_ftdc
@needs_binary
def test_get_raw_window_matches_cli_oracle(tmp_path: Path) -> None:
    """PG reassemble + ftdc-slice must match CLI oracle on the original file bytes."""
    path = _FTDC_FILES[0]
    file_start, _file_end = _file_index_bounds(path)
    # Narrow window near file start — known non-empty for this fixture.
    start_ts = file_start
    end_ts = file_start + 113.0
    paths = [_KNOWN_PATH, _KNOWN_PATH_2]

    oracle = _cli_window(path, paths, start_ts, end_ts)
    assert oracle.get("files_processed") == 1
    for p in paths:
        assert p in oracle["series"], f"oracle missing {p}"
        assert len(oracle["series"][p]) > 10, f"oracle too thin for {p}"

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, path.name, path)
    _stage_ftdc_for_index(tmp_path, path)
    _seed_raw_index(tmp_path)

    tools = FtdcTools(_RUN, workspace_root=tmp_path)
    result = tools.get_raw_window(paths=paths, start_ts=start_ts, end_ts=end_ts)

    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert result["files_processed"] == oracle["files_processed"]
    assert set(result["series"]) == set(oracle["series"])
    for p in paths:
        got = result["series"][p]
        want = oracle["series"][p]
        assert len(got) == len(want), f"{p}: point count {len(got)} != oracle {len(want)}"
        assert got == want, f"{p}: series diverged from CLI oracle (first mismatch in data)"
        for ts, _val in got:
            assert start_ts <= ts <= end_ts, f"{p}: ts {ts} outside [{start_ts}, {end_ts}]"


@needs_ftdc
@needs_binary
def test_get_raw_window_unknown_path_empty_series(tmp_path: Path) -> None:
    """Unknown FTDC path returns empty series for that key (or omits it), no crash."""
    path = _FTDC_FILES[0]
    file_start, _ = _file_index_bounds(path)
    start_ts, end_ts = file_start, file_start + 30.0

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, path.name, path)
    _stage_ftdc_for_index(tmp_path, path)
    _seed_raw_index(tmp_path)

    tools = FtdcTools(_RUN, workspace_root=tmp_path)
    result = tools.get_raw_window(
        paths=["serverStatus/does/not/exist"],
        start_ts=start_ts,
        end_ts=end_ts,
    )
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    series = result.get("series") or {}
    assert series.get("serverStatus/does/not/exist", []) == []


@needs_ftdc
@needs_binary
def test_get_raw_window_no_overlap_returns_empty(tmp_path: Path) -> None:
    """get_raw_window returns empty series when window doesn't overlap any file."""
    path = _FTDC_FILES[0]
    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, path.name, path)

    _stage_ftdc_for_index(tmp_path, path)
    _seed_raw_index(tmp_path)

    tools = FtdcTools(_RUN, workspace_root=tmp_path)
    result = tools.get_raw_window(
        paths=[_KNOWN_PATH],
        start_ts=1.0,       # year 1970 — no FTDC data there
        end_ts=1_000_000.0,
    )

    # Should return gracefully with empty series, not an error
    assert result["files_processed"] == 0 or result["series"] == {} or \
        result.get("note") is not None
