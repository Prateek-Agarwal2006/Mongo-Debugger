# FTDC Data Funnel — what mongod captures, what simagix keeps, what we do about the rest

> Companion to [FTDC_REFERENCE.md](FTDC_REFERENCE.md) (long-form research) and
> [PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md) (PG migration decisions).
> This doc answers three questions with numbers from a real run
> (`upload20260625T131510Z`: 21 files, 193 MB, ~17.5 h of data):
>
> 1. What is inside an FTDC file, byte by byte?
> 2. How does simagix reduce ~5,000 captured paths to the 89 series we store — and why?
> 3. What is our plan to make **all** captured data reachable by the Phase 2 agent?

---

## Part 1 — FTDC file structure

### 1.1 The directory

```
diagnostic.data/
├── metrics.2026-06-23T22-17-02Z-00000     10.4 MB   covers 22:17 → 23:07
├── metrics.2026-06-23T23-07-38Z-00000     10.5 MB   covers 23:07 → 23:58
├── ...                                    (~10 MB each)
├── metrics.2026-06-24T13-25-22Z-00000      2.5 MB   final file, still growing
└── metrics.interim                                  newest samples, not yet rolled
```

Facts that matter for engineering:

- **Rotation is size-based (~10 MB), not time-based.** ~50 min/file is typical for
  this server, but a server with more collections (more paths) rotates faster.
  Never assume duration — measure it.
- **The filename embeds the first sample's timestamp.** The directory listing is a
  free coarse time index.
- **Every file is independently decodable.** No cross-file state. The file is the
  natural retrieval unit.
- **mongod restarts cut a file short** and may leave a coverage gap (server down).
- **The last file may end in a truncated chunk** (crash mid-write). Decoders must
  treat a corrupt tail as end-of-data, not as an error.
  **⚠️ simagix's own `ReadAllMetrics` (`decoder/metrics.go:26–32`) does NOT do
  this** — it computes `buffer[pos:pos+length]` unchecked and will panic on a
  short final doc. Our `ftdc-slice` binary guards this: `pos+length > len(buffer)`
  → stop and mark `coverage_gap: truncated_tail`. This matters most for the last
  file, which is the one every incident query touches.

### 1.2 Inside a file: BSON docs back to back

```
metrics.2026-06-24T08-45-38Z-00000
├── [type 0]  metadata doc      buildInfo, getCmdLineOpts, hostInfo (config snapshot)
├── [type 1]  metric chunk      ~300 samples, zlib-compressed     (08:45–08:50)
├── [type 1]  metric chunk      ~300 samples                      (08:50–08:55)
├── ...                         (~10 chunks per file)
└── [type 1]  metric chunk      possibly truncated
```

- Type 0: static metadata, captured at file start (and on config changes).
- Type 1: a **metric chunk** — a BSON doc whose `data` field is a zlib-compressed
  block, plus a chunk start timestamp readable **without decompressing**.
  One chunk = up to 300 consecutive 1-per-second samples ≈ 5 minutes.

The readable chunk timestamp means a decoder can skip whole chunks outside the
requested window without paying decompression cost.

### 1.3 Inside a chunk: one reference doc + delta columns

Decompress `data` and you get:

```
┌────────────────────────────────────────────────────────────┐
│ REFERENCE DOC (full BSON sample #1 — every path + value)   │
│   serverStatus.opcounters.insert          = 8102455        │
│   serverStatus.locks.Collection.acquireCount.r = 44210     │
│   systemMetrics.disks.nvme1n1.io_time_ms  = 991822         │
│   ... several thousand paths (≈5,000 typical)              │
├────────────────────────────────────────────────────────────┤
│ metricCount = N,  sampleCount = up to 299                  │
├────────────────────────────────────────────────────────────┤
│ DELTA COLUMNS — one per path, in reference-doc key order   │
│   path₁:  +3 +5 +2 +4 ...       (varint, zigzag)           │
│   path₂:  0×299                 (unchanged → ~2 bytes RLE) │
│   path₃:  +12 +9 +840 +7 ...                               │
└────────────────────────────────────────────────────────────┘
```

