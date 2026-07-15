from __future__ import annotations

from typing import Any

from backend.app.db.connection import db_conn
from backend.app.simagix.evidence.ftdc_tools import unique_metrics_from_index
from backend.app.simagix.scoring import score_semantics
from backend.app.simagix.schemas import (
    BundleIndexEntry,
    ExecutiveContext,
    FallbackRetrievalEntry,
    Finding,
    Tier1Context,
    ValidationResult,
)

_TIER1_REQUIRED = frozenset({
    "executive_context",
    "findings",
    "anomaly_timeline",
    "activity_summary",
})


def _get(conn: Any, run_id: str, key: str) -> Any | None:
    cur = conn.execute(
        "SELECT data FROM evidence WHERE run_id = %s AND key = %s", (run_id, key)
    )
    row = cur.fetchone()
    return row[0] if row else None


class EvidenceLoader:
    """Load tier-1 analysed evidence from Postgres (replaces file-based SimagixBundleLoader)."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id

    def exists(self) -> bool:
        with db_conn() as conn:
            cur = conn.execute(
                "SELECT 1 FROM evidence WHERE run_id = %s AND key = 'manifest' LIMIT 1",
                (self.run_id,),
            )
            return cur.fetchone() is not None

    def load_tier1(self) -> Tier1Context:
        with db_conn() as conn:
            missing = [
                k for k in _TIER1_REQUIRED
                if _get(conn, self.run_id, k) is None
            ]
            if missing:
                raise FileNotFoundError(
                    f"Run {self.run_id!r} missing evidence keys: {missing}"
                )
            manifest = _get(conn, self.run_id, "manifest") or {}
            executive = ExecutiveContext.model_validate(
                _get(conn, self.run_id, "executive_context")
            )
            findings = [
                Finding.model_validate(item)
                for item in (_get(conn, self.run_id, "findings") or [])
            ]
            bundle_index_raw = _get(conn, self.run_id, "bundle_index") or []
            validation_raw = _get(conn, self.run_id, "validation")
            fallback_raw = _get(conn, self.run_id, "fallback_index") or []

        validation: ValidationResult | None = None
        if validation_raw is not None:
            validation_raw["errors"] = validation_raw.get("errors") or []
            validation_raw["warnings"] = validation_raw.get("warnings") or []
            validation = ValidationResult.model_validate(validation_raw)

        return Tier1Context(
            run_id=self.run_id,
            bundle_dir="",
            manifest=manifest,
            executive_context=executive,
            findings=findings,
            anomaly_timeline=self._load("anomaly_timeline"),
            activity_summary=self._load("activity_summary"),
            assessment=self._load("assessment"),
            formulas=self._load("formulas"),
            bundle_index=[BundleIndexEntry.model_validate(i) for i in bundle_index_raw],
            validation=validation,
            fallback_index=[FallbackRetrievalEntry.model_validate(i) for i in fallback_raw],
        )

    def assemble_prompt_context(self) -> dict[str, Any]:
        tier1 = self.load_tier1()
        return {
            "run_id": tier1.run_id,
            "contract_version": tier1.executive_context.contract_version,
            "instruction": tier1.executive_context.instruction,
            "time_range": tier1.executive_context.time_range.model_dump(by_alias=True),
            "host": tier1.executive_context.host,
            "mongodb_version": tier1.executive_context.mongodb_version,
            "activity_summary": tier1.activity_summary,
            "findings": [f.model_dump() for f in tier1.findings],
            "top_anomaly_windows": [
                w.model_dump(by_alias=True)
                for w in tier1.executive_context.top_anomaly_windows
            ],
            "assessment_highlights": [
                h.model_dump()
                for h in tier1.executive_context.assessment_highlights
            ],
            "retrievable_metrics": unique_metrics_from_index(
                [e.model_dump() for e in tier1.fallback_index]
            ),
            "anomaly_event_count": tier1.executive_context.anomaly_event_count,
            "read_order": tier1.executive_context.read_order,
            "fallback_files": tier1.executive_context.fallback_files,
            "score_semantics": score_semantics(),
        }

    def _load(self, key: str) -> Any:
        with db_conn() as conn:
            return _get(conn, self.run_id, key)


def list_run_ids() -> list[str]:
    """Distinct run_ids present in the evidence table (PG source of truth for catalog)."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT run_id FROM evidence ORDER BY run_id DESC"
        ).fetchall()
    return [row[0] for row in rows]
