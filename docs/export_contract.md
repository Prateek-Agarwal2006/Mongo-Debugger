# FTDC Evidence Bundle Contract

Version: `1.0.0`

This contract defines the tiered evidence bundle produced by `cmd/llm-export` and consumed by the Mongo Debugger RCA backend.

## Design Principle

```text
tier_1_analyzed  -> primary input for RCA backend / LLM (mongo-ftdc findings)
tier_2_normalized -> fallback tool retrieval only
tier_3_raw        -> forensic fallback only
```

The RCA backend loads tier_1 always. Tier_2/3 are reachable only through fallback tools when analyzed evidence is insufficient.

**Why tiered?** Full normalized + raw FTDC can exceed 500 MB. The LLM receives a compact analyzed entrypoint (~11 KB `executive_context.json`) and fetches small metric slices via tools only when proof is needed. See [Evidence Guide](EVIDENCE_GUIDE.md).

## Tier 1 — Analyzed (primary)

| File | Required | Description |
|------|----------|-------------|
| `llm/executive_context.json` | yes | Compact analyzed entrypoint |
| `diagnosis/findings.json` | yes | Named issues with severity, symptoms, suggestions |
| `diagnosis/anomaly_timeline.json` | yes | Full anomaly event list |
| `diagnosis/activity_summary.json` | yes | Workload profile |
| `assessment/assessment.json` | yes | Per-metric p5/median/p95/score |
| `assessment/formulas.json` | yes | Score formulas and thresholds |
| `diagnosis/diagnosis.json` | no | Full diagnosis engine output |

### `executive_context.json` fields

- `contract_version`
- `instruction`
- `time_range`, `host`, `mongodb_version`
- `activity_summary`
- `findings` (full list)
- `top_anomaly_windows` (merged top-N, not full timeline)
- `assessment_highlights` (metrics with score 0–100 where score < 101; worst first)
- `score_semantics` (optional in export; always injected by RCA backend if missing)
- `read_order` — tier_1 files to read first
- `fallback_files` — tier_2/3 files for tool retrieval

### Assessment score semantics (simagix/mongo-ftdc)

Verified against upstream `assessment.go` and `utils.go`:

| Score | Meaning |
|-------|---------|
| **100** | Healthy — value below low watermark |
| **0** | Unhealthy — value above high watermark |
| **1–99** | Proportional between low/high watermarks (`GetScoreByRange`) |
| **101** | **Not assessed / N/A** — NOT healthy |

Score **101** is returned when:

- the metric has no entry in `FormulaMap` (e.g. `conns_active`, `conns_available`)
- the metric is missing from FTDC data
- the computed value is `NaN`
- insufficient data exists to score (e.g. empty tcmalloc series)

`assessment_highlights` and the Grafana assessment table **exclude** score 101 (unless verbose mode). `diagnosis.json` may still list p5/median/p95 alongside score 101 for informational metrics.

## Tier 2 — Normalized (fallback)

| File | Description |
|------|-------------|
| `normalized/time_series.jsonl.gz` | All normalized metric series |
| `normalized/replication_lags.json` | Per-host replication lag |
| `normalized/disk_stats.json` | Per-device disk metrics |
| `normalized/server_status.jsonl.gz` | Decoded serverStatus samples |
| `normalized/system_metrics.jsonl.gz` | Decoded systemMetrics samples |
| `normalized/replset_status.jsonl.gz` | Decoded replSetGetStatus samples |
| `normalized/server_info.json` | Host/build metadata |
| `metric_catalog.json` | Metric name index with point counts |

## Tier 3 — Raw (forensic fallback)

| File | Description |
|------|-------------|
| `raw/raw_metric_values.jsonl.gz` | Raw decoder DataPointsMap |
| `raw/raw_blocks.jsonl.gz` | Block metadata |
| `raw/raw_server_info.jsonl.gz` | Type-0 metadata per file |

## Bundle metadata

| File | Description |
|------|-------------|
| `manifest.json` | Authoritative run metadata (written atomically at end) |
| `bundle_index.json` | All files with tier, size, sha256 |
| `validation.json` | Completeness and consistency checks |
| `llm/fallback_retrieval_index.json` | Metric → source file → time window for tool calls |
| `manifest.pre.json` | Non-authoritative checkpoint during export |

