# Production Architecture — Decisions and Tradeoffs

Status: **agreed target** (2026-07-13). This document records every architecture decision made
for the Kubernetes production deployment, the alternatives considered, and why each was
accepted or rejected. Read this before changing any storage, queue, or deployment code.

## Target topology

```
ui             nginx — serves frontend/static/*, proxies API + pages → orchestrator
orchestrator   FastAPI — uploads, runs catalog, job status, Phase 2 + chatbot
               (async background tasks), Grafana datasource endpoints
worker         poll loop (backend/app/jobs/worker.py) — decode, hatchet, ingest.
               Go binaries (mftdc, llm-export, hatchet) baked into this image. × N replicas
grafana        1 replica — JSON datasource pointed at orchestrator
postgres       1 replica — the ONLY durable store
```

No shared volumes. No Docker socket anywhere. Pods use only their own temp disk
(`emptyDir`), which is disposable at all times.

---

## Decision 1 — Docker-in-Docker: bake binaries into the worker image

**Decision.** Compile `mftdc`, `llm-export`, and `hatchet` in a multi-stage Dockerfile and
copy the binaries into the worker image. The `simagix-workspace/scripts/run-*.sh` scripts
call the binaries directly. No `docker run` anywhere at runtime, no fallback mode.

**Why.** The containers were only ever a packaging mechanism for static Go CLI binaries
(mount workspace → run one binary → exit). Nothing about them needs container isolation.

**Alternatives rejected.**
- *K8s Jobs per run* — best decode isolation, but needs RBAC, job watching, log
  collection, and an image registry round-trip per run. Kept as a future upgrade if a
  decode ever OOMs a worker; the subprocess seam in `ftdc_job.py`/`hatchet_job.py` makes it
  an additive change.
- *Always-on decode microservice* — a whole service to build and operate for what is a
  CLI invocation.
- *Docker-in-Docker sidecar* — privileged pods; unacceptable.
- *`go run` at runtime* (current `run-llm-export.sh`) — compiles on every upload; removed
  for free by baking the compiled binary.

**Discovery: `diagnostic.data` was being decoded twice per run.**

`run-mongo-ftdc-pipeline.sh` calls two sub-scripts sequentially:

1. `run-mongo-ftdc.sh` → `docker run simagix/ftdc /mftdc` → writes **HTML reports** to
   `simagix-workspace/reports/mongo-ftdc/{run_id}/`. Our code never reads from
   `reports/` anywhere. This is a full FTDC decode producing output we discard.
2. `run-llm-export.sh` → `docker run golang:1.25 go run ./cmd/llm-export` → writes
   `findings.json`, `executive_context.json`, `time_series.jsonl.gz`, etc. to
   `uploads/{run_id}/phase1/mongo-ftdc/`. This is the output our consumers actually read.

**Fix (step 6):** Remove the call to `run-mongo-ftdc.sh` from the pipeline script. Only
`llm-export` is called, as a baked binary (no `go run`, no Docker). No og-repo source
change needed — only the shell script changes. The `reports/` directory stops being
written to. Pipeline decode time roughly halves.

**Tradeoff accepted.** Decodes share the worker pod's memory. Mitigated by worker resource
limits and by the worker being a separate deployment from the orchestrator (Decision 6), so
a decode OOM kills only a worker replica; the queue and API survive.

**Q: In the job runners, why `env = {**dict(os.environ), "HATCHET_RUN_ID": run_id}` —
copy the whole environment just to add one variable?**
Because `subprocess.run(env=...)` *replaces* the child's environment entirely; passing
only `{"HATCHET_RUN_ID": ...}` would strip `PATH`, `HOME`, etc. and the shell script
would break immediately. The pattern is plain dict-merge: everything from the parent,
plus one extra key. The run id travels as an env var rather than a CLI argument because
the pipeline script chains into further scripts (`run-mongo-ftdc-pipeline.sh` →
`run-llm-export.sh`) that read the same variable — one `export` beats threading an
argument through every layer. Same pattern in `ftdc_job.py` with `MONGO_FTDC_RUN_ID`.

---

## Decision 2 — Storage: Postgres only; ingest data, don't move files

**Decision.** Postgres is the single durable store. Binary outputs are written to the
worker's temp disk, then an **ingest step** reads them once and loads them into Postgres
as *queryable data* (not file blobs). The files then die with the pod.

- `normalized/time_series.jsonl.gz` → `metrics(run_id, name, ts, value)` rows
  (it is already `{target, datapoints}` shaped — ingest is a direct mapping)
- `hatchet.db` (SQLite) → read once with Python's `sqlite3`, bulk-insert into
  `log_events` tables. **No change to the hatchet binary.**
- findings / executive_context / assessment / manifests → JSONB rows
- Phase 2 state (investigation, questions, report, chat) → JSONB rows
- job queue + run catalog → plain tables

**Why.** Every file-shuffling design (sync/hydrate cache layer, blob tables, gob
snapshots, sidecars sharing volumes) existed only to preserve the assumption "outputs
live as files". Storing *data* eliminates the whole category: nothing needs a shared
filesystem, restarts lose nothing, any pod can serve any request.

**Alternatives rejected.**
- *RWX PVC (shared filesystem)* — needs NFS/EFS-class storage; not available on standard
  cloud block disks; extra infra and cost.
- *S3/MinIO object store* — solves persistence but not queryability; every consumer still
  needs download-to-temp adapters; adds a third stateful service. Revisit only if
  artifacts outgrow Postgres (~1GB/value hard limit, practical discomfort far earlier).
- *Postgres as a blob filesystem + local disk cache (sync/hydrate)* — cheapest migration
  (~3–5 days, zero consumer changes) and was seriously considered; rejected because it
  keeps the single-replica constraint, keeps the blob→temp-file round-trips, and leaves
  Grafana dependent on either raw files or a patched simagix API. The full ingest design
  costs ~2.5–3 weeks but removes every one of those permanently.
- *Postgres + MongoDB* (hatchet has a native Mongo backend) — two databases means two
  backup/monitoring/failure regimes for one tool's convenience.
- *Teach the Go binaries to write to Postgres/S3 directly* — 2–3 days per binary, permanent
  fork divergence, and the ingest step is still needed for Python-written artifacts, so
  nothing is saved.

**Tradeoffs accepted.**
- An ingest step per job (~seconds; trivial next to a multi-minute decode).
- The consumer modules (`evidence/loader.py`, `evidence/ftdc_tools.py`,
  `evidence/hatchet_tools.py`, Phase 2 state, job store, catalog) must be migrated from
  file reads to Postgres queries — this is the bulk of the ~2.5–3 week estimate.

---

## Decision 3 — Raw uploads: transient, transferred through Postgres chunks

**Decision.** Raw inputs (`diagnostic.data`, mongod logs) are never durable. The
orchestrator streams an upload into a `raw_chunks(run_id, seq, bytes)` table (~10MB rows);
the worker that claims the job reassembles them to its temp disk, decodes, ingests, then
the chunks are deleted.

**Why chunks exist at all.** Earlier single-pod designs had upload receiver and decoder in
the same process, so locality hid the transfer. With orchestrator/worker as separate
deployments (Decision 6), the bytes must cross pods. Chunks also make the job durable the
moment the upload completes: the orchestrator can die immediately after and any worker
still runs the job.

**Alternatives rejected.**
- *Worker HTTP-fetches raw file from orchestrator* — file lives on one replica's disk; a
  restart between upload and claim loses it unrecoverably.
- *Process-where-uploaded* (receiving pod also decodes) — worked in the all-in-one design;
  incompatible with the orchestrator/worker role split.
- *MinIO for this one artifact* — legitimate; rejected to keep the stack at two stateful
  services. Revisit if uploads grow well past ~1GB.
- *Single bytea value* — a 1GB value is materialized in memory whole on insert and read;
  chunked rows stream with flat memory.

**Tradeoffs accepted.**
- ~200MB–1GB transits Postgres per upload (minutes of residence, then deleted).
- A run can never be re-decoded later — re-analysis requires re-upload. (Nothing
  downstream needs the raw file once metrics/logs/evidence are ingested and charts are
  served from Postgres.)

---

## Decision 4 — Grafana: keep it, but serve it from our own datasource endpoints

**Decision.** Grafana stays (user requirement). The simagix `ftdc-api` service is
**removed entirely**. The orchestrator implements the Grafana JSON datasource protocol —
`/grafana/search` (metric names from the catalog) and `/grafana/query` (datapoints from
the `metrics` table). Dashboards are ported from simagix's provisioned JSONs (same metric
names — both derive from the same decoder).