- The **reference doc** defines which paths exist in this chunk and their starting
  values. Flatten its nested keys with dots → the canonical path names.
- The remaining samples are stored **column-major as deltas**: "how much did this
  number change since the previous second." Most metrics are unchanged most
  seconds, so most columns are runs of zeros — that's the compression.
- Reconstructing `path₃` at second N = reference value + sum of its first N
  deltas. Other columns are never touched.
- If the path set changes mid-run (new collection ⇒ new lock-stat paths), FTDC
  starts a fresh chunk with a bigger reference doc. **Path sets can differ across
  chunks** — always match paths by name, never by column position.

**Nothing is dropped at this level.** Every path mongod captures is in every chunk.
All dropping happens downstream, in the decoder that chooses what to export.

---

## Part 2 — The simagix funnel: ~5,000 paths → 89 series

simagix/mongo-ftdc is a *DBA incident dashboard + auto-playbook* tool, not a
forensic archiver. Its filter, applied in four code stages
(`simagix-workspace/repos/mongo-ftdc/`):

```
~5,000 FTDC paths          (everything mongod captures)
   │  attribs.go — extracts exactly 79 typed paths into
   │  ServerStatusDoc / SystemMetricsDoc / ReplSetStatusDoc
   ▼
79 extracted paths
   │  time_series_data.go — flattens/derives chart targets:
   │  counters → rates (bytesIn → net_in), per-member repl lags,
   │  per-disk util/iops, WT cache, queues, tcmalloc, flow control
   ▼
89 chart targets           (normalized/time_series.jsonl.gz — what our
   │                        metrics table stores; count varies with
   │                        member/disk count)
   │  assessment.go — FormulaMap scores each metric 0–100
   │  against p5/median/p95 watermarks
   ▼
scored metrics             (assessment/assessment.json)
   │  diagnosis.go — AnomalyThreshold rules (latency > x ms,
   │  disk util > 70%, repl lag > 5 s, cpu idle < 30%, …)
   ▼
named findings             (diagnosis/findings.json → "Disk I/O
                            Bottleneck", "Replication Lag", …)
```

### 2.1 What simagix is optimizing for (why the funnel exists at all)

The dropping is deliberate product design — not random, but also not published as
a rationale doc. simagix/mongo-ftdc is built as a **MongoDB performance
troubleshooting tool, not a forensic dump of all FTDC**. Four product goals drive
every keep/drop decision:

1. **Grafana dashboards** — charts need short metric names + clean numeric time
   series. Deep nested paths with hundreds of siblings make unusable panels.
2. **Assessment scoring** — each kept metric gets p5/median/p95 watermarks and a
   0–100 score (`FormulaMap`). A metric only earns a slot if a sensible
   threshold exists for it.
3. **Diagnosis playbooks** — named findings like "Disk I/O Bottleneck" or
   "Replication Lag" fire from specific metrics crossing specific thresholds
   (repl lag > 5 s, disk util > 70 %, CPU idle < 30 %). Kept metrics are the
   ones consultants actually look at in incidents.
4. **Speed/size** — FTDC's whole point is compressing ~1 sample/sec for days
   into ~200–500 MB; a tool that re-expands everything defeats it.

So the filter is: *"does this help a DBA spot common MongoDB problems quickly?"* —
not *"export every path Mongo ever captures."*

**Where the choices live (code, not vibes):**

| Code / artifact | What it decides |
|---|---|
| `attribs.go` | which FTDC paths get typed fields in `ServerStatusDoc` / `SystemMetricsDoc` (exactly 79) |
| `time_series_data.go` | which fields become chart targets (`cpu_idle`, `wt_cache_used`, …) |
| `assessment.go` + `FormulaMap` | which metrics get health scores + low/high watermarks |
| `diagnosis.go` + threshold rules | which metrics trigger which named findings |

