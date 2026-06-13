# Evidence Bundle Guide — Why It Is Structured This Way

This guide explains **why** the export bundle is tiered and slimmed down, and **where each important field comes from**. It is written for engineers and LLM integrators who need to understand the optimization design—not just the file list.

## The problem we are solving

A single FTDC incident can produce:

| Artifact | Approximate size | Problem for LLM |
|----------|------------------|-----------------|
| Raw decoder values | 500 MB+ | Cannot fit in context |
| Normalized time series | ~20 MB+ gzip | Too large to dump wholesale |
| Full anomaly timeline | 164 events | Noisy; duplicates executive summary |
| Full diagnosis.json | 56 KB+ | Redundant with split tier_1 files |

**Goal:** The LLM should receive **mongo-ftdc's conclusions first** (~10–50 KB), and fetch **exact metric proof slices** only when needed (hundreds of points, not millions).

```text
WITHOUT optimization (bad):
  LLM ← entire normalized/time_series.jsonl.gz + raw FTDC

WITH tiered contract (this project):
  LLM ← executive_context.json (~11 KB)
  LLM → tool call → 50–500 points around 09:28 UTC only
```

---

## Design principles

### 1. Analyzed first, raw never by default

mongo-ftdc already computed findings, scores, and anomaly windows. The LLM must **not** rediscover health from raw metrics.

| Tier | Role | LLM loads into context? |
|------|------|-------------------------|
| **tier_1_analyzed** | Findings, top windows, assessment highlights | **Yes — always start here** |
| **tier_2_normalized** | Exact time series on disk | **No — tool slices only** |
| **tier_3_raw** | Forensic decoder output | **No — opt-in forensic only** |

### 2. Summarize at the edge, prove on demand

| Full data | Compact substitute | Savings |
|-----------|-------------------|---------|
| 164 anomaly events | `top_anomaly_windows` (15) | ~90% fewer events in context |
| 72+ scored metrics | `assessment_highlights` (≤25, score &lt; 101) | Worst metrics only |
| 87 metric series files | `fallback_retrieval_index` pointers | Index only; no values in JSON |
| `diagnosis.json` (all-in-one) | Split: findings + activity_summary + optional full diagnosis | LLM reads splits first |

### 3. Backend is a pipe, not a brain

The RCA backend:

- Loads tier_1
- Assembles prompt context
- Exposes fallback tools with a **retrieval budget** (12 calls)
- Does **not** interpret or correlate

### 4. One run_id links human report + machine export

Prevents mismatched time windows between HTML report and LLM bundle.

---

## Read order (what the LLM should see)

```text
1. llm/executive_context.json     ← START (~11 KB entrypoint)
2. (optional) diagnosis/findings.json   ← same findings, canonical file
3. Tool calls if proof needed:
     GET /tools/metric-window?metric=repl_lag_host-1&start=...&end=...
4. Never: load entire normalized/ or raw/ into prompt
```

The `instruction` field in `executive_context.json` states this explicitly.

---

## File-by-file: purpose, optimization, field origins

### `llm/executive_context.json` — LLM entrypoint

**Why it exists:** Single compact document so the LLM does not open 10 tier_1 files.

| Field | Source | Optimization |
|-------|--------|--------------|
| `instruction` | Written by `cmd/llm-export` | Tells LLM: analyzed first, tools for proof |
| `findings` | `Diagnosis.Run()` → all fired rules | Full list (only 4 in sample—not truncated) |
| `top_anomaly_windows` | Top 15 from 164 anomalies, ranked by duration + severity | **Truncated** — worst windows only |
| `assessment_highlights` | Metrics with score &lt; 101, worst 25 | **Filtered** — excludes N/A (101) scores |
| `activity_summary` | `computeActivitySummary()` medians/p95 | One number per category, not time series |
| `read_order` / `fallback_files` | Static pointers in exporter | Tells integrator what exists without loading |
| `score_semantics` | Exporter + RCA backend | Prevents misreading 101 as healthy |

