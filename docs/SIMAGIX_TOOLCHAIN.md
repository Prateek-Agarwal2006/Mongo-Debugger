# Simagix Toolchain

Reference for each tool in the Simagix diagnostic suite and its role in Mongo Debugger.

## Tool matrix

| Tool | Input | Output | Status | Role in RCA |
|------|-------|--------|--------|-------------|
| **mongo-ftdc** | `diagnostic.data` | HTML report, tiered export bundle | Ready | Primary — deterministic analysis |
| **Hatchet** | `mongod.log` | Slow query / COLLSCAN report | Blocked | Future tier_1 enricher |
| **Keyhole** | `MONGO_URI` | Cluster metadata JSON | Blocked | Future tier_1 enricher |
| **Maobi** | Keyhole output | Health report PDF/HTML | Blocked | Future human summary |

## mongo-ftdc

**Repository:** `repos/mongo-ftdc` ([simagix/mongo-ftdc](https://github.com/simagix/mongo-ftdc))

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
| `run-grafana-stack.sh` | Grafana `:3030` + FTDC API `:5408` (shared stack) |

All scripts require Docker. On Mac: `colima start --cpu 4 --memory 8` before running.

**Custom additions:**

- `cmd/llm-export/` — tiered evidence exporter
- `diagnosis.go` — `DetectedAt` uses incident time, not export time

## Hatchet

**Repository:** `repos/hatchet` ([simagix/hatchet](https://github.com/simagix/hatchet))

**Input:** MongoDB log files in `tmp/mongodb-logs/`

**Output:** `reports/hatchet/` — slow queries, COLLSCANs, connection issues

**Blocked because:** No MongoDB logs provided yet.

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
| hatchet | `https://github.com/simagix/hatchet.git` | `c109eed` |

## Related documentation

- [Export Contract](export_contract.md)
- [Simagix Workspace](SIMAGIX_WORKSPACE.md)
- [Operations Guide](OPERATIONS.md)
- [Architecture](ARCHITECTURE.md)
