from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.simagix.fallback_tools import unique_metrics_from_index
from backend.app.simagix.scoring import score_semantics
from backend.app.simagix.schemas import (
    BundleIndexEntry,
    ExecutiveContext,
    FallbackRetrievalEntry,
    Finding,
    Tier1Context,
    ValidationResult,
)

TIER1_REQUIRED = [
    "llm/executive_context.json",
    "diagnosis/findings.json",
    "diagnosis/anomaly_timeline.json",
    "diagnosis/activity_summary.json",
    "assessment/assessment.json",
    "assessment/formulas.json",
]


class SimagixBundleLoader:
    """Load tier_1 analyzed evidence from a mongo-ftdc export bundle."""

    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = bundle_dir.resolve()

    def exists(self) -> bool:
        return self.bundle_dir.is_dir()

    def load_tier1(self, run_id: str) -> Tier1Context:
        self._assert_bundle_ready()
        manifest = self._read_json("manifest.json")
        executive = ExecutiveContext.model_validate(self._read_json("llm/executive_context.json"))
        findings_raw = self._read_json("diagnosis/findings.json")
        findings = [Finding.model_validate(item) for item in findings_raw]
        return Tier1Context(
            run_id=run_id,
            bundle_dir=str(self.bundle_dir),
            manifest=manifest,
            executive_context=executive,
            findings=findings,
            anomaly_timeline=self._read_json("diagnosis/anomaly_timeline.json"),
            activity_summary=self._read_json("diagnosis/activity_summary.json"),
            assessment=self._read_json_optional("assessment/assessment.json"),
            formulas=self._read_json_optional("assessment/formulas.json"),
            bundle_index=self._load_bundle_index(),
            validation=self._load_validation(),
            fallback_index=self._load_fallback_index(),
        )

    def assemble_prompt_context(self, run_id: str) -> dict[str, Any]:
        tier1 = self.load_tier1(run_id)
        return {
            "run_id": tier1.run_id,
            "contract_version": tier1.executive_context.contract_version,
            "instruction": tier1.executive_context.instruction,
            "time_range": tier1.executive_context.time_range.model_dump(by_alias=True),
            "host": tier1.executive_context.host,
            "mongodb_version": tier1.executive_context.mongodb_version,
            "activity_summary": tier1.activity_summary,
            "findings": [finding.model_dump() for finding in tier1.findings],
            "top_anomaly_windows": [
                window.model_dump(by_alias=True)
                for window in tier1.executive_context.top_anomaly_windows
            ],
            "assessment_highlights": [
                highlight.model_dump()
                for highlight in tier1.executive_context.assessment_highlights
            ],
            "retrievable_metrics": unique_metrics_from_index(
                [entry.model_dump() for entry in tier1.fallback_index]
            ),
            "anomaly_event_count": tier1.executive_context.anomaly_event_count,
            "read_order": tier1.executive_context.read_order,
            "fallback_files": tier1.executive_context.fallback_files,
            "score_semantics": score_semantics(),
        }

    def _assert_bundle_ready(self) -> None:
        if not self.exists():
            raise FileNotFoundError(f"Bundle directory not found: {self.bundle_dir}")
        for rel in TIER1_REQUIRED:
            if not (self.bundle_dir / rel).exists():
                raise FileNotFoundError(f"Missing tier_1 file: {rel}")
        manifest_path = self.bundle_dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError("Missing authoritative manifest.json")

    def _read_json(self, rel: str) -> Any:
        with (self.bundle_dir / rel).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _read_json_optional(self, rel: str) -> Any | None:
        path = self.bundle_dir / rel
        if not path.exists():
            return None
        return self._read_json(rel)

    def _load_bundle_index(self) -> list[BundleIndexEntry]:
        raw = self._read_json_optional("bundle_index.json")
        if not raw:
            return []
        return [BundleIndexEntry.model_validate(item) for item in raw]

    def _load_validation(self) -> ValidationResult | None:
        raw = self._read_json_optional("validation.json")
        if not raw:
            return None
        if raw.get("errors") is None:
            raw["errors"] = []
        if raw.get("warnings") is None:
            raw["warnings"] = []
        return ValidationResult.model_validate(raw)

    def _load_fallback_index(self) -> list[FallbackRetrievalEntry]:
        raw = self._read_json_optional("llm/fallback_retrieval_index.json")
        if not raw:
            return []
        return [FallbackRetrievalEntry.model_validate(item) for item in raw]