**Ranking for top anomaly windows** (`buildTopAnomalyWindows`):

```text
score = duration_seconds
+ 1,000,000 if severity = critical
+   100,000 if severity = warning
→ sort descending → take top 15
```

---

### `diagnosis/findings.json` — Named problems

**Why separate from executive_context:** Canonical tier_1 file; same content as `executive_context.findings`.

| Field | How calculated |
|-------|----------------|
| `name`, `description`, `severity`, `suggestion` | Static `DiagnosisRules` in `diagnosis.go` |
| `symptoms` | Rule's `Symptoms()` using p5/p95/score + anomaly timing text |
| `score` | Worst related metric score for that rule |
| `detected_at` | Latest related anomaly timestamp, else analysis `to` time |

**LLM optimization:** 4 findings ≈ 2 KB. No raw metrics.

---

### `diagnosis/anomaly_timeline.json` — Full threshold violations

**Why it exists:** Complete forensic timeline (164 events). **Not** loaded into LLM context by default.

| Field | How calculated |
|-------|----------------|
| `Timestamp` | First sample where metric crossed threshold |
| `EndTime` | Last sample before return to normal |
| `Duration` | Nanoseconds (`EndTime - Timestamp`) |
| `Metric` | Series name (`cpu_idle`, `repl_lag_host-1`, …) |
| `Peak` | Worst value in window (max if above threshold, min if below) |
| `Threshold` | Human label from hardcoded rules (`> 5s`, `< 30%`) |
| `Severity` | Per-rule label (`critical` for repl lag, `warning` for CPU) |

**Detection:** `collectAnomalies()` walks normalized points; keeps windows ≥ 10 seconds.

**LLM optimization:** Use `executive_context.top_anomaly_windows` (15) in context; load full timeline only for deep forensic review.

---

### `diagnosis/diagnosis.json` — All-in-one diagnosis dump

**Why it exists:** Debugging and offline analysis. **Optional** for LLM.

| Section | Contents | Field origins |
|---------|----------|---------------|
| `from` / `to` / `duration_seconds` | Incident window | FTDC file time range |
| `activity_summary` | Workload snapshot | Same as standalone `activity_summary.json` |
| `metrics` | 72 metrics × {p5, median, p95, score} | `computeMetrics()` + assessment engine |
| `disk_metrics` | Per-device iops + util | `DiskStats` + scoring |
| `repl_metrics` | Per-host lag stats | `ReplicationLags` + scoring |
| `anomalies` | Duplicate of anomaly_timeline | Same 164 events |
| `findings` | Duplicate of findings.json | Same 4 findings |

**LLM optimization:** Prefer splits (`findings.json`, `activity_summary.json`) over loading this 56 KB+ monolith.

---

### `diagnosis/activity_summary.json` — Workload headline numbers

**Why it exists:** Quick “what was the server doing” without 72 metric entries.

| Field | Statistic used | Source metric |
|-------|----------------|---------------|
| `Ops*` | median | `ops_query`, `ops_update`, … |
| `Latency*` | p95 | `latency_read`, … |
| `ScanKeys` / `ScanObjects` | p95 | scan metrics |
| `CPU*` | median | `cpu_user`, `cpu_idle`, … |
| `MemResident` / `CacheUsed` | median % | mem / WT cache |
| `DiskUtil` | max p95 across disks | disk utilization |
| `Conns*` | median | connection metrics |

**Caveat:** Medians can look healthy while p5/p95 in `metrics` show spikes (e.g. CPUIdle median 97% but p5=2%).

---

### `assessment/assessment.json` — Scored metrics table

**Why it exists:** Grafana-style health table. Sorted by score (worst first).

Rows: `Metric | Score | p5 | Median | p95`

**LLM optimization:** `executive_context.assessment_highlights` is the filtered subset (score &lt; 101, max 25).

**Score 101:** Not assessed (no formula, NaN, missing data)—**not healthy**. See [export contract](export_contract.md).

---