A path is kept when it feeds **charts + scores + rules**; dropped when it's noise
for that workflow.

**Not everything "missing" was dropped — some was transformed:**

```
flowControl/enabled (bool)   → not a numeric series → excluded by type, not judgment
network/bytesIn (counter)    → converted to net_in rate (more useful than raw counter)
per-member repl optimes      → computed into replication_lags seconds
```

**What simagix did not publish:** there is no official "why we drop
`serverStatus/metrics/cursor/open`" document. The reasoning is engineering
judgment baked into which Grafana panels exist, which metrics MongoDB
consultants reach for in incidents, and what can be scored with sensible
thresholds. This doc (and [FTDC_REFERENCE.md](FTDC_REFERENCE.md)) reverse-engineer
that intent from the code.

**One-line truth:**

```
Raw FTDC  = Mongo captured everything        (support/debug mindset)
simagix   = curated DBA incident dashboard   (auto-playbook mindset)
```

### 2.2 What survives (the 89), grouped

| Group | Series (examples) | Playbook it feeds |
|---|---|---|
| Connections | `conns_active/available/created/s/current` | Connection pool misconfiguration |
| CPU | `cpu_idle/iowait/system/user/steal/...` | CPU saturation |
| Disk | `disks_iops`, `disks_utils`, `io_in_progress`, `io_queued_ms`, `read/write_time_ms` | Disk I/O bottleneck |
| Ops & docs | `ops_*`, `doc_*` per-second rates | Workload shape |
| Latency | `latency_command/read/write` | Latency anomalies |
| Memory | `mem_resident/virtual/page_faults` | Memory pressure |
| tcmalloc | `tcmalloc_allocated/heap/in_use/physical` | Memory fragmentation |
| Network | `net_in/out`, `net_physical_*`, `net_requests` | Network saturation |
| Queues/tickets | `q_*`, `queues_*`, `ticket_avail_*` | Admission control stalls |
| Replication | `repl_0..N` (per member), `replication_lags` | Replication lag |
| Flow control | `flowctl_*` | Flow control activated |
| Scans/targeting | `scan_keys/objects/sort`, `query_targeting_*` | Missing indexes |
| Transactions | `txn_*` | Transaction pileups |
| WiredTiger | `wt_cache_*`, `wt_blkmgr_*`, `wt_dhandles_active`, `wt_*_evicted` | Cache pressure, checkpoint stalls |
| Write conflicts | `write_conflicts/s` | Contention |

### 2.3 What is dropped, and the reason per category

| Dropped category (examples) | Why simagix skips it | When you'd miss it |
|---|---|---|
| Per-command counters (`metrics.commands.<cmd>.total/failed` — hundreds of paths) | `ops_*` rates summarize workload; hundreds of mostly-zero series are dashboard noise | "Which command class caused the 09:06 spike?" |
| Deep lock trees (`locks.<resource>.acquireCount/timeAcquiringMicros.<mode>`) | Too granular to threshold generically | Lock storms, namespace-level contention |
| Cursor metrics (`metrics.cursor.open.*`, timed-out histograms) | Niche | Cursor leak hunts |
| Asserts (`asserts.regular/warning/msg/user`) | Usually flat 0 | Server instability / bug hunts |
| Oplog `collStats` (`local.oplog.rs` size/window) | Not part of its chart model | "Is lag caused by a too-small oplog window?" |
| Full `replSetGetStatus` detail (`pingMs`, `syncSourceHost`, heartbeat ages) | Keeps only computed lag seconds per member | "Is lag network vs apply vs source choice?" |
| `getParameter` / config snapshots (type 0 docs) | Static, not a time series | "Did someone change flowControl mid-incident?" |
| WT internals beyond cache/blkmgr (session/txn/log subsystems) | Curated subset covers common cases | Checkpoint stall forensics |
| Non-numeric fields (`flowControl.enabled` bool, host strings) | Chart pipeline is numeric-only | Config-state questions |

