from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MB per row


def store_raw_file(conn: Any, run_id: str, kind: str, filename: str, path: Path) -> None:
    """Chunk file at path into raw_files rows. Idempotent (ON CONFLICT DO NOTHING)."""
    data = path.read_bytes()
    for chunk_no, offset in enumerate(range(0, len(data), _CHUNK_BYTES)):
        conn.execute(
            "INSERT INTO raw_files (run_id, kind, filename, chunk_no, data)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT DO NOTHING",
            (run_id, kind, filename, chunk_no, data[offset : offset + _CHUNK_BYTES]),
        )


def reassemble_raw_file(conn: Any, run_id: str, kind: str, filename: str, dest: Path) -> None:
    """Reassemble chunks from raw_files back to dest on disk (creates parent dirs)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cur = conn.execute(
        "SELECT data FROM raw_files"
        " WHERE run_id=%s AND kind=%s AND filename=%s"
        " ORDER BY chunk_no",
        (run_id, kind, filename),
    )
    with dest.open("wb") as fh:
        for (chunk,) in cur:
            fh.write(bytes(chunk))


def list_raw_filenames(conn: Any, run_id: str, kind: str) -> list[str]:
    """Distinct filenames stored for (run_id, kind), sorted."""
    cur = conn.execute(
        "SELECT DISTINCT filename FROM raw_files"
        " WHERE run_id=%s AND kind=%s ORDER BY filename",
        (run_id, kind),
    )
    return [row[0] for row in cur]


def build_raw_file_index(
    conn: Any,
    run_id: str,
    kind: str,
    ftdc_paths: list[Path],
    ftdc_slice_bin: str | None = None,
) -> None:
    """Run ftdc-slice --mode index and upsert per-file time windows into raw_file_index."""
    if not ftdc_paths:
        return

    binary = ftdc_slice_bin or shutil.which("ftdc-slice") or "ftdc-slice"
    # Full captures can be 20+ metrics.* files — 120s was too tight and bubbled up as a
    # fake "pipeline timed out after 3600s" from ftdc_job's broad TimeoutExpired handler.
    index_timeout = max(300, 90 * len(ftdc_paths))
    try:
        result = subprocess.run(
            [binary, "--mode", "index", *[str(p) for p in ftdc_paths]],
            capture_output=True,
            text=True,
            timeout=index_timeout,
        )
    except (FileNotFoundError, OSError):
        return
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"ftdc-slice --mode index timed out after {index_timeout}s "
            f"on {len(ftdc_paths)} FTDC file(s)"
        ) from exc
    if not result.stdout.strip():
        return
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return

    for e in entries:
        conn.execute(
            "INSERT INTO raw_file_index (run_id, kind, filename, start_ts, end_ts, bytes)"
            " VALUES (%s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (run_id, kind, filename)"
            " DO UPDATE SET start_ts=EXCLUDED.start_ts, end_ts=EXCLUDED.end_ts,"
            " bytes=EXCLUDED.bytes",
            (run_id, kind, Path(e["filename"]).name, e["start_ts"], e["end_ts"], e["bytes"]),
        )