### `llm/fallback_retrieval_index.json` — Proof lookup table

**Why it exists:** Tells the RCA backend **where** tier_2 data lives and **which time windows** matter—without putting metric values in the index.

**Not loaded into LLM context.** Used by tools and as drill-down hints.

Two row types merged (138 entries in sample):

#### Type A — Catalog rows (~100)

From `buildMetricCatalog(stats)` after FTDC decode.

| Field | Calculation |
|-------|-------------|
| `metric` | `ts.Target` or `disk.{dev}.{field}` or `replication_lag.{host}` |
| `source` | `time_series` / `disk_stats` / `replication_lags` |
| `source_file` | Static map → `normalized/*.json(l.gz)` |
| `tier` | Always `tier_2_normalized` |
| `window.from/to` | First/last sample timestamp (ms) in series |
| `window.duration_seconds` | `to - from` |
| `points` | `len(datapoints)` |

#### Type B — Anomaly rows (25)

From `buildTopAnomalyWindows(diagnosis.Anomalies, 25)`.

| Field | Calculation |
|-------|-------------|
| `metric` | `AnomalyEvent.Metric` |
| `source` / `source_file` | `repl` in name → `replication_lags.json`, else `time_series.jsonl.gz` |
| `window` | Anomaly `from`/`to` (narrow spike window, not full 17h) |
| `related_finding` | Keyword match: `repl`→Replication, `cpu`→CPU Saturation, etc. |
| `points` | Omitted (hint only) |

**Duplicate metric names are intentional** (e.g. 21× `cpu_idle`): one catalog row + many anomaly-window bookmarks.

**Tool behavior:** `get_metric_window` uses index for **file routing**; time filter comes from API `start`/`end` params. Use index `window` + `related_finding` as **suggested** drill-down ranges.

---

### `normalized/` — Tier_2 proof on disk

| File | Contents | LLM access |
|------|----------|------------|
| `time_series.jsonl.gz` | One line per metric: `{target, datapoints:[[v,ts_ms],...]}` | Tool slice only |
| `replication_lags.json` | Per-host lag series | Tool slice only |
| `disk_stats.json` | Nested per-device metrics | Tool slice only |
| `server_status.jsonl.gz` | Decoded serverStatus docs | Forensic / rare |
| `metric_catalog.json` | Name, source, point count | Index helper (no values) |

**Sample sizes:** `time_series` ~20 MB gzip; `replication_lags` ~623 KB; `disk_stats` ~77 MB.

---

## Size comparison (sample run `phase1test20260609T133314Z`)

| What LLM loads first | Size |
|----------------------|------|
| `executive_context.json` | ~11 KB |
| `findings.json` | ~2 KB |
| `/phase2/package` prompt + context | ~15–30 KB |
| One tool call (500 points) | ~5–20 KB |
| **vs** full `time_series.jsonl.gz` | **~20 MB** |
| **vs** raw export (forensic tier) | **~500 MB+** |

---

## Retrieval budget (why 12 tool calls)

Prevents runaway context growth:

- Each `get_metric_window` returns at most `limit` points (default 500)
- Max 12 calls per orchestrator session → HTTP 429 when exhausted
- LLM must finalize RCA from tier_1 if budget runs out

---

## What we deliberately do NOT give the LLM

| Excluded | Reason |
|----------|--------|
| Full `anomaly_timeline.json` in prompt | 164 events; top 15 in executive_context |
| Full `diagnosis.json` in prompt | Redundant; use splits |
| `metric_catalog.json` values | No values—catalog only |
| `bundle_index.json` / `validation.json` | Ops metadata |
| Entire `normalized/` directory | Tool slices only |
| `raw/` by default | Forensic opt-in |

---

## Related documentation

- [Architecture](ARCHITECTURE.md) — role split
- [Export contract](export_contract.md) — schema reference
- [Phase 2 LLM](PHASE2_LLM.md) — integration loop
- [RCA Backend API](RCA_BACKEND.md) — tool endpoints