The consistent rule: **kept if it feeds a Grafana panel, a score formula, or a
diagnosis rule; dropped otherwise.** It is opinionated curation for the ~80–90 %
of incidents that are CPU / disk / memory / connections / repl-lag shaped — not a
completeness guarantee.

### 2.4 Usefulness triage of the drops — are they actually needed?

Not all drops are equal. Think of them in three buckets:

```
Dropped in raw → normalized
        │
        ├── Mostly noise for incident RCA     (safe to drop)
        ├── Sometimes useful for deep debug   (nice to have raw)
        └── Critical for specific bug classes (raw matters)
```

**Bucket 1 — usually NOT useful for standard RCA (dropping is fine):**

| Dropped | Why skipping is OK | RCA impact |
|---|---|---|
| Per-command counters | `ops_query` / latency already summarize workload | low for "why was disk slow?" |
| Deep lock trees | very granular, hard to threshold | low unless lock storm suspected |
| Cursor lifetime histograms | niche | low unless cursor-leak hunt |
| `getParameter` snapshots | static config; live `getParameter` is better | low for time-series RCA |
| Oplog `collStats` | oplog sizing, not CPU/disk spikes | low for typical findings |
| Assert counters | often flat 0 | low unless crash/assert investigation |

For a typical run (disk bottleneck + tcmalloc fragmentation + repl lag), the
signals that matter were all kept — `disks_*`, `replication_lags`, `tcmalloc_*`,
`flowctl_*`. The drops don't block the primary findings.

**Bucket 2 — sometimes useful (normalized is thin, raw helps):**

| Dropped / partial | When it matters |
|---|---|
| Full `replSetGetStatus` (`pingMs`, `syncSourceHost`, `lastHeartbeat`) | "Is lag network vs apply vs source?" |
| More WT session/transaction/log paths | checkpoint stalls, WT internal contention |
| Per-command failure counts | "did a specific command class fail more?" |
| Full lock stats | write contention on specific namespace patterns |
| Oplog collStats | "lag because oplog window too small?" |

These are **second-order questions** — after tier 1 says *what* looks bad, you
may need raw to explain *mechanism*.

**Bucket 3 — the honest gap (dropped data that can change a diagnosis):**

- **Oplog / replication mechanics** — lag with healthy disk/CPU sometimes needs
  oplog stats + repl member metadata (sync source, heartbeat), not just lag
  seconds.
- **Command-level spikes** — one bad aggregation pattern won't show in
  `ops_query` alone; per-command FTDC paths can.
- **Lock / admission-control deep dives** — we have queue/ticket series but not
  full lock trees; rare stall cases need them.
- **Config drift** — FTDC's `getParameter` snapshot is historical evidence if
  someone changed flowControl or cache size mid-incident.

So the drops are: **collectively mostly irrelevant** for standard performance RCA
(~80–90 % of incidents), **individually decisive** for specific deep dives (the
remaining 10–20 %). Was simagix wrong to drop them? No — for a Grafana +
auto-diagnosis tool, curation is the right tradeoff. Was it wrong to gate raw
behind an opt-in (`-tier=forensic`)? Also no — raw is huge; you enable it when
the question gets sharp enough to need path-level forensics.

**Rule of thumb by question type:**

| Question | Enough with curated tiers? |
|---|---|
| Disk / CPU / memory / repl lag / connections / flow control | yes (tier 1 + tier 2) |
| "Prove the spike at 09:06 UTC" | yes (`get_metric_window`) |
| "Which command / namespace / lock caused it?" | often no — needs raw |
| "Was oplog or sync source the repl issue?" | partial — lag yes, mechanism dropped |

### 2.5 So are the 89 enough?

- **For detection ("what & when"): yes.** Every playbook-class incident surfaces
  in the curated series; that's what they were selected for.
- **For mechanism ("which command / collection / lock / sync source"): often no.**
  The evidence for second-order questions lives exclusively in dropped paths.
