# Simagix Toolchain

Reference for each tool in the Simagix diagnostic suite and its role in Mongo Debugger.

**Last updated:** 2026-06-24

## Tool matrix

| Tool | Input | Output | Status | Role in RCA |
|------|-------|--------|--------|-------------|
| **mongo-ftdc** | `diagnostic.data` | HTML report, tiered export bundle | Ready | Primary — deterministic analysis |
| **Hatchet** | MongoDB log files | `hatchet.db`, `summary.json` | Planned | Optional log tier_1 enricher |
| **Keyhole** | `MONGO_URI` | Cluster metadata JSON | Blocked | Future tier_1 enricher |
| **Maobi** | Keyhole output | Health report PDF/HTML | Blocked | Future human summary |

## mongo-ftdc

**Repository:** `simagix-workspace/repos/mongo-ftdc` — **vendored in this git repo** (based on [simagix/mongo-ftdc](https://github.com/simagix/mongo-ftdc)), including local **`cmd/ftdc-slice`** for tier-3 index/catalog/window. Kind Dockerfiles build `llm-export` + `ftdc-slice` from this tree; no separate upstream clone required.

**What it does:**

- Decodes FTDC binary files in parallel
- Extracts normalized time-series metrics
- Runs assessment scoring (p5/median/p95 per metric)
- Runs diagnosis rules (findings, anomaly detection)
- Serves Grafana dashboards (optional)

**Our wrappers:**

| Script | Purpose |
|--------|---------|
| `run-mongo-ftdc.sh` | Human HTML + console report |
| `run-llm-export.sh` | Tiered evidence bundle for RCA backend |
| `run-mongo-ftdc-pipeline.sh` | Both with shared `run_id` |
| `run-grafana-stack.sh` | Build `mongo-debugger/ftdc:local` + Grafana `:3030` + FTDC API `:5408` (shared stack) |
| `build-ftdc-local.sh` | Patched `mftdc -server` (deferred `/grafana/dir` load) → `mongo-debugger/ftdc:local` |

All scripts require Docker. On Mac: `colima start --cpu 4 --memory 8` before running.

**Custom additions:**

- `cmd/llm-export/` — tiered evidence exporter
- `diagnosis.go` — `DetectedAt` uses incident time, not export time

**Local patch (Grafana server):** `patches/mftdc-server-deferred-load.patch` — `mftdc -server` with no directory args starts HTTP on `:5408` and waits for `POST /grafana/dir` (no `tmp/diagnostic.data` bootstrap). Build: `build-ftdc-local.sh` → `mongo-debugger/ftdc:local`. Upload pipeline one-shot runs may still use upstream `simagix/ftdc:latest`.

## Hatchet

**Repository:** `repos/hatchet` ([simagix/hatchet](https://github.com/simagix/hatchet)) — **gitignored**; clone via `scripts/setup-simagix-repos.sh`.

**Upstream pin:** `c109eed` (v0.8.10). **Local patch required** for multi-file `-merge` — see below.

### Local patch: `-merge` drop gate

Upstream `Begin()` always calls `Drop()` (since `fd28370`, Dec 2025) to replace data on re-process. That breaks `-merge`: file 2+ wipes file 1 from the shared `merge` tables.

| Artifact | Purpose |
|----------|---------|
| `simagix-workspace/patches/hatchet-merge-drop-gate.patch` | Tracked patch (apply after clone) |
| `simagix-workspace/scripts/build-hatchet-local.sh` | Build `mongo-debugger/hatchet:local` from patched repo |
| `scripts/setup-simagix-repos.sh` | Clones hatchet + applies patch |

**Gate logic:** drop only when **not** (`-merge` && file index > 1). File 1 still drops — replaces a prior merged run. Files 2+ append with distinct `marker` values.

**Verify after clone/build:**

```bash
colima start --cpu 4 --memory 8
simagix-workspace/scripts/build-hatchet-local.sh
# extract logs/replica.tar.gz from hatchet repo; then:
docker run --rm -v "$PWD:/w" -w /w mongo-debugger/hatchet:local \
  /hatchet -merge -url /w/hatchet.db rs1.log rs2.log rs3.log
sqlite3 hatchet.db "SELECT marker, COUNT(*) FROM merge GROUP BY marker;"
# expect markers 1, 2, 3 and ~16008 total rows
```

Do **not** use `simagix/hatchet:latest` from Docker Hub for multi-file merge until upstream fixes land. We are not pushing this patch to GitHub — the patch file in this repo is the source of truth.

**Input:** MongoDB log files uploaded later on the run page to `uploads/<run_id>/inputs/mongodb-logs/`.

**Planned run output:** `uploads/<run_id>/phase1/hatchet/` (worker script: `run-hatchet-job.sh`)

| File | Purpose |
|------|---------|
| `hatchet.db` | Hatchet SQLite store; one analysis row in table `hatchet` for v1 |
| `summary.json` | Mongo Debugger tier-1 log evidence for Phase 2 |
| `status.json` | Job metadata: source files, Hatchet name, row counts, errors |

**How v1 uses Hatchet:**

- The FTDC run is created first; logs are a second optional upload.
- The existing Phase 1 queue gets a ticket with `job_type: "hatchet"`.
- One job runs Hatchet parse and then exports `summary.json` from SQLite.
- Multiple log files are passed explicitly with `-merge`; the export records `hatchet_name` and a `marker` to source-file map.
- Phase 2 reads `summary.json` if present; v2 exposes Hatchet MCP tools when `hatchet.db` is present.
- v1 does not generate Hatchet HTML reports; avoiding `-report` is simpler and keeps the contract focused on SQLite + JSON.

**Tier-1 summary contents:** metadata, source files, `top_slow_ops_by_avg_ms`, `top_slow_ops_by_total_ms`, separate `collscan_ops`, audit highlights, observed driver versions only, top 10 slowest log examples with ~500-character snippets, and a capped connection timeline. Full logs, full charts, compatibility verdicts, and arbitrary SQL stay out of the prompt.

**Hatchet MCP (v2):** `backend/app/simagix/hatchet_tools.py`, `backend/app/simagix/llm/mcp/servers/hatchet.py`. Tools read the same `hatchet.db` using `summary.json.store_paths`.

**Why not the Hatchet web service:** its pages and REST endpoints are wrappers over the same SQLite `Database` methods (`GetSlowOps`, `GetAuditData`, `GetSlowestLogs`, connection/reslen queries). Reading the DB directly keeps the Phase 2 path deterministic and avoids another long-running service.

## Keyhole

**Repository:** `repos/keyhole` ([simagix/keyhole](https://github.com/simagix/keyhole))

**Input:** Live MongoDB connection (`MONGO_URI`)

**Output:** `tmp/keyhole-output/` — indexes, collections, schema stats

**Blocked because:** No `MONGO_URI` configured.

## Maobi

**Input:** Keyhole output file

**Output:** `reports/maobi/` — human-readable cluster health report

**Blocked because:** Depends on Keyhole output.

## Docker vs local builds

| Approach | When to use |
|----------|-------------|
| Docker (default) | Production runs, repeatable CI, no local Go needed |
| Local Go build | Source debugging, patching `llm-export` |

Docker is preferred. Local repo clones exist for source review and version tracking.

## Cloned versions

| Repo | Remote | Commit |
|------|--------|--------|
| mongo-ftdc | `https://github.com/simagix/mongo-ftdc.git` | `66212fd` |
| keyhole | `https://github.com/simagix/keyhole.git` | `7d3a156` |
| hatchet | `https://github.com/simagix/hatchet.git` | `c109eed` + **`patches/hatchet-merge-drop-gate.patch`** |

## Related documentation

- [Export Contract](export_contract.md)
- [Simagix Workspace](SIMAGIX_WORKSPACE.md)
- [Operations Guide](OPERATIONS.md)
- [Architecture](ARCHITECTURE.md)
