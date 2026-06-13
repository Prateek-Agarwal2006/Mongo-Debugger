"""Simagix/mongo-ftdc assessment score semantics.

Verified against upstream:
- simagix/mongo-ftdc assessment.go (default score 101, FormulaMap gate)
- simagix/mongo-ftdc/utils.go GetScoreByRange (NaN -> 101)
- simagix/mongo-ftdc/diagnosis.go hasProblematicScore (score < 101)
- cmd/llm-export buildAssessmentHighlights (skips score >= 101)
"""

from __future__ import annotations

from typing import Any

# Sentinel used by mongo-ftdc when a metric is not health-scored.
SCORE_NOT_ASSESSED = 101


def score_semantics() -> dict[str, Any]:
    """Machine-readable score legend for LLM grounding."""
    return {
        "source": "simagix/mongo-ftdc assessment engine",
        "range": "0-100 are health scores; lower is worse",
        "100": "healthy — metric value below low watermark",
        "0": "unhealthy — metric value above high watermark",
        "1_to_99": "proportional between low and high watermarks (GetScoreByRange)",
        str(SCORE_NOT_ASSESSED): {
            "meaning": "not assessed / unavailable (N/A sentinel — NOT healthy)",
            "reasons": [
                "metric has no scoring formula in FormulaMap (e.g. conns_active, conns_available)",
                "metric missing from FTDC data",
                "NaN during score calculation",
                "insufficient data to compute score (e.g. empty tcmalloc series)",
            ],
            "llm_guidance": (
                "Ignore score 101 for health conclusions. "
                "Use p5/median/p95 as informational stats only, or rely on findings/anomalies instead."
            ),
        },
        "assessment_highlights_rule": "Only metrics with score < 101 appear in assessment_highlights",
        "findings_rule": "Named findings come from metrics that are scored and cross diagnosis thresholds",
    }


def score_semantics_prompt_lines() -> list[str]:
    """Short lines for inclusion in Phase 2 prompt text."""
    return [
        "Simagix assessment scores: 0-100 only (lower = worse). 100 = healthy, 0 = critical.",
        f"Score {SCORE_NOT_ASSESSED} = NOT ASSESSED (N/A sentinel). "
        "It is NOT healthy — means no formula, missing data, or NaN. "
        "Do not treat 101 as good.",
        "assessment_highlights excludes score 101. "
        "diagnosis.json may list p5/median/p95 with score 101 for informational metrics.",
    ]