- Verdict: 89 is the right *fast tier*, wrong *only tier*. Detection needs
  curation; attribution sometimes needs the raw paths. Hence Part 3.

---

## Part 3 — Our design: every captured byte reachable, nothing bulky duplicated

Design decided in session (2026-07-14), targeted at the K8s/no-PVC deployment.
Principle: **keep the source bytes, decode on demand.** Raw FTDC is already
delta-encoded + zlib-compressed — it is its own best storage format. Decoding
everything up-front would multiply 200–500 MB into billions of PG rows, 95 % of
which no investigation ever reads.

### 3.1 Storage

```sql
CREATE TABLE raw_files (
    run_id    TEXT   NOT NULL,
    kind      TEXT   NOT NULL,   -- 'ftdc' | 'mongolog'
    filename  TEXT   NOT NULL,   -- metrics.2026-06-24T08-45-38Z-00000
    chunk_no  INT    NOT NULL,   -- 8 MB bytea slices (row-size hygiene only)
    data      BYTEA  NOT NULL,
    PRIMARY KEY (run_id, kind, filename, chunk_no)
);

CREATE TABLE raw_file_index (
    run_id    TEXT NOT NULL,
    filename  TEXT NOT NULL,
    start_ts  DOUBLE PRECISION NOT NULL,  -- measured from first chunk header
    end_ts    DOUBLE PRECISION NOT NULL,  -- measured, never inferred from name
    bytes     BIGINT NOT NULL,
    PRIMARY KEY (run_id, filename)
);
```

Plus two evidence keys built at ingest by decoding **the last chunk of the last
FTDC file** (late, because path sets grow over a run — new collections add new
lock-stat paths):

```json
// evidence key: raw_path_catalog
// Path separator is "/" — this is how simagix's decoder emits keys
// (decoder/decode.go:17). NOT dots. All agent tool inputs must use "/".
{ "path_count": 5124, "paths": ["serverStatus/asserts/regular", "..."] }

// evidence key: raw_path_prefix_map
// Precomputed taxonomy — ~50–100 buckets, none exceeding ~500 entries.
// Served by list_raw_paths() with no args. See §3.3.
{
  "total_paths": 5124,
  "prefixes": [
    {"prefix": "serverStatus/metrics/commands/*", "count": 487},
    {"prefix": "serverStatus/wiredTiger/cache/*", "count": 73},
    ...
  ]
}
```

Why last chunk of last file: a collection created at hour 6 of a 12-hour
capture won't appear in early reference docs but will in late ones. Choosing
the tail chunk guarantees the catalog is a superset of every path that ever
existed in the run. Cost: one zlib + one BSON parse at ingest.

### 3.2 Upload streaming (also fixes the crash-mid-upload gap)

1. Multipart body streams to pod-local temp; archive extracted there.
2. Each extracted file → 8 MB slices → `raw_files`, one transaction per file.
3. After the last file commits, a completion marker is written; only then is the
   phase 1 job enqueued. Pod dies earlier ⇒ no marker, no job, no corrupt run.
4. Worker claims job → `SELECT ... ORDER BY chunk_no` → reassembles files onto
   **ephemeral local disk** → runs the unchanged phase 1 pipeline → ingests
   metrics/evidence → builds `raw_file_index` + `raw_path_catalog` → deletes
   scratch. Disk is never the source of truth; there is no PVC.
5. `ftdc_retry` / `hatchet_retry` re-materialize from `raw_files`, so retry
   works even after the pod that took the upload is gone.

### 3.3 Agent tools (tier 3) — three layers by cost

The naïve design was one tool: pattern in, series out. That collapses two
concerns — *discovery* (what paths exist) and *retrieval* (get their values) —
into a single call. We split them into three layers, each cheaper than the
next and reused as needed.