**Why.** The ftdc-api held one decoded run **in memory**, required a ~2-minute warm-up
decode of the raw files per run switch, and was the last component needing either raw-file
retention, a shared volume/sidecar, or a fork patch (gob snapshot save/load was designed,
~60 lines). Serving `{target, datapoints}` rows out of Postgres makes charts instant,
restart-proof, multi-run (dashboard variable), and deletes a service.

**Alternatives rejected, in the order they were considered.**
1. *Keep ftdc-api, keep raw files, re-decode on warm* — 2-minute warms forever; raw
   retention forces the shared-storage problem back in.
2. *Fork patch: gob snapshot save + load-by-path* — small (~40 lines) but forces a shared
   volume between app and ftdc-api (sidecar + RWO PVC gymnastics).
3. *Fork patch v2: snapshot posted over HTTP* — removed the shared volume, still kept an
   extra stateful-in-memory service and permanent fork maintenance for serving.
4. *Replace Grafana with our own uPlot dashboard* — fully viable (~1.5 weeks) and would
   drop a deployment; rejected because the user explicitly wants Grafana's UX.

**What this decision solves — exhaustive list.**

Every item below is a real production problem in the current Docker-based Grafana setup.
All are eliminated by serving metrics from Postgres.

1. *Docker must be running on the machine.* `stack.py` calls `docker compose up` before
   every chart load. In K8s there is no Docker daemon. Our implementation needs no Docker
   at runtime.
2. *2-minute warm-up per run switch.* ftdc-api decodes the full `diagnostic.data` into
   memory on `POST /load`. Charts are unavailable for ~2 minutes after each run switch.
   Our implementation: data is in Postgres after ingest (seconds). Every chart load is
   instant, first or hundredth.
3. *Raw files must be kept on disk forever.* ftdc-api needs the original `diagnostic.data`
   to decode. In K8s with `emptyDir`, the raw file dies with the pod — making ftdc-api
   impossible. Our implementation: the raw file is only needed during ingest. Once ingested
   it can disappear.
4. *Shared volume between app and ftdc-api.* ftdc-api and the app must share the same
   filesystem namespace. In K8s this forces a sidecar (same pod) or RWX PVC (cross-pod).
   Our implementation: no shared volume. Grafana talks to our orchestrator over HTTP.
5. *Only one run visible in Grafana at a time.* ftdc-api is stateful — it holds exactly
   one decoded run in memory. Our implementation: `metrics` table has `run_id` as a column.
   All runs are always available; switching runs changes a Grafana dropdown variable.
6. *`POST /{run_id}/grafana/load` blocks for minutes.* This API endpoint holds an HTTP
   connection open while ftdc-api decodes. nginx kills it in production. Our implementation:
   this endpoint is deleted. There is no "load" step.
