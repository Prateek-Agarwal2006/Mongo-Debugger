from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db.connection import db_conn
from backend.app.db.raw_files import (
    _CHUNK_BYTES,
    build_raw_file_index,
    list_raw_filenames,
    reassemble_raw_file,
    store_raw_file,
)

_RUN = "rawtest20260609T000000Z"
_KIND = "ftdc"


@pytest.fixture(autouse=True)
def _isolate_raw_rows():
    """Tests in this module share _RUN; wipe raw_files rows before and after each."""
    from backend.tests.db_cleanup import wipe_raw_rows

    wipe_raw_rows(_RUN)
    yield
    wipe_raw_rows(_RUN)


# ── helpers ───────────────────────────────────────────────────────────────────

def _row_count(run_id: str, filename: str) -> int:
    with db_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM raw_files WHERE run_id=%s AND filename=%s",
            (run_id, filename),
        ).fetchone()[0]


def _index_count(run_id: str) -> int:
    with db_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM raw_file_index WHERE run_id=%s",
            (run_id,),
        ).fetchone()[0]


# ── chunk-store roundtrip ─────────────────────────────────────────────────────

def test_roundtrip_small_file(tmp_path: Path) -> None:
    """store → reassemble → identical bytes (single chunk)."""
    data = b"hello world FTDC" * 100
    src = tmp_path / "metrics.small"
    src.write_bytes(data)

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, "metrics.small", src)

    dest = tmp_path / "out" / "metrics.small"
    with db_conn() as conn:
        reassemble_raw_file(conn, _RUN, _KIND, "metrics.small", dest)

    assert dest.read_bytes() == data


def test_roundtrip_multi_chunk(tmp_path: Path) -> None:
    """Files > _CHUNK_BYTES are split across multiple rows and reassembled correctly."""
    data = bytes(range(256)) * (_CHUNK_BYTES // 128 + 1)
    src = tmp_path / "metrics.big"
    src.write_bytes(data)

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, "metrics.big", src)

    # At least 2 chunks stored.
    assert _row_count(_RUN, "metrics.big") >= 2

    dest = tmp_path / "out_big" / "metrics.big"
    with db_conn() as conn:
        reassemble_raw_file(conn, _RUN, _KIND, "metrics.big", dest)

    assert dest.read_bytes() == data


def test_store_idempotent(tmp_path: Path) -> None:
    """Storing the same file twice inserts no duplicate rows (ON CONFLICT DO NOTHING)."""
    data = b"idempotent test"
    src = tmp_path / "metrics.idem"
    src.write_bytes(data)

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, "metrics.idem", src)
        store_raw_file(conn, _RUN, _KIND, "metrics.idem", src)

    assert _row_count(_RUN, "metrics.idem") == 1


def test_reassemble_creates_parent_dirs(tmp_path: Path) -> None:
    """reassemble_raw_file creates intermediate directories."""
    data = b"dir creation test"
    src = tmp_path / "metrics.dir"
    src.write_bytes(data)

    with db_conn() as conn:
        store_raw_file(conn, _RUN, _KIND, "metrics.dir", src)

    dest = tmp_path / "deep" / "nested" / "metrics.dir"
    assert not dest.parent.exists()

    with db_conn() as conn:
        reassemble_raw_file(conn, _RUN, _KIND, "metrics.dir", dest)

    assert dest.read_bytes() == data


# ── list_raw_filenames ────────────────────────────────────────────────────────

def test_list_raw_filenames_sorted(tmp_path: Path) -> None:
    """list_raw_filenames returns stored filenames in alphabetical order."""
    for name in ("metrics.c", "metrics.a", "metrics.b"):
        f = tmp_path / name
        f.write_bytes(b"x")
        with db_conn() as conn:
            store_raw_file(conn, _RUN, _KIND, name, f)

    with db_conn() as conn:
        names = list_raw_filenames(conn, _RUN, _KIND)

    assert names == ["metrics.a", "metrics.b", "metrics.c"]


def test_list_raw_filenames_empty() -> None:
    """list_raw_filenames returns empty list when run has no stored files."""
    with db_conn() as conn:
        names = list_raw_filenames(conn, "nonexistent-run", _KIND)
    assert names == []


# ── build_raw_file_index error paths ─────────────────────────────────────────

def test_build_raw_file_index_missing_binary(tmp_path: Path) -> None:
    """build_raw_file_index does not raise when the binary path does not exist."""
    src = tmp_path / "metrics.fake"
    src.write_bytes(b"not ftdc")

    with db_conn() as conn:
        # Should return silently, not raise FileNotFoundError.
        build_raw_file_index(conn, _RUN, _KIND, [src], ftdc_slice_bin="/no/such/binary")

    assert _index_count(_RUN) == 0


def test_build_raw_file_index_empty_paths() -> None:
    """build_raw_file_index with an empty path list does nothing."""
    with db_conn() as conn:
        build_raw_file_index(conn, _RUN, _KIND, [])

    assert _index_count(_RUN) == 0


def test_build_raw_file_index_invalid_ftdc_data(tmp_path: Path) -> None:
    """build_raw_file_index on a file that is not valid FTDC inserts no rows."""
    import shutil

    ftdc_slice = shutil.which("ftdc-slice")
    if ftdc_slice is None:
        pytest.skip("ftdc-slice binary not on PATH")

    src = tmp_path / "metrics.garbage"
    src.write_bytes(b"\x00" * 100)

    with db_conn() as conn:
        build_raw_file_index(conn, _RUN, _KIND, [src], ftdc_slice_bin=ftdc_slice)

    assert _index_count(_RUN) == 0