```
Layer          Tool                          Cost           Returns
──────────────────────────────────────────────────────────────────────
taxonomy       list_raw_paths()              ~500 tokens    ~50–100 prefix buckets
names          list_raw_paths(pattern)       ~200 tokens    literal path names
values         get_raw_window(paths,ts)      real work      time series
```

The agent walks down the stack only as far as it needs. It never sees the
5,000 flat paths.

#### The rejected alternative: dump the whole catalog to the agent

The obvious question: why not just hand the agent every path in one MCP call
and let it grep in-context? Three reasons we don't:

| Concern | Dump 5,000 paths | Three-layer discovery |
|---|---|---|
| Context cost per turn | ~200 KB text ≈ **65–80K tokens** (30–40 % of context) | ~500 tokens prefix map + ~200 tokens per query |
| Prompt cache reuse | poor — tool results land mid-conversation, past the cache prefix | irrelevant — cost is already tiny |
| Injection surface | every path (collection/index/DB name) enters context every turn | bounded to what the agent asked about |
| Reasoning quality | agent grep-in-head → typos, hallucinated names | server-side literal matching → exact spellings |
| Taxonomy for reasoning | flat list is a haystack | prefix map gives the agent a real map |

The dump-all approach is not just expensive — it's *less useful*. The agent
doesn't have a mental index of 5,000 flat paths; it thinks in concepts
("commands", "locks", "cache pressure"). A taxonomy helps it think; a haystack
makes it guess.

The rejected middle option — one tool that always requires a pattern — is
almost as good, but forces the agent to guess prefixes before it has any map
of what exists. The 500 tokens for a prefix map pay for themselves the first
time the agent asks the right pattern instead of the wrong one.

#### `list_raw_paths()` — no args → prefix map

```json
{
  "prefixes": [
    {"prefix": "serverStatus/asserts/*",              "count": 5},
    {"prefix": "serverStatus/metrics/commands/*",     "count": 487},
    {"prefix": "serverStatus/metrics/cursor/*",       "count": 12},
    {"prefix": "serverStatus/wiredTiger/cache/*",     "count": 73},
    {"prefix": "serverStatus/locks/Collection/*",     "count": 38},
    {"prefix": "systemMetrics/disks/nvme1n1/*",       "count": 42},
    ...
  ],
  "total_paths": 5124,
  "note": "tier 1 (curated) exposes 89 of these ~5,124 paths — use a pattern to reach the rest"
}
```

Precomputed at ingest (`raw_path_prefix_map` evidence key), served from PG in
one query. Bucketing rule: group by first N path segments so no bucket
exceeds ~500 entries and total buckets stay near 50–100. The note at the
bottom is a permanent nudge that curated tiers are the tip of the iceberg.

#### `list_raw_paths(pattern)` — literal names

```json
// pattern = "commands/aggregate"
{
  "resolved": [
    "serverStatus/metrics/commands/aggregate/total",
    "serverStatus/metrics/commands/aggregate/failed"
  ],
  "count": 2
}
```

Python-side regex + substring fallback against `raw_path_catalog`. Zero
matches returns the 5 nearest catalog entries by edit distance so the agent
self-corrects on the next turn. **The decoder never sees a regex** — only
literal path names. No result cap; the agent asked for a pattern, it gets
every match.

#### `get_raw_window(run_id, paths, start, end)` — the actual data

`paths` is a list of literal names from `list_raw_paths(pattern)` (or a fresh
pattern the tool resolves internally). Steps:

1. Resolve any patterns → literal names against the catalog.
2. Interval-overlap query on `raw_file_index`
   (`start_ts <= win_end AND end_ts >= win_start`) → every file that overlaps
   the window. No file-count guard — the agent chose the window.
3. Scratch-cache check per file → else `SELECT ... ORDER BY chunk_no` from
   `raw_files`, reassemble to `scratch/<run_id>/raw_ftdc/<filename>` (LRU
   keeps ~3 files hot per run).
4. Exec `ftdc-slice` per file: safe outer BSON iterator (guards truncated
   tails), reference-doc peek to skip chunks outside window, reuses simagix's
   `decoder.decode()` for surviving chunks, filters `DataPointsMap` to
   matched names on emit.
