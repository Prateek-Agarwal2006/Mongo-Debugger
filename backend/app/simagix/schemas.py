from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TimeRange(BaseModel):
    from_: datetime = Field(alias="from")
    to: datetime
    duration_seconds: float

    model_config = {"populate_by_name": True}


class Finding(BaseModel):
    name: str
    description: str
    severity: str
    symptoms: list[str]
    suggestion: str
    score: int
    detected_at: datetime


class AnomalyWindow(BaseModel):
    metric: str
    severity: str
    peak: float
    threshold: str
    from_: datetime = Field(alias="from")
    to: datetime
    duration_seconds: float

    model_config = {"populate_by_name": True}


class AssessmentHighlight(BaseModel):
    metric: str
    label: str
    score: int
    p95: float


class ExecutiveContext(BaseModel):
    contract_version: str
    instruction: str
    time_range: TimeRange
    host: str
    mongodb_version: str
    activity_summary: dict[str, Any]
    findings: list[Finding]
    top_anomaly_windows: list[AnomalyWindow]
    assessment_highlights: list[AssessmentHighlight]
    anomaly_event_count: int
    read_order: list[str]
    fallback_files: dict[str, str]
    recommended_metrics: list[str] = Field(default_factory=list)


class BundleIndexEntry(BaseModel):
    path: str
    tier: str
    size_bytes: int
    sha256: str | None = None


class ValidationResult(BaseModel):
    contract_version: str
    validated_at: datetime
    valid: bool
    export_tier: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tier_1_complete: bool = False
    tier_2_present: bool = False
    tier_3_present: bool = False


class FallbackRetrievalEntry(BaseModel):
    metric: str
    source: str
    source_file: str
    tier: str
    window: TimeRange | None = None
    related_finding: str | None = None
    points: int | None = None


class Tier1Context(BaseModel):
    run_id: str
    bundle_dir: str
    manifest: dict[str, Any]
    executive_context: ExecutiveContext
    findings: list[Finding]
    anomaly_timeline: list[dict[str, Any]]
    activity_summary: dict[str, Any]
    assessment: dict[str, Any] | None = None
    formulas: dict[str, Any] | None = None
    bundle_index: list[BundleIndexEntry] = Field(default_factory=list)
    validation: ValidationResult | None = None
    fallback_index: list[FallbackRetrievalEntry] = Field(default_factory=list)
