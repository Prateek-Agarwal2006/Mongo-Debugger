# Fallback Retrieval Index — Field Reference

`llm/fallback_retrieval_index.json` is a **JSON array** of lookup entries. It contains **no metric values**—only pointers to tier_2 files and time-range hints.

See [Evidence Guide](EVIDENCE_GUIDE.md) for the full optimization rationale.

## Why this file exists

```text
tier_1 tells the LLM WHAT happened (findings, top windows)
fallback_retrieval_index tells tools WHERE to fetch proof (file + metric + window hint)
normalized/* holds the actual numbers (too big for LLM context)
```

Without this index, fallback tools would scan 20 MB `time_series.jsonl.gz` blindly.

## Pipeline

```text
diagnostic.data
  → FTDCStats (TimeSeriesData, ReplicationLags, DiskStats)
  → buildMetricCatalog()           → ~100 catalog entries
  → diagnosis.Anomalies            → 164 events
  → buildTopAnomalyWindows(25)     → top spike windows
  → buildFallbackRetrievalIndex()  → merge + sort → write JSON
```

Implementation: `simagix-workspace/repos/mongo-ftdc/cmd/llm-export/main.go`

## Entry shape

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

Optional fields: `points` (catalog only), `related_finding` (anomaly rows only).

## Field origins

| Field | Catalog rows | Anomaly rows |
|-------|--------------|--------------|
| `metric` | `buildMetricCatalog` name | `AnomalyEvent.Metric` |
| `source` | `time_series` / `disk_stats` / `replication_lags` | `repl` in name → `replication_lags`, else `time_series` |
| `source_file` | Static map in exporter | Static map |
| `tier` | Literal `tier_2_normalized` | Same |
| `window` | First/last sample ts in series | Anomaly start/end |
| `points` | `len(datapoints)` | Omitted |
| `related_finding` | Omitted | Keyword match to `findings.json` |

## `related_finding` matching rules

| Metric contains | Finding name contains | Result |
|-----------------|----------------------|--------|
| `repl` | `replication` | e.g. Replication Lag Issues |
| `cpu` | `cpu` | e.g. CPU Saturation |
| `write` | `write` | Write contention finding |
| `scan` or `query` | `index` | e.g. Missing Indexes |

## RCA backend usage

| API | Uses index for |
|-----|----------------|
| `GET /tools/fallback-metrics` | List unique `metric` names |
| `GET /tools/metric-window` | Pick source file reader; **not** auto window |
| `GET /tools/normalized-series` | Batch metric-window |

Time filtering uses query params `start`/`end`, not index `window` automatically. Index `window` is a **hint** for the LLM (especially with `related_finding`).

## Sample run stats (`phase1test20260609T133314Z`)

| Metric | Count |
|--------|-------|
| Total entries | 138 |
| `time_series` source | 107 |
| `disk_stats` source | 24 |
| `replication_lags` source | 7 |
| With `related_finding` | 25 |
| Duplicate metrics | `cpu_idle` (21), `repl_lag_host-1` (5) |

## Empty index

When `export_tier=analyzed`, the index is `[]` because tier_2 files are not exported.