7. *Silent `warm_grafana_for_run()` that often fails.* After decode, `ftdc_job.py` calls
   this function which swallows every exception and returns False on failure (the "Grafana
   warmup skipped" job message). Our implementation: the function is deleted. Ingest writes
   to Postgres. Charts appear.
8. *Container path vs host path translation.* `stack.py` translates host filesystem paths
   to Docker-container-mounted paths (`container_path_for_host()`). ~40 lines of
   path-munging that exists solely because of the shared-volume architecture. Our
   implementation: no containers, no path translation, no `stack.py`.
9. *215 lines of Docker orchestration to maintain.* Compose file management, Docker socket
   health checks, container restart logic. All of it is inert in K8s. Our implementation:
   `stack.py` deleted entirely.
10. *ftdc-api fork patch required.* We had designed a ~60-line gob snapshot patch to make
    ftdc-api save/load decoded state without re-decoding per pod restart. Our
    implementation makes it unnecessary — data is in Postgres, not in-memory. The
    mongo-ftdc fork stays at existing changes only (`llm-export`, `mftdc.go`).

**Implementation — how the protocol actually works.**

Grafana's SimpleJSON datasource sends three request types to our FastAPI orchestrator
(`api/grafana.py` → `grafana/datasource.py`):

1. `GET /grafana/` → must return HTTP 200. Grafana health check. We add `?run_id=` here
   so the dashboard variable can be threaded to all requests.
2. `POST /grafana/search` → body `{"target": ""}`. Returns a JSON array of metric names
   for the active run:
   ```sql
   SELECT DISTINCT name FROM metrics WHERE run_id = $1 ORDER BY name
   ```
3. `POST /grafana/query` → body contains `targets` (metric names) and a `range`
   (`from`/`to`). Returns:
   ```json
   [{"target": "ss.opcounters.insert", "datapoints": [[value, ts_ms], ...]}]
   ```
   Backed by:
   ```sql
   SELECT ts, value FROM metrics
   WHERE run_id = $1 AND name = $2 AND ts BETWEEN $3 AND $4
   ORDER BY ts
   ```

**Q: How does Grafana know which run to query?**
A Grafana dashboard variable `$run_id` is populated from a search query. Our `/grafana/search`
returns run IDs when target is `"runs"`. All panel queries include `run_id=$run_id` as a
variable substitution, which Grafana passes into the query body's `scopedVars`.

**Q: What happens to the existing simagix dashboard JSONs?**
The metric names are identical — both simagix's ftdc-api and our `metrics` table derive
from the same `mftdc` decoder output (same `target` field). Only the datasource name in the
JSON changes from `"ftdc"` to our datasource name. Panel definitions, time ranges, and
thresholds stay the same. One-time port, then maintained by us.

**Q: Performance vs the in-memory ftdc-api?**
The `metrics` table has index `(run_id, name, ts)`. A 1-hour window at 1s resolution is
~3600 rows — sub-millisecond index lookup. At the extreme (~55k points per metric), it is
still a trivial indexed scan. Grafana downsamples client-side anyway. The difference from
in-memory is unmeasurable at these row counts.

**Q: Warm-up time?**
Zero. Data is in Postgres after ingest completes (seconds after decode). First chart load
is identical to the hundredth. The ftdc-api's 2-minute warm-up is eliminated entirely.

**Q: Any case where the old approach was better?**
Yes — ftdc-api could serve charts mid-decode by pointing at the raw file. Our approach:
charts appear only after ingest finishes. Acceptable because ingest takes seconds, not
minutes, and decode must finish before any metric is meaningful anyway.

**Tradeoffs accepted.**
- Dashboards must be ported once and maintained by us.
- `/query` performance depends on the `metrics` index + downsampling in SQL; ~55k points
  per metric per run is comfortably within Postgres range.
- The mongo-ftdc fork keeps only the changes that already exist (`llm-export`,
  `main/mftdc.go`); no new divergence for serving.

---

## Decision 5 — hatchet.db: read once, ingest FULLY, discard

**Decision.** The hatchet binary keeps writing SQLite to temp disk. After the job, Python
reads it once and streams **every row of every table** into typed Postgres tables via
`COPY`. Tier-2 log tools (`evidence/hatchet_tools.py`) run their filters/sorts as SQL at
query time — identical behaviour to the old direct-SQLite tools, zero data loss.

**Table mapping** (PG schema mirrors the SQLite schema column-for-column, plus `run_id`):

| SQLite table (per hatchet name) | Postgres table | Real-case row count |
|---|---|---|
| `{name}` (every parsed log line) | `hatchet_logs` | 1,079,991 |
| `{name}_ops` (slow-op aggregates) | `hatchet_ops` | 41 |
| `{name}_audit` (exception counters) | `hatchet_audit` | 1,015 |
| `{name}_clients` (connection rows) | `hatchet_clients` | 222,921 |
| `{name}_drivers` (driver versions) | `hatchet_drivers` | 110,692 |
| `hatchet` (1-row meta) + computed summary | `evidence` JSONB (`hatchet_meta`, `hatchet_summary`) | 2 docs |

**Q: An earlier iteration stored top-500 log slices as JSONB arrays in the evidence
table. Why was that reversed?**
Because it silently violated this decision. The JSONB approach exported only the slices
the current tools happened to read (top 500 logs by latency, top 200 audit rows, pre-
bucketed clients) — against a real case that meant keeping 500 of 1,079,991 log rows and
baking the tools' LIMITs into the data at ingest time. Verified against a real
`hatchet.db`: full COPY of all 1.4M rows takes ~57s (acceptable one-time cost inside the
hatchet job), row counts match source exactly, and raw `message` payloads round-trip
byte-identical. JSONB remains only for `hatchet_meta`/`hatchet_summary`, which genuinely
are single documents.

**Q: Why typed tables instead of one JSONB doc per table?**
A 1M-row table as one JSONB document is unusable: ~GB-scale document, no indexing, and
every tool call would deserialize the whole thing in Python. Typed tables get real
indexes (`(run_id, milli DESC)` etc.), so `get_hatchet_log_examples(min_milli=2000)` is
an index scan — same query plan the SQLite tools relied on. This mirrors the `metrics`
table decision: big row-shaped data → typed table; small keyed documents → `evidence`.

**Q: How are hatchet schema variants handled?**
Ingest intersects the PG column list with `PRAGMA table_info` of the actual file, so a
column missing in an older/newer hatchet build is skipped (stays NULL) instead of
crashing. `hatchet_clients` carries both variant column sets (`ip`-based and
`date`-based); the timeline tool picks its bucketing at query time based on which is
populated.

**Alternatives rejected.**
- *Store hatchet.db as a Postgres blob, download-to-temp before each query session* —
  works and was the earlier plan; rejected with the move to full ingest (Decision 2): the
  round-trip is ugly, and rows make logs queryable/joinable server-side.
- *Write a Postgres backend inside the hatchet fork* (it has a storage interface with
  SQLite and Mongo implementations) — 3–5 days of Go plus Python rewrite; the ingest step
  achieves the same end state with zero fork changes. Shelved, not needed.

**Tradeoffs accepted.** Large log cases (600MB+) produce a big one-time ingest (~1min/1M
rows via COPY) added to the hatchet job, and Postgres storage grows with full log fidelity
(~1–2GB per large run — run deletion must clean these tables, handled with retention in
step 6).

---

## Decision 6 — Roles: worker = heavy compute only; orchestrator = API + Phase 2

**Decision.** The existing split stays and sharpens:
- **Worker** (`backend/app/jobs/worker.py`, already a standalone polling process) runs
  decode, hatchet, and ingest — the memory/CPU-heavy jobs.
- **Orchestrator** keeps Phase 2 (LLM investigation, clarify, chatbot) — but as **async
  background tasks + status polling**, never as work done inside a blocking HTTP handler.

**Why.** Division by resource profile. Decode is heavy compute and must not share a
process with the API (an OOM should kill a worker replica, not the API). Phase 2 is ~99%
waiting on LLM/network I/O — cheap to host in the orchestrator, where the code already
lives; routing it through the worker queue would let a long decode block a user's RCA
(head-of-line blocking) unless we ran type-split worker pools, i.e. more moving parts for
zero benefit.

**Alternatives rejected.**
- *Everything in the worker (Phase 2 as job types)* — clean queue semantics and automatic
  retry, but causes decode-blocks-RCA with one worker pool and demands a second pool to
  avoid it.
- *Status quo (blocking `POST /phase2/run`)* — holds an HTTP connection open for a
  multi-minute investigation; nginx/LB kills it in production. **This must change
  regardless of role placement**: enqueue-style handler returning immediately + frontend
  polling (pattern already used for Phase 1 jobs; `rca.js`/`agent-chat.js` change from
  await-fetch to poll).

**Tradeoffs accepted.**
- An orchestrator pod dying mid-investigation loses that investigation (state saved to
  Postgres up to the last checkpoint; the user re-runs). A queue would auto-retry;
  accepted because it matches today's failure semantics and Phase 2 is user-initiated.
- Needs an atomic per-run "already running" guard (`UPDATE ... WHERE state != 'running'
  RETURNING`) so concurrent requests can't start two investigations.

---

## Decision 7 — Queue: Postgres rows with SKIP LOCKED, same interface as today

**Decision.** `FileJobQueue` (pending//processing/ directories, atomic `path.replace`
claims) is **deleted and replaced** by `JobQueue` in `backend/app/jobs/queue.py` — a
Postgres implementation of the same interface (`enqueue`, `claim_next`, `complete`,
`requeue_stale_processing`, …). Claiming uses `FOR UPDATE SKIP LOCKED`; each claim
records `claimed_by` (pod hostname); startup recovery requeues only rows claimed by
the restarting worker. **No file-queue fallback exists**: `DATABASE_URL` is required
everywhere, including local dev and tests (a one-line `docker run postgres:16-alpine`
provides it — see `.env.example`; kind + Helm provide it in cluster testing, mirroring
Merged Dev).

**Why.** The file queue was a correct design bound to one machine's disk. `SKIP LOCKED`
is the canonical multi-consumer Postgres queue (same pattern as Merged Dev's recordings
table). Because the interface already existed, this was a storage-engine swap, not an
architecture change. A dual-backend factory was considered and **rejected by explicit
decision**: fallbacks double the code paths and halve the test honesty — dev must run
what prod runs.

**Tradeoffs accepted.**
- A worker that dies mid-job leaves a PROCESSING row until it restarts (self-requeue) —
  same semantics as the file queue had. A heartbeat/timeout reaper can be added later
  if workers become numerous.
- Local dev and CI require a Postgres to be running; the test suite refuses to start
  without `DATABASE_URL` (`backend/tests/conftest.py`).

**Q: What is `worker_id` and why is it a config setting?**
It is the identity a worker stamps into `jobs.claimed_by` when claiming a ticket
(`_worker_id()` in `queue.py`: `settings.worker_id or socket.gethostname()`). It does
two jobs. First, observability — the table shows which of the N worker pods is running
what. Second, and more important, **crash recovery**: on startup a worker runs
`UPDATE jobs SET state='PENDING', claimed_by=NULL WHERE claimed_by = <me>` — "release
anything *I* claimed before I died." If a pod OOMs mid-decode and Kubernetes restarts
it, its orphaned job returns to PENDING and is picked up again instead of being stuck
in PROCESSING forever. The `claimed_by = me` filter is what makes this safe: a
restarting pod releases only *its own* orphans, never a job another healthy pod is
actively running. In K8s, `WORKER_ID` is set from the pod name (stable identity across
container restarts within the pod); locally it falls back to the hostname. That is why
it is configuration rather than a hardcoded value.

---

## Decision 8 — Two tables: `jobs` (queue) vs `job_status` (lifecycle record)

**Decision.** Job queue tickets and job lifecycle records are stored in **separate tables**
with different retention semantics. `jobs` holds only pending/processing work and rows are
**deleted** on completion. `job_status` is the permanent record of every job ever created
(pending → running → succeeded/failed) and rows are **never deleted**.

**Why.** They serve different access patterns and lifecycles:
- The queue is a hot, small, high-contention table. `claim_next()` scans only
  pending rows using `FOR UPDATE SKIP LOCKED`. If completed rows lived here too,
  the claim query would scan an ever-growing pile of `succeeded`/`failed` rows to
  find the one `PENDING` row — degrading over time.
- `FOR UPDATE` on a queue row during claiming would contend with status-update
  writes (worker setting `state=running`, `state=succeeded`) if both lived in the
  same row.
- Index profiles differ: the queue wants `(state, enqueued_at)` for FIFO claiming;
  the status store wants `(run_id, job_type)` for catalog lookups and `(updated_at
  DESC)` for recency sorting. Separate tables let each carry only the indexes it
  needs.

**Alternatives rejected.**
- *Single merged table (queue + status in one row)* — completed rows accumulate
  forever, claim scans grow, lock contention between queue operations and status
  reads. Would need a periodic archival job or partitioning to stay performant —
  complexity for no benefit.

**Tradeoff accepted.** Two tables means `enqueue()` and `store.create()` are separate
calls; callers must remember both. Acceptable because the call sites are few (upload
handler, retry handler) and the separation makes each table's invariants obvious.

---

## Decision 9 — Multi-pod behavior

With Decisions 2–8 in place:
- Any orchestrator replica serves any request (all state in Postgres).
- N workers drain one queue without coordination (`SKIP LOCKED`); decodes spread across
  replicas.
- Grafana and Postgres run single-instance — fine at this scale; both have standard HA
  paths (managed PG, Grafana replicas) if ever needed.

---

## Decision 10 — File structure and module naming

Every rename, move, deletion, and creation is deliberate. This section records the why
for each so a future reader (or interviewer) can reconstruct the reasoning without
reading git blame.

### `backend/app/jobs/`

**Q: Why rename `pipeline.py` → `ftdc_job.py`?**
"Pipeline" is generic — any multi-step process could be called that. The file runs one
specific thing: the FTDC decode job via `run-mongo-ftdc-pipeline.sh`. `ftdc_job.py` is
unambiguous. It also pairs symmetrically with `hatchet_job.py`.

**Q: Why rename `retry.py` → `ftdc_retry.py`?**
`hatchet_retry.py` already existed with its job-type prefix. `retry.py` was the FTDC
equivalent but looked like a generic retry utility. Consistency: every job-type file now
follows the pattern `<type>_job.py` / `<type>_retry.py`. The pairings are explicit:
`ftdc_job.py` + `ftdc_retry.py`, `hatchet_job.py` + `hatchet_retry.py`.

**Q: Why rename `hatchet.py` → `hatchet_job.py`?**
`hatchet.py` in `jobs/` clashed conceptually with `simagix/hatchet_tools.py` — both named
"hatchet" with no qualifier. The `_job` suffix makes the role unambiguous: this is the job
runner (runs the shell script, then calls ingest). `evidence/hatchet_tools.py` is the
query layer. Different files, different responsibilities, now distinguishable at a glance.

**Q: Why add `ingest.py`?**
The ingest step is a distinct responsibility: read temp-disk outputs once, bulk-insert into
Postgres, done. It belongs in `jobs/` because it is called by the job runners after decode
completes. Keeping it separate from `ftdc_job.py` and `hatchet_job.py` means each file has
exactly one job — running the shell script, or ingesting its output. Not both.

---

### `backend/app/simagix/evidence/` (new subfolder)

**Q: Why create an `evidence/` subfolder inside `simagix/`?**
`simagix/` had 15 flat files with no grouping. Three of them — `bundle.py`,
`fallback_tools.py`, `hatchet_tools.py` — form a coherent data-access layer: all three are
being rewritten for Postgres, all three serve the same consumer (`rca_service.py`), and all
three answer the same question: "give me run data." Grouping them in `evidence/` makes the
architecture readable at a glance: `evidence/` is the data layer, `rca_service.py`
orchestrates it, `llm/` is the AI layer. The flat file list had no such signal.

**Q: Why rename `bundle.py` → `evidence/loader.py`?**
`bundle.py` / `SimagixBundleLoader` described the storage mechanism — a bundle directory
full of JSON files. After Postgres migration there is no bundle directory; there are
`evidence` rows. `loader.py` / `EvidenceLoader` describes the role (load tier1 evidence
context), not the storage format that role used to use.

**Q: Why rename `fallback_tools.py` → `evidence/ftdc_tools.py`?**
"Fallback" was an implementation detail of how the LLM uses these tools: it "falls back"
to metric retrieval when tier1 context alone is insufficient. The file's actual job is FTDC
metric series retrieval from Postgres. Calling it "fallback" made it sound secondary or
emergency-only. `ftdc_tools.py` names what it retrieves. Moving it to `evidence/` groups
it with the other data-access files where it belongs.

**Q: Why move `hatchet_tools.py` into `evidence/`?**
The name stays the same, but it moves into `evidence/` so that all three data-access files
(`loader.py`, `ftdc_tools.py`, `hatchet_tools.py`) live together. A reader looking for
"how do I get run data from Postgres" goes to one place.

**Q: Why delete `hatchet_export.py`?**
It had two jobs: (a) query SQLite and write JSON artifacts to disk (summary.json,
source_files.json), and (b) helper functions used by `hatchet_job.py`. After migration,
(a) moves to `jobs/ingest.py` (now writes to Postgres, not disk), and (b) folds inline
into `hatchet_job.py`. Nothing remains, so the file is deleted rather than left hollow.

**Q: Why delete `hatchet_summary.py` and `hatchet_readiness.py`?**
Both were small single-purpose helpers used only inside `hatchet_tools.py` and
`rca_service.py`. After Postgres migration, `hatchet_summary.py`'s disk-read is replaced
by a Postgres query (no separate file needed), and `hatchet_readiness.py`'s filesystem
`is_file()` check is replaced by a `COUNT(*)` query. The logic absorbs cleanly into
`evidence/hatchet_tools.py`. Two fewer files, zero lost capability.

**Q: Why rename `evidence_service.py` → `rca_service.py` and not just `service.py`?**
Two reasons. First, `llm/service.py` already exists — renaming to `simagix/service.py`
would produce two files named `service.py` in parent and child modules, confusing imports
and grep. Second, this file is the RCA evidence orchestrator (tier1 load, budget-gated
tier2 tools, hatchet block assembly) — `rca_service.py` says what it does, not just that
it is "a service."

**Q: Why rename `prompt.py` → `evidence_block.py`?**
`simagix/prompt.py` and `simagix/llm/prompts.py` were near-identical names at different
levels doing completely different things. `simagix/prompt.py` builds the structured tier1
evidence text block (assembled from decoded run data, passed as context). `simagix/llm/prompts.py`
builds LLM user messages (investigate, clarify, chatbot instructions). `evidence_block.py`
is accurate for the former; the latter keeps `prompts.py` unchanged.

---

### `backend/app/simagix/llm/`

**Q: Why rename `llm_paths.py` → `paths.py`?**
The file is already inside the `llm/` package — the `llm_` prefix is redundant noise.
`llm/paths.py` reads correctly as "the paths module of the llm package." Note: this file
manages Phase 2 session file paths on disk. It will be significantly reduced or deleted
when Phase 2 state moves to Postgres in step 4.

---

### `backend/app/grafana/`

**Q: Why delete `stack.py`?**
`stack.py` managed the Docker Compose stack — spinning up ftdc-api and Grafana containers,
checking health, loading runs via Docker. Decision 4 eliminates the ftdc-api entirely:
metrics are served from Postgres, not from an in-memory Docker service. With no containers
to manage, `stack.py` has nothing to do. Deleting it removes ~215 lines of Docker
orchestration from a codebase that now has no Docker at runtime.

**Q: Why rename `service.py` → `datasource.py`?**
After migration, this file implements the Grafana SimpleJSON datasource protocol (health
check, `/search`, `/query` — see Decision 4 implementation detail). `service.py` is too
generic. `datasource.py` names exactly what protocol it implements.

**Q: Why rename `anomaly_dashboard.py` → `dashboard.py`?**
The "anomaly" qualifier was specific to the first dashboard we ported (the anomaly focus
view). The file will grow to cover all dashboard definitions (all-metrics view, etc.).
`dashboard.py` is general enough to accommodate that without another rename.

**Q: Why will `links.py` be deleted in step 5?**
`links.py` (153 lines) builds Docker host paths, container paths, and Grafana URLs that
presuppose the Docker Compose stack. After migration: no containers, no container paths,
no ftdc-api base URL. What remains (Grafana base URL construction) is trivial and absorbs
into `datasource.py`. The file is kept until step 5 rather than deleted now to avoid
breaking the current Grafana flow before the replacement endpoints exist.

---

### `backend/app/api/`

**Q: Why rename `grafana_routes.py` → `grafana.py`?**
Every other API file follows the pattern `<domain>.py`: `upload.py`, `phase2.py`,
`simagix_runs.py`, `mcp_connectors.py`, `skill_workarea.py`. Only grafana carried the
redundant `_routes` suffix. Consistency over convention.

---

### Final file map (steps 3–6)

```
backend/app/
├── jobs/
│   ├── ftdc_job.py          (was pipeline.py)
│   ├── ftdc_retry.py        (was retry.py)
│   ├── hatchet_job.py       (was hatchet.py)
│   ├── hatchet_retry.py     (unchanged)
│   ├── ingest.py            ← NEW
│   ├── queue.py, store.py, worker.py, catalog.py, job_types.py
│
├── grafana/
│   ├── datasource.py        (was service.py)
│   ├── dashboard.py         (was anomaly_dashboard.py)
│   ├── links.py             (deleted in step 5)
│   ✗ stack.py               DELETED (step 3)
│
├── api/
│   ├── grafana.py           (was grafana_routes.py)
│   └── upload.py, phase2.py, simagix_runs.py, mcp_connectors.py, skill_workarea.py
│
└── simagix/
    ├── evidence/            ← NEW subfolder
    │   ├── loader.py        (was bundle.py)
    │   ├── ftdc_tools.py    (was fallback_tools.py)
    │   └── hatchet_tools.py (was hatchet_tools.py + summary + readiness merged in)
    │   ✗ hatchet_export.py  DELETED
    │   ✗ hatchet_summary.py DELETED
    │   ✗ hatchet_readiness.py DELETED
    ├── llm/
    │   ├── paths.py         (was llm_paths.py; deleted in step 4)
    │   └── prompts.py, service.py, session.py, provider.py, ...
    ├── rca_service.py       (was evidence_service.py)
    ├── evidence_block.py    (was prompt.py)
    └── schemas.py, output_schema.py, scoring.py, grounding.py, budget.py,
        anomaly_correlation.py, format_report.py, report_html.py,
        eval.py, tool_usage.py, graylog_client.py
```

**Q: Postgres holds everything now — do the path-resolution files
(`llm/paths.py`, `core/run_workspace.py`) still have a reason to exist?**
Two different files, two different fates, one rule of thumb: **paths to durable state
die step by step; paths to scratch space stay forever.**

- `simagix/llm/paths.py` resolves where phase 2 *durable state* lives on disk
  (`phase2/llm/<llm>/latest_report.json`, `investigation.json`, `budget_state.json`,
  `tool_trace.json`, chat history, `llm_index.json`). After step 3, phase 2 *reads*
  evidence from Postgres, but its own session state is still file-backed — so the file
  is still load-bearing (five importers: `session.py`, `service.py`, `api/phase2.py`,
  `jobs/catalog.py`, `web/routes.py`). Step 4 moves that state into Postgres, and the
  file is deleted with it.
- `core/run_workspace.py` resolves *scratch space during a job*: where the uploaded
  FTDC archive sits, where the shell scripts live, where `hatchet.db` lands before
  ingest reads it. Postgres is where data **lives**; it cannot answer "where do temp
  files go while a worker is mid-decode." The file shrinks as export-dir resolution
  stops mattering, but it survives every migration step.

---

## Decision 11 — Phase 2 state: one `phase2_state` table; runs become async + poll (step 4)

**Decision.** All phase 2 session state moves from per-run disk files into a single
Postgres table, and the two long-running endpoints stop blocking HTTP.

```sql
CREATE TABLE phase2_state (
    run_id     TEXT NOT NULL,
    llm        TEXT NOT NULL,   -- mock | cursor | gemini
    key        TEXT NOT NULL,   -- report | investigation | iterative_state | budget
                                -- | tool_trace | metadata | chatbot | attachment:<name>
    data       JSONB NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (run_id, llm, key)
);
```

**File → key mapping** (every file under `phase2/llm/<llm>/` dies):

| Old file | New key | Notes |
|---|---|---|
| `latest_report.json` | `report` | |
| `investigation.json` | `investigation` | |
| `iterative_state.json` | `iterative_state` | also drives status polling |
| `budget_state.json` | `budget` | shared with MCP subprocesses via PG, not a file |
| `tool_trace.json` | `tool_trace` | `ToolTraceCollector(run_id, llm)` writes PG |
| `session_metadata.json` | `metadata` | |
| `chatbot_chat.json` | `chatbot` | |
| `chatbot_scratch/attachments/*` | `attachment:<stored_name>` | text content in JSONB; materialised to local scratch before each chatbot run |
| `llm_index.json` | *(none — derived)* | `list_llm_sessions` is now a SELECT; `update_llm_index()` deleted |

**Q: Why one table with a `key` column instead of typed columns per artifact?**
Same reasoning as the `evidence` table: these are single JSON documents written and read
whole, never filtered row-wise. `(run_id, llm, key)` primary key gives upsert semantics
identical to "overwrite the file". The typed-table treatment is reserved for row-shaped
data (metrics, hatchet rows).

**Q: How does the retrieval budget work without `budget_state.json`?**
The budget was a file because two *processes* share it: the orchestrator and the MCP
server subprocess the LLM provider spawns. Both now read/write the `budget` key in
`phase2_state` (`RetrievalBudget(run_id=…, llm=…)`). The MCP subprocess env drops
`SIMAGIX_BUDGET_STATE_PATH` and gains `SIMAGIX_LLM` + `DATABASE_URL`. Same
load-check-increment-save semantics as the file version — no new race introduced.

**Q: Chatbot attachments in Postgres? Those are files the LLM reads with grep/read tools.**
Source of truth is PG (they're capped at 512KB, text-only suffixes). Before each chatbot
run the session materialises them into the local `chatbot_scratch/` dir — which is now
pure per-pod cache, rebuildable from PG on any pod. Upload on pod A, chat on pod B works.

**Q: What exactly becomes async?**
`POST /phase2/run` (investigation + clarifying questions, ~1–3 min of LLM calls) and
`POST /phase2/clarify` (final RCA, similar). Both now: validate synchronously (missing
bundle → 404, hatchet not ready → 409 — unchanged), write `iterative_state` with a
running status, submit the work to a small in-process thread pool, and return
immediately. The status lifecycle:

```
not_started → running_investigation → awaiting_clarifications → running_rca → completed
                                   ↘ failed (error text in state)  ↗
```

`GET /phase2/status` reads `iterative_state` from PG — served by any orchestrator pod.
The frontend polls it every ~2s while a running status is active. A background failure
writes `status=failed` + error; nothing is lost to a dropped connection.

**Q: Why an in-process thread pool and not the worker job queue?**
Decision 6: phase 2 is ~99% waiting on LLM network I/O — cheap for the orchestrator,
and routing it through the worker queue would let a long decode block a user's RCA.
Tradeoff accepted: if an orchestrator pod dies mid-run, state sticks at `running_*`
until the user retries (same self-recovery semantics as the worker queue; a stale-state
sweep can be added later).

**Q: What survives on disk after step 4?**
Only scratch: `chatbot_scratch/` as a rebuildable cache, and everything
`run_workspace.py` owns for in-flight jobs (uploads, scripts, hatchet.db pre-ingest).
`llm/paths.py` is deleted; its pure helpers (`llm_folder_name`, `LLM_FOLDER_NAMES`) move
to the new `llm/state.py` alongside the PG state accessors.

---

## Schema reference — why every table looks the way it does

The lesson that forced this migration: the file tree was already a database — paths were
keys, files were rows, directories were indexes, `mkdir -p` was the migration tool — but
with none of the guarantees (no atomicity across two files, no concurrent-writer safety,
no querying, and above all: bound to one machine's disk). Moving to Postgres wasn't
adding a database; it was replacing a hand-rolled one with a real one. This section
answers, table by table, "why is it shaped like this and what did you trade away."

### The one rule that decides every table's shape

> **Read whole → JSONB document row. Filtered/sorted/aggregated → typed columns.**

A report, a manifest, a chat transcript — always loaded entirely, never queried inside →
one JSONB row, upsert-on-write, exactly the semantics of overwriting a file. A metric
series or a million log lines — always sliced by predicates (`WHERE milli > 2000 ORDER BY
milli DESC LIMIT 10`) → typed columns with real indexes. Applying the wrong treatment
fails visibly in both directions: typed tables for reports means a schema migration every
time the report gains a field; JSONB for logs means deserialising a GB-scale document in
Python to find ten rows.

### `jobs` — the queue

```sql
jobs (job_id PK, run_id, job_type, input_path,
      state CHECK IN ('PENDING','PROCESSING'), claimed_by,
      enqueued_at TIMESTAMPTZ, claimed_at TIMESTAMPTZ)
INDEX (state, enqueued_at)   -- FIFO claim scan
INDEX (run_id)               -- has_active_job_for_run
```

**Q: Why only two states, when a job has four?**
Because this table *is the queue*, not the job's biography. A row exists only while work
is owed: PENDING (waiting) or PROCESSING (claimed). Completion **deletes** the row. The
CHECK constraint makes the invariant self-documenting — a `succeeded` row here is a bug
the database itself rejects. The full lifecycle lives in `job_status`.

**Q: Walk me through the claim query.**
`SELECT … WHERE state='PENDING' ORDER BY enqueued_at FOR UPDATE SKIP LOCKED LIMIT 1`,
then `UPDATE … SET state='PROCESSING', claimed_by=<me>`. `FOR UPDATE` locks the row;
`SKIP LOCKED` makes a second concurrent worker skip past it instead of blocking — N
workers drain one queue with zero coordination code. The `(state, enqueued_at)` index is
exactly this query's shape: filter on state, order by enqueue time.

**Q: Why TIMESTAMPTZ here but epoch floats in `job_status`?**
`enqueued_at`/`claimed_at` are set by the database (`DEFAULT now()`) and only ever
compared inside SQL — native timestamps are correct and free. `job_status` timestamps
originate in Python (`time.time()`), round-trip through the API as JSON numbers, and are
compared in Python — storing them as DOUBLE PRECISION means zero conversions end to end.
Rule: whoever generates and consumes a timestamp picks its type.

**Tradeoff accepted:** deleting completed rows means the queue table can't answer "what
ran yesterday" — by design; that's `job_status`'s job. Two writes per enqueue is the cost
(see Decision 8).

### `job_status` — the permanent record

```sql
job_status (job_id PK, run_id, job_type,
            state CHECK IN ('pending','running','succeeded','failed'),
            message, error, input_path,
            created_at DOUBLE PRECISION, updated_at DOUBLE PRECISION)
INDEX (run_id, job_type, updated_at DESC)  -- "latest ftdc job for run X"
INDEX (updated_at DESC)                    -- recency-sorted catalog
```

**Q: Why does `message` exist as a column instead of inside a JSONB blob?**
It's rendered in every catalog row the UI shows — a hot, always-selected scalar. Columns
for what you always read, JSONB for what you sometimes read. `error` is nullable TEXT
for the same reason (it's `IS NOT NULL`-filterable).

**Q: The two indexes look redundant — both end in `updated_at DESC`.**
Different leading columns, different queries. `(run_id, job_type, updated_at DESC)`
serves "latest hatchet attempt for run X" (point lookup + top-1). `(updated_at DESC)`
alone serves the global "recent activity" catalog sort, which has no run filter and
couldn't use the composite index efficiently.

**Tradeoff accepted:** never-deleted rows grow forever. Fine at this scale (hundreds of
jobs); the fix when it matters is a retention sweep, not a schema change.

### `metrics` — decoded FTDC time series

```sql
metrics (run_id, name, ts DOUBLE PRECISION /* ms epoch */, value,
         PRIMARY KEY (run_id, name, ts))
```

**Q: Why a single narrow table for hundreds of different metrics?**
The classic time-series-in-SQL shape (same as Prometheus remote-write schemas). The
alternatives are all worse: a column per metric (schema changes when mongo-ftdc adds a
metric, sparse NULLs everywhere), a table per metric (hundreds of tables, dynamic SQL),
or arrays in JSONB (no windowed queries). Narrow rows + composite PK give every query
the same plan: `WHERE run_id=? AND name=? AND ts BETWEEN ? AND ?` — an index range scan.

**Q: Why is `ts` a DOUBLE and not TIMESTAMPTZ?**
Milliseconds-since-epoch is the wire format on both ends: the decoder emits it and the
Grafana SimpleJSON protocol expects `[value, ts_ms]` pairs. Storing native timestamps
would mean converting on ingest and converting back on every query, purely for cosmetics.
The mixed source formats (some series in seconds, some in ms) are normalised **once at
ingest** — queries never guess.

**Q: Doesn't a range query need an index besides the PK?**
No — a composite PK *is* a unique index, and `(run_id, name, ts)` is exactly the query's
shape: equality on the first two columns, range on the third. An early version of the
schema carried a redundant secondary index on the same columns; it was caught during
this review and dropped (every extra index taxes ingest inserts for nothing).

**Q: Why is `value` nullable?**
FTDC encodes gaps; a NULL point preserves "the metric existed but had no reading" —
Grafana renders the gap instead of interpolating a lie.

**Tradeoff accepted:** row explosion — a long capture is millions of rows. Batched
`executemany` ingest and the covering PK keep it fine; the escape hatch if it ever isn't
is TimescaleDB/partitioning, which is a bolt-on, not a redesign.

### `evidence` — analysis artefacts

```sql
evidence (run_id, key, data JSONB, PRIMARY KEY (run_id, key))
```

**Q: Ten different artefact types in one table — why not a `findings` table, a
`manifest` table, …?**
Because every one of them is a document: written once by ingest, read whole by the
loader, never filtered inside SQL. Ten typed tables would each need their own schema
kept in lock-step with the Go exporter's JSON — churn with zero query benefit. The
`(run_id, key)` PK gives file-overwrite semantics (`ON CONFLICT DO UPDATE`) and
`EvidenceLoader` is a `SELECT data WHERE run_id=? AND key=?` — as simple as
`open(path).read()`, but pod-independent and transactional.

**Q: When would you split a key out of this table?**
The moment a consumer needs to query *inside* it. That's exactly the hatchet story
below — hatchet row data started as evidence keys and was promoted to typed tables when
"top 500 by latency, baked at ingest" proved to be silent data loss.

### `phase2_state` — the table that replaced a directory tree

```sql
phase2_state (run_id, llm, key, data JSONB, updated_at DOUBLE PRECISION,
              PRIMARY KEY (run_id, llm, key))
```

**Q: One table replaced eight file types. What's the trick?**
The file tree's structure *was* the key: `phase2/llm/<llm>/<artifact>.json` is literally
`(run_id, llm, key)`. The migration recognised the filesystem layout as a poorly-typed
composite primary key and wrote it down as a real one. Every file operation had a
one-line translation: write-file → upsert, read-file → select, `.exists()` → `SELECT 1`,
"list session dirs" → `SELECT … GROUP BY llm`. `llm_index.json` vanished entirely
because it was a cache of what a GROUP BY computes for free.

**Q: Why is `llm` its own column instead of part of the key string (`mock:report`)?**
It's a real query axis: "all sessions for this run" filters on it, isolation between
mock/cursor/gemini sessions depends on it. Encoded into the key string, it would need
`LIKE 'mock:%'` — a scan, not an index lookup, and one typo from a cross-LLM leak.

**Q: The budget is read-modify-write from two processes. Race?**
Same load-check-increment-save semantics the budget file had — the migration made it
pod-safe, not more atomic than before. The honest fix if it ever matters is a single
`UPDATE … SET data = jsonb_set(data, '{tool_calls_used}', …) RETURNING` — possible
precisely because the state is now in Postgres; it never was possible with a file.

**Q: Attachments as JSONB text — files in a database, really?**
They're ≤512KB, text-only suffixes enforced at upload, and the pod that receives the
upload is not necessarily the pod that runs the chat. PG is the source of truth; the
local `chatbot_scratch/` dir is a cache rebuilt (`materialize_attachments`) before each
run. Large/binary attachments would flip this to object storage — a documented boundary,
not a hidden one.

### `hatchet_*` — five typed tables (the JSONB counter-example)

```sql
hatchet_logs    (run_id + 17 source columns)  -- 1M+ rows/run; (run_id, milli DESC), (run_id, severity), (run_id, ns, op)
hatchet_ops     (run_id + 10 source columns)  -- (run_id)
hatchet_audit   (run_id, type, name, value)   -- (run_id, type, value DESC)
hatchet_clients (run_id + both schema variants) -- (run_id, ip)
hatchet_drivers (run_id + 5 source columns)   -- (run_id)
```

**Q: Everything else got JSONB — why do these get columns?**
The rule from the top: these are row-shaped and query-shaped. Real case: 1,079,991 log
lines, and the tools ask "slowest ops over 2000ms", "exceptions ranked by count",
"connections grouped by IP". As JSONB that's deserialising the world per tool call; as
typed rows it's an index scan. (First attempt stored top-N JSONB slices — rejected for
silently discarding 99.95% of rows; see Decision 5.)

**Q: Why do the columns mirror the SQLite schema exactly, even the awkward `_index` name?**
Fidelity is checkable when the mapping is 1:1 — `COUNT(*)` per table against the source
proves nothing was lost (verified: all five tables match, raw messages byte-identical).
Renaming columns during ingest creates a translation layer that must be documented and
can drift. `_index` is ugly and correct.

**Q: No primary key on these tables. Defend that.**
The source rows have no natural key (`id` repeats across runs and across merged source
files) and no consumer updates or addresses individual rows — access is only ever
"filter within one run". Idempotence comes from delete-then-`COPY` per run, not upserts.
A synthetic BIGSERIAL would cost index maintenance on a million-row COPY and buy nothing.
The day something needs row identity, adding it is one additive migration.

**Q: How were the indexes chosen?**
By reading the four tool functions and indexing exactly their predicates — `(run_id,
milli DESC)` is `get_hatchet_log_examples`'s ORDER BY, `(run_id, type, value DESC)` is
`get_hatchet_audit`'s, `(run_id, ip)` is the connection-timeline GROUP BY. No
speculative indexes: every index taxes the 1M-row ingest COPY, so each one must name the
query that pays its rent.

### Cross-cutting choices an interviewer will poke at

**Q: All ids are TEXT, not UUID or BIGSERIAL. Why?**
Ids pre-date the database — `run_id` (`upload20260618T120000Z`) and `job_id` come from
the application layer and appear in URLs, logs, and directory names on the worker's temp
disk. Making Postgres the id authority would have coupled the migration steps together.
TEXT PKs are marginally larger; irrelevant at these row counts.

**Q: No foreign keys anywhere. Lazy or deliberate?**
Deliberate, with eyes open. There's no `runs` parent table (a run exists the moment an
upload directory is created, before any row does), ingest order varies (evidence before
metrics, hatchet later or never), and per-run deletion in step 6 is `DELETE … WHERE
run_id=?` across tables in any order. FKs would force parent-first ordering and buy
referential guarantees nothing currently violates. The cost is honest: an orphaned row
is possible and a retention sweep, not a constraint, cleans it.

**Q: `CREATE TABLE IF NOT EXISTS` at startup instead of a migration tool?**
Additive-only schema evolution, applied idempotently by every process
(`ensure_schema()`). At this stage every change so far *was* additive (new tables), so a
migration framework (alembic) would be ceremony. Its trigger for adoption is defined:
the first `ALTER TABLE` that transforms existing data.

**Q: You said "one table handled everything" about phase2_state. So why isn't
*everything* one big JSONB key-value table?**
Because `metrics` and `hatchet_logs` exist. One KV table is exactly right for
document-shaped state and exactly wrong for row-shaped data — the schema is the rule
applied case by case, not one dogma applied everywhere. That's also the interview
answer in one line: *storage shape follows query shape.*

---

---

## Decision 12 — Operator config (MCP connectors + skills) → PG (implemented)

**Decision.** MCP connector registrations and skill uploads are stored in Postgres, not
in files under `simagix-workspace/operator/`. Two new tables added to `schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS mcp_connectors (
    id         TEXT PRIMARY KEY,
    data       JSONB NOT NULL,      -- full McpConnectorRecord: transport, url, headers, env, …
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    slot_name   TEXT PRIMARY KEY,
    files       JSONB NOT NULL,     -- {relative_path: file_content} for every file in the zip
    description TEXT,
    updated_at  DOUBLE PRECISION NOT NULL
);
```

**Why.** Same root cause as every other file-based store: a pod restart deletes them.
Before this migration, uploading an MCP connector on orchestrator pod A and then having
pod B handle a Phase 2 run would see an empty registry. Skills uploaded via the WorkArea
UI would vanish on the next deploy. Both are operator-configured resources that must
survive pod restarts and be available from any pod.

**What did not change.** The UX is identical: `POST /simagix/mcp-connectors` upserts a
connector, `GET /simagix/mcp-connectors` lists them, `DELETE` removes one. Same for
`/simagix/skills`. The agent-facing code (`build_mcp_server_specs()`, `_connector_to_spec()`,
`to_cursor_sdk_servers()`, `to_adk_mcp_toolsets()`) is unchanged — it still receives fully
resolved specs and passes them to the agent exactly as before.

**Skills are materialized before each agent run (same pattern as chatbot attachments).**
Skills stored as JSONB text can't be read directly by ADK's `load_skill_from_dir()` or
by Cursor's `.cursor/skills/` directory scanning — both require files on disk. Two
materializers run before their respective agent calls:
- `copy_all_to_cursor_scratch(workspace_root, scratch_dir)` → writes
  `scratch_dir/.cursor/skills/<slot>/<file>` from PG `files` JSONB.
- `build_adk_skill_toolset_all(workspace_root)` → writes to
  `operator_skills_dir/<slot>/<file>` from PG, then calls `load_skill_from_dir`.

In both cases: PG is source of truth, disk is a per-call rebuild cache.

**Frontmatter name sync.** Cursor SDK and ADK both require `name:` in `SKILL.md` to
match the slot directory name. Previously this was patched on disk after extraction.
After migration, `_sync_skill_frontmatter_name_content()` applies the fix in-memory
on the SKILL.md string before the JSONB is stored — so every materialization gets the
correct name with no re-patching.

**Alternatives rejected.**
- *Pass connector config directly to agents instead of storing it* — every Phase 2
  session would need the caller to supply the full connector list at request time. The
  WorkArea UI model (register once, referenced by id per session) is intentionally
  decoupled from request payloads.
- *Store skill zip bytes as BLOB in PG* — works but loses queryability. Storing
  `{rel_path: content}` JSONB means a future "show file X from skill Y" API is a
  `SELECT files->>'SKILL.md'` with no extra round-trips.

**Q: Why not store skill files as separate rows (one row per file)?**
Skills are always read as a unit: every materializer reads the entire `files` JSONB for
a slot and writes all files. No consumer filters inside a skill. One JSONB row per slot
gives upsert semantics identical to replacing the directory — a single `ON CONFLICT DO
UPDATE` atomically replaces all files.

**Q: What if a skill has binary files?**
Currently text-only files are assumed (markdown, Python scripts, config). Binary files
are stored with `errors='replace'` on UTF-8 decode — lossy. The correct fix if binary
assets become necessary is to base64-encode them in the JSONB value. Documented boundary,
not a hidden assumption.

**Tradeoffs accepted.**
- Each agent run materializes all skills to disk (proportional to total skill size, not
  per-skill). Acceptable because skills are small text files.
- Zip extraction still requires a temp dir per upload. The temp dir is destroyed
  immediately after the JSONB is built — no lingering files.

---

## Decision 13 — Phase 2 hardening: survival gaps closed (implemented)

Five gaps remained after step 4 where the system could lose state or crash after a pod
restart. All five are now fixed.

### 13a — `hatchet_summary_ready()` → PG

**Before.** `workspace.hatchet_summary_ready(run_id)` checked if
`simagix-workspace/.../hatchet/summary.json` existed on disk.

**After.** `EvidenceLoader(run_id)._load("hatchet_summary") is not None` — checks the
`evidence` table. The hatchet summary was already being ingested to PG in step 3 (Decision 5).
The file check just never got updated.

**Why this matters.** After pod restart, hatchet summary data is in PG but the disk file
is gone. All callers that asked "is hatchet analysis ready?" (`catalog.py`,
`hatchet_retry.py`, `web/routes.py`) would incorrectly return False, hiding hatchet
results in the UI and blocking Phase 2 for runs that already had a completed analysis.

### 13b — `has_mongodb_log_inputs()` → disk + PG fallback

**Before.** Returned `bool(list_mongodb_log_files(run_id))` — filesystem only.

**After.** Disk first; if no disk files, query `SELECT 1 FROM hatchet_logs WHERE run_id = %s`.

**Why disk first, not pure PG.** `has_mongodb_log_inputs` has two callers with different
semantics:
- *Display* (catalog, run detail): "has the user ever uploaded logs?" — PG fallback is
  correct (ingested rows exist even if disk files are gone).
- *Retry gate* (`hatchet_retry.py`): "can we re-run hatchet?" — requires raw log files
  on disk because the retry enqueues a hatchet job that reads them. But `hatchet_retry.py`
  also checks `log_dir.is_dir()` two lines later, so even if the PG check passes for a
  disk-absent run, the retry is blocked correctly by the second check.

**Tradeoff.** The display callers will briefly show "has logs" for a run where the raw
files were cleaned up after ingest but hatchet was never completed. Acceptable —
"has logs" is informational, not gatekeeping.

### 13c — Startup reset for stuck phase2 status

**Problem.** The thread pool in `runner.py` dies when the orchestrator pod restarts. Any
`phase2_state` row with `key='status'` stuck at `"running_investigation"` or
`"running_rca"` would never transition to `failed` — the UI would show a spinner forever.

**Fix.** `ensure_schema()` in `connection.py` runs one UPDATE immediately after applying
the DDL, once per process start:

```sql
UPDATE phase2_state
SET data = '"failed"'::jsonb, updated_at = <now>
WHERE key = 'status'
  AND data::text IN ('"running_investigation"', '"running_rca"')
```

**Why here.** `ensure_schema()` is the single process-startup hook that every code path
already hits before its first query. Adding the reset here means it runs exactly once,
before any status is read or written by the new process.

**Why `data::text IN (...)` instead of a JSONB operator.** Avoids JSONB operator
precedence subtleties. A JSONB string `"running_investigation"` has `data::text =
'"running_investigation"'` (with the JSON string quotes). Text comparison is unambiguous
and no less efficient on a tiny table.

**Tradeoff.** A pod restart marks genuinely mid-run investigations as failed even if the
LLM was 90% done. The user must re-run. Acceptable — this matches the semantics of any
stateful crash, and PG preserves the last checkpoint (report/investigation/tool_trace)
so re-runs resume from a richer starting state than cold start.

### 13d — `bundle_cwd` removed from Cursor provider

**Before.** `cursor/provider.py:_agent_options()`:
```python
bundle_cwd = str(session.evidence.bundle_dir)
scratch_cwd = str(session.ensure_chatbot_scratch_dir())
agent_cwd = scratch_cwd if include_mcp else bundle_cwd
```

**After.**
```python
agent_cwd = str(session.ensure_chatbot_scratch_dir())
```

**Why `bundle_dir` was `""`.**  `bundle_dir` is a field on `Tier1Context` (the Pydantic
schema). After step 3 moved all evidence to PG, `EvidenceLoader.load_tier1()` set it to
`""` (empty string) — there is no bundle directory. Passing `""` as `cwd` to the Cursor
SDK is undefined behaviour (resolves to the process working directory or errors).

**Why the clarify phase doesn't need a `cwd` at all.** The clarify phase runs with
`include_mcp=False` — no MCP servers, no custom tools, pure text completion. The agent
doesn't invoke any file tools, so `cwd` is never consulted. Using `scratch_cwd` is
correct and consistent.

### 13e — Grafana SimpleJSON endpoints implemented (step 5 done)

See Decision 4 for the full protocol description. `api/grafana_simple.py` now serves:

- `GET /grafana/simple/` → 200 health.
- `GET /grafana/simple/config` → Grafana base URL + anomaly / all-metrics dashboard UIDs.
- `GET /grafana/simple/runs/{run_id}/range` → padded `{from,to}` for full capture plus
  `{anomaly_from,anomaly_to,has_anomalies}` from `top_anomaly_windows` (Evidence deep links).
- `POST /grafana/simple/search` → two modes:
  - `target == "runs"` → `SELECT DISTINCT run_id FROM metrics` — used to populate
    the `$run_id` Grafana dashboard variable dropdown.
  - otherwise → `SELECT DISTINCT name FROM metrics` — metric name list for panel editor.
- `POST /grafana/simple/query` → target format `<run_id>/<metric_name>` (Grafana
  substitutes `$run_id` before sending). Returns `[[value, ts_ms], ...]`.
- `POST /grafana/simple/annotations` → reads `executive_context.top_anomaly_windows`
  from the `evidence` table for the run_id in `annotation.query` (Grafana substitutes
  `$run_id` here too). Returns time-range regions with ±5-minute padding.

**Q: The anomaly window in the old approach was a pre-built Grafana URL with `?from=`
and `?to=`. How does the new approach replicate that?**
**Anomaly View** deep-links absolute `from`/`to` to the union of `top_anomaly_windows`
(±5 min). **All Metrics** uses the full metric min/max. Both also draw anomaly
**annotations** as shaded regions. Table panels (`assessment`, `host_info`) from the
old ftdc-api dashboards are omitted — SimpleJSON only serves timeseries.
**Q: The old approach had an `anomaly_focus_url` pointing to a specific dashboard.
Is that gone?**
The old dashboard URL was Docker-stack-specific (it included the ftdc-api base URL and
the Docker Compose Grafana port). With the Docker stack removed, those URLs are invalid.
The new approach uses the ported dashboard (Decision 4) with the `$run_id` variable;
users switch runs via the dropdown, not via a new URL per run.

**Tradeoff accepted.** The annotation-based anomaly window requires a one-time Grafana
annotation configuration (point at this datasource, query = `$run_id`). The old deep-link
was zero-config from the app's perspective. Acceptable because the annotation approach is
more flexible (users can toggle it on/off per dashboard) and doesn't couple the app to
Grafana's URL structure.

---

## Chatbot scratch directory — lifecycle and K8s implications

`chatbot_scratch_dir` resolves to:
```
workspace_root/simagix-workspace/uploads/<run_id>/phase2/llm/<llm>/chatbot_scratch/
```

This is under `workspace_root`, which in K8s is mounted as `emptyDir` — disposable pod
storage. The directory does not pre-exist; `ensure_chatbot_scratch_dir()` calls
`mkdir(parents=True, exist_ok=True)` on the first chatbot call.

**Before step 4.** The same parent directory held eight durable JSON files:
`latest_report.json`, `investigation.json`, `budget_state.json`, `tool_trace.json`,
`session_metadata.json`, `chatbot_chat.json`, `chatbot_scratch/attachments/*`. A pod
restart deleted all of them — sessions were lost. This is the root reason step 4 existed.

**After step 4.** Only `chatbot_scratch/` remains on disk, and only as a materialization
cache. The source of truth for every attachment is `phase2_state` under
`attachment:<stored_name>` keys. `materialize_attachments()` rebuilds the files before
each LLM call. Sequence after pod restart + first chatbot message:

1. Pod starts, `ensure_schema()` runs (DDL + stuck-status reset).
2. User sends a chatbot message.
3. `ensure_chatbot_scratch_dir()` → `mkdir` creates the dir fresh.
4. `materialize_attachments()` queries PG for `attachment:*` keys, writes files to disk.
5. LLM call runs with the correct `cwd` pointing at the scratch dir.
6. LLM reads/greps the attachment files by path. Nothing is lost.

**Q: Why is the scratch dir under `uploads/<run_id>/` instead of a global temp dir?**
Isolation. Each session gets its own scratch space; the LLM can't accidentally read
another run's attachments. Using the run's own upload subtree keeps the path predictable
and debuggable (you can look at a specific pod's disk to inspect what a session saw).

**Q: Is there any state the chatbot loses across a pod restart?**
No durable state. The chat history, report, investigation, attachments — all in PG. The
only thing lost is the in-memory `phase2_session_store` cache (a Python dict of active
sessions), which is a performance cache, not a data store. The first request after restart
re-loads the session from PG into the cache.

---

## Deferred / shelved (in priority order if revisited)

1. **Robust retry + crash recovery** — lease heartbeat + stale-`PROCESSING` reaper;
   bounded auto-retry. Today only self-requeue on the *same* worker restart (Decision 7).
   Tracked in [PROJECT_STATUS.md](PROJECT_STATUS.md) § Other future work.
2. **`LISTEN` / `NOTIFY` instead of worker poll** — wake workers on enqueue; keep a slow
   poll as safety net. Same `SKIP LOCKED` claim path.
3. **SSE instead of UI status polling** — push job / Phase 2 transitions to the browser;
   poll remains fallback. Complements (2): DB notify → API → SSE.
4. **K8s Jobs for decode isolation** — if a single decode can OOM a whole worker replica
   and that matters. Additive behind the subprocess seam.
5. **Hatchet Postgres backend in the fork** — if ingest of huge hatchet.db files becomes
   the bottleneck.
6. **MinIO for raw uploads** — if uploads regularly exceed ~1GB.
7. **Multi-run in-memory ftdc-api** — obsolete; superseded by Decision 4.
8. **Grafana replaced by in-app uPlot charts** — reopens only if maintaining ported
   dashboards becomes painful.

## Migration order

1. `jobs` schema + Postgres `JobQueue` replacing the file queue outright (no fallback;
   `DATABASE_URL` required everywhere). ← **done** (backend/app/db/,
   backend/app/jobs/queue.py, backend/tests/conftest.py)
2. Job status store + run catalog job reads → Postgres. ← **done** (`job_status`
   table; `JobStore` is a thin PG wrapper — no in-memory cache, no JSON records;
   catalog reads jobs via `job_store.list_all()`; run *discovery* still walks
   uploads/ on disk until step 3 ingests run metadata).
3. Ingest step + consumer migration + file renames (Decision 10):
   - New: `jobs/ingest.py`, `simagix/evidence/` subfolder
   - Renamed: `pipeline.py`→`ftdc_job.py`, `retry.py`→`ftdc_retry.py`,
     `hatchet.py`→`hatchet_job.py`, `bundle.py`→`evidence/loader.py`,
     `fallback_tools.py`→`evidence/ftdc_tools.py`, `evidence_service.py`→`rca_service.py`,
     `prompt.py`→`evidence_block.py`, `grafana_routes.py`→`api/grafana.py`,
     `llm/llm_paths.py`→`llm/paths.py`
   - Deleted: `hatchet_export.py`, `hatchet_summary.py`, `hatchet_readiness.py`,
     `grafana/stack.py`
   - Consumers (`evidence/loader.py`, `evidence/ftdc_tools.py`, `evidence/hatchet_tools.py`)
     rewritten to query Postgres instead of reading files/SQLite.
4. Phase 2 state → Postgres; blocking handlers → async + poll; frontend polling.
   `llm/paths.py` deleted (pure helpers moved to `llm/state.py`). ← **done**
   (Decision 11: `phase2_state` table; `llm/runner.py` thread pool;
   `POST /phase2/run|clarify` return 202 + status polling; budget and tool
   trace shared through PG; chatbot attachments in PG with local scratch cache;
   duplicate `simagix/prompt.py` deleted.)
5. Grafana datasource endpoints (`grafana/datasource.py`, `api/grafana.py`) + dashboard
   port; `grafana/links.py` deleted; rename `anomaly_dashboard.py`→`dashboard.py`.
   ← **done** (Decision 13e: `api/grafana_simple.py` serves SimpleJSON at
   `/grafana/simple/`; `/search` with `target="runs"` populates `$run_id` variable;
   `/query` uses `<run_id>/<metric_name>` targets; `/annotations` returns
   `top_anomaly_windows` from evidence table. `grafana/links.py` and Docker-stack
   endpoints still present; to be deleted in step 6 cleanup.)
6. `raw_chunks` upload transfer; bake binaries; de-dockerize scripts; Helm charts
   (mirror Merged Dev's `deploy/helm/` layout: ui / orchestrator / worker / grafana /
   postgres).