## Read order for RCA backend

1. `manifest.json` — scope and counts
2. `llm/executive_context.json` — analyzed entrypoint
3. `diagnosis/findings.json` + `diagnosis/anomaly_timeline.json`
4. `assessment/assessment.json` — on demand
5. Fallback tools → tier_2/3 slices

## Export tiers (`-tier` flag)

| Tier | Includes |
|------|----------|
| `analyzed` | tier_1 only + metadata |
| `normalized` | tier_1 + tier_2 (default) |
| `forensic` | tier_1 + tier_2 + tier_3 raw |

Raw export is off by default (`-raw=false`). Use `-tier=forensic` or `-raw=true` for full raw decoder output.

## Validation

`validation.json` is written at export completion. Fields:

| Field | Description |
|-------|-------------|
| `valid` | `true` when all required tier files exist and counts match manifest |
| `errors` | Blocking issues (empty array when none) |
| `warnings` | Non-blocking issues (empty array when none) |
| `checks` | Per-check pass/fail details |

The RCA backend coerces `null` errors/warnings to empty arrays for backward compatibility.

## Manifest fields

`manifest.json` is written atomically at the end of export. Key fields:

| Field | Description |
|-------|-------------|
| `contract_version` | `1.0.0` |
| `run_id` | Shared identifier matching report and export |
| `export_tier` | `analyzed`, `normalized`, or `forensic` |
| `time_range` | `{ from, to }` ISO 8601 |
| `file_count` | Number of FTDC files processed |
| `metric_count` | Number of normalized metric series |
| `finding_count` | Number of diagnosis findings |
| `anomaly_count` | Number of anomaly events |
| `includes_raw` | Whether tier_3 raw was exported |

## Fallback retrieval index

`llm/fallback_retrieval_index.json` is a **JSON array** of lookup entries (no metric values). Each entry maps a metric name to a tier_2 source file and optional time-window hint.

Full field reference: [FALLBACK_INDEX.md](FALLBACK_INDEX.md)

Example catalog entry:

```json
{
  "metric": "cpu_idle",
  "source": "time_series",
  "source_file": "normalized/time_series.jsonl.gz",
  "tier": "tier_2_normalized",
  "window": {
    "from": "2026-06-02T17:29:03.004Z",
    "to": "2026-06-03T10:26:44.002Z",
    "duration_seconds": 61060.998
  },
  "points": 54872
}
```

Example anomaly-linked entry (narrow window + finding):

```json
{
  "metric": "repl_lag_host-1",
  "source": "replication_lags",
  "source_file": "normalized/replication_lags.json",
  "tier": "tier_2_normalized",
  "window": {
    "from": "2026-06-03T09:28:56Z",
    "to": "2026-06-03T10:10:56Z",
    "duration_seconds": 2520
  },
  "related_finding": "Replication Lag Issues"
}
```

Built from: (1) `metric_catalog` — full series metadata; (2) top 25 anomaly windows — drill-down hints with `related_finding`.

The RCA backend uses this index for file routing in `get_metric_window` and `get_normalized_series`. Time filtering uses API query params, not the index window automatically.

## Consumer contract (RCA backend)

1. Load `manifest.json` — fail if missing or `validation.valid` is false (with warnings allowed).
2. Load `llm/executive_context.json` — primary analyzed entrypoint.
3. Serve tier_1 on `/context` and `/tier1` endpoints.
4. Expose tier_2/3 only through fallback tools with retrieval budget.
5. Never re-run diagnosis rules or re-derive scores from raw data.

## Versioning

| Version | Changes |
|---------|---------|
| `1.0.0` | Initial tiered contract: executive_context, fallback_retrieval_index, bundle_index, validation, atomic manifest |

Breaking changes increment the major version. The RCA backend checks `contract_version` in manifest and executive_context.

## Related documentation

- [Evidence Guide](EVIDENCE_GUIDE.md) — why the bundle is structured for LLM optimization
- [Fallback Index Reference](FALLBACK_INDEX.md) — field-by-field index documentation
- [Project Architecture](ARCHITECTURE.md)
- [RCA Backend API](RCA_BACKEND.md)
- [Operations Guide](OPERATIONS.md)
- [Phase 2 LLM](PHASE2_LLM.md)