5. Concatenate series across files in ts order. Attach `coverage_gaps` for
   restart holes and truncated tails.

**No budget accounting.** The phase 2 tool budget does not tick on raw tier
calls. The agent should reach for raw whenever mechanism attribution needs
it, without a countdown pressuring it back to curated paths.

Worked example. Tier 1 says "Disk I/O bottleneck 09:04–09:11":

```
agent → list_raw_paths()
        ← prefix map — sees "serverStatus/metrics/commands/* (487)"
agent → list_raw_paths("commands/(aggregate|find|getMore)")
        ← 6 literal names
agent → get_raw_window(run_id, <6 names>, "09:00", "09:15")
        ← index picks metrics.…T08-45-38Z (10 MB)
          reference-doc peek keeps 2 chunks of 10
          both chunks decoded in full (interleaved delta stream —
          all columns walked; only matched columns' values copied)
          samples filtered by ts
          ~3 KB of exactly the per-command counters returned
```

Four data-reducing layers, all cheap, three of them free from the format
itself. Column-level skip is not possible (delta stream is interleaved with
RLE-zeros), so matched-chunk CPU is proportional to *server column count*,
not query column count — ~50–200 ms per chunk on a normal server, which is
fine inside an agent turn and free on the second call thanks to the scratch
LRU.

### 3.4 Anti-bias guardrails (so the agent actually uses tier 3)

Curation biases the agent toward the 89 names. Time-anchoring is the feature;
vocabulary-anchoring is the risk. Mitigations: tool descriptions state
explicitly that tier 2 is a *subset* and the full catalog exists; the phase 2
prompt instructs "curated metrics establish what & when — check whether the
mechanism needs raw paths before concluding"; findings name their natural raw
follow-ups (disk finding → `systemMetrics.disks.*`, `metrics.commands.*`).

### 3.5 Normalized bundle files — final disposition

| File (real sizes) | Decision | Reason |
|---|---|---|
| `time_series.jsonl.gz` (23 MB gz) | **already ingested** → `metrics` table | the fast tier |
| `replset_status.jsonl.gz` (160 KB gz) | **ingest as evidence** | sync source / pingMs / member states — answers lag-mechanism questions instantly |
| `replication_lags.json` (832 KB) | **ingest as evidence** | simagix-*derived* lag computation; not reproducible from raw without reimplementing it |
| `server_info.json` (397 B) | **ingest as evidence** | host/version context, free |
| `diagnosis/diagnosis.json` | **ingest as evidence** | full per-metric p5/median/p95 + score table behind `findings` — simagix judgment, currently dropped, shouldn't be |
| `metric_catalog.json` | skip | `SELECT DISTINCT name FROM metrics` serves it |
| `server_status.jsonl.gz` (15 MB gz → 112 MB) | skip | exact re-encoding of FTDC paths; raw tier supersedes |
| `system_metrics.jsonl.gz` (13 MB gz → 150 MB) | skip | same |
| `disk_stats.json` (329 MB!) | skip | expansion of `systemMetrics.disks.*`; reachable via `get_raw_window` |
| `manifest.pre.json` | skip | intermediate; `manifest.json` supersedes |

Rule of thumb: **keep derived judgments and tiny hot summaries as evidence; keep
raw bytes as the universal fallback; never store a bulk re-encoding twice.**

### 3.6 Cost & retention

~0.5 GB of PG per run (the same bytes that used to sit on the PVC, now durable
and pod-independent). Per-run deletion is `DELETE FROM raw_files/raw_file_index
WHERE run_id = %s` — a retention sweep, consistent with the no-FK design in
PRODUCTION_ARCHITECTURE.md. Decode latency is seconds per window — acceptable
inside an agent turn, and the scratch LRU makes follow-up questions on the same
window free.

### 3.7 Why not just change simagix? — tradeoff record

The question is natural: the decoder (`decoder/decode.go`) already traverses
every BSON path into `DataPointsMap map[string][]uint64`. `attribs.go` is a
typed *selection* layer on top of a complete decode. Why add a `ftdc-slice`
binary when we could just widen simagix's output?

There are two distinct interpretations — and they have very different answers.

#### Option A: expand `attribs.go` from 79 → all paths — don't do this

`ServerStatusDoc` / `SystemMetricsDoc` are hand-written typed Go structs. You'd
be writing thousands of fields. Worse, `assessment.go` and `diagnosis.go`
iterate those structs — every added field flows into scoring and diagnosis rules.
You'd either bury the playbooks in unscoreable noise, or hand-write thresholds
for 5,000 metrics. This changes the **judgment layer**, which is exactly the
part of simagix worth preserving.

#### Option B: flip the forensic flag (`-tier=forensic`) — feasible, wrong tradeoff

`cmd/llm-export/main.go:165–166` already has `-tier=forensic` and `-raw=true`
flags. Passing `-tier=forensic` emits `raw/raw_metric_values.jsonl.gz` from the
full `DataPointsMap` — every path, every sample, already working. One-line
pipeline change. But:

| Criterion | `-tier=forensic` → ingest to PG | Raw bytes + decode-on-demand (this design) |
|---|---|---|
| Code effort | ~zero (flag + existing ingest loop) | `ftdc-slice` binary (~100 lines), index + catalog + tools |
| Storage per run | JSONL re-encode: ~200–500 MB gz **but** decoded → potentially GBs of rows; FTDC's delta+zlib discarded | ~0.5 GB — the theoretical minimum; FTDC **is** its own best encoding |
| Must store raw bytes anyway? | **Yes** — PVC is gone; `raw_files` is required for upload durability + retry regardless | Same: bytes are the source of truth |
| Therefore stored twice? | Yes — bytes for durability **plus** rows for query | No — bytes serve both roles |
| Ingest time | Full decode of all paths on every ingest run (always; you pay 100 %) | Near zero; bytes stream through untouched |
| Query latency | If rows: instant SQL, but billions of rows → ingest takes forever + indexes balloon. If JSONL: must gunzip-scan whole file per query — *worse* random access than FTDC with skippable chunk headers | Seconds per window; 2-level skip (file overlap → chunk `_id` timestamp before zlib) means only overlapping chunks decompressed. Column-level skip is not possible (single interleaved delta stream) so matched chunks decode in full, but decoded output is filtered to requested paths |
| Coverage | Numeric FTDC paths only; type-0 metadata docs partially covered by side files; frozen at export-time decoder version | Byte-exact; includes type-0 config snapshots, future fields, every path; re-decodable later with any decoder version |
| Fork pressure | Changes pipeline *behavior* in the vendored checkout | Additive: new `cmd/ftdc-slice` next to `cmd/llm-export`; existing behavior untouched |

**The decisive argument:** `raw_files` is not optional — it is the
crash-mid-upload fix, the pod-restart durability guarantee, and the retry path.
Given raw bytes are already sitting in PG, the forensic export would store the
same information **twice**, paying full decode+storage for 100 % of paths to
cover an agent usage rate of 10–20 % of investigations.

#### The winning pattern: extend, don't fork

`ftdc-slice` is not "instead of simagix" — it **reuses simagix's decoder
package**. The decoder already does the hard parts: chunk parsing, delta
expansion, `traverseDocElem` recursive traversal. The new binary is a thin CLI:
iterate files → skip blocks by header timestamp → decode matching blocks → emit
only the requested columns. Small, additive, and it inherits every format edge
case the simagix decoder already handles (truncated tails, path-set changes
across chunks).

**One-line truth:** "change simagix to export all paths" and "use raw bytes"
are not opposing options — the best implementation of the raw tier *is* a change
to simagix: a new `cmd/` entrypoint that slices on demand instead of expanding
at ingest.
